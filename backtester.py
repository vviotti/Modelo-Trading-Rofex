# backtester.py (Refactorizado para Claridad y Configuración Centralizada)

from datetime import datetime, timedelta
import pandas as pd
import uuid
import numpy as np

import api_client
import indicators
import config # Importamos la configuración centralizada

# --- LÓGICA PRINCIPAL DEL BACKTEST ---
def ejecutar_backtest_avanzado(symbol, parametros, datos_completos, verbose=False):
    """
    Ejecuta un backtest intradiario para un conjunto de parámetros.
    - Utiliza datos de velas de 1 minuto.
    - Simula sobre los últimos N días de trading disponibles.
    - Cierra todas las posiciones al final del día.
    - Aplica comisiones y deslizamientos (spread) configurables.
    """
    if verbose: print(f"\n--- Iniciando Backtest con Parámetros:\n{parametros}\n")

    # 1. Usar parámetros desde config.py
    capital = config.CAPITAL_INICIAL
    open_positions = []
    equity_curve = []
    peak_capital = config.CAPITAL_INICIAL
    max_drawdown = 0

    # 2. Determinar el rango de fechas del backtest (últimos N días)
    todos_los_dias = datos_completos.index.normalize().unique()
    dias_de_trading = todos_los_dias[todos_los_dias > todos_los_dias.max() - timedelta(days=config.DIAS_BACKTEST + 1)]

    if verbose: print(f"Período de Backtest: {dias_de_trading.min().strftime('%Y-%m-%d')} al {dias_de_trading.max().strftime('%Y-%m-%d')}")

    regimen_vol_anterior = "BAJA" # Estado inicial

    # 3. Iterar por cada día del período de backtest
    for dia_actual in dias_de_trading:
        # Calcular régimen de Volatilidad y Momento (basado en datos hasta el día anterior)
        dia_anterior = dia_actual - timedelta(days=1)

        # Volatilidad
        fecha_inicio_vol = dia_anterior - timedelta(days=parametros['dias_volatilidad'])
        datos_para_volatilidad = datos_completos.loc[fecha_inicio_vol:dia_anterior]
        regimen_vol = regimen_vol_anterior
        if not datos_para_volatilidad.empty:
            rendimientos_diarios_vol = datos_para_volatilidad['close'].pct_change().resample('D').sum()
            volatilidad_reciente = rendimientos_diarios_vol.std()
            if volatilidad_reciente > parametros['umbral_vol_alto']: regimen_vol = "ALTA"
            elif volatilidad_reciente < parametros['umbral_vol_bajo']: regimen_vol = "BAJA"

        # Momento
        fecha_inicio_mom = dia_anterior - timedelta(days=parametros['dias_momento'])
        datos_para_momento = datos_completos.loc[fecha_inicio_mom:dia_anterior]['close'].resample('D').last()
        regimen_momento = "NEUTRAL"
        if len(datos_para_momento) >= parametros['dias_momento']:
            ma_momento = datos_para_momento.rolling(window=parametros['dias_momento']).mean()
            if not ma_momento.empty and not pd.isna(ma_momento.iloc[-1]) and not pd.isna(datos_para_momento.iloc[-1]):
                if datos_para_momento.iloc[-1] > ma_momento.iloc[-1]: regimen_momento = "POSITIVO"
                else: regimen_momento = "NEGATIVO"

        if verbose: print(f"\n--- {dia_actual.strftime('%Y-%m-%d')} | Vol: {regimen_vol} | Momento: {regimen_momento} ---")
        
        # 4. Iterar por cada vela (minuto) del día
        velas_del_dia = datos_completos.loc[dia_actual.strftime('%Y-%m-%d')]
        for i in range(len(velas_del_dia)):
            fila_actual = velas_del_dia.iloc[i]

            # A. Lógica de Cierre de Posiciones Abiertas
            for trade in list(open_positions):
                precio_actual = fila_actual['close']
                razon_salida = None
                es_largo = trade['direction'] == 'LONG'

                if trade['estrategia'] == "TENDENCIA":
                    sl = parametros['stop_loss_tendencia']
                    tp = parametros['take_profit_tendencia']
                    if es_largo:
                        if precio_actual <= trade['entry_price'] * (1 - sl): razon_salida = "STOP_LOSS"
                        elif precio_actual >= trade['entry_price'] * (1 + tp): razon_salida = "TAKE_PROFIT"
                    else:
                        if precio_actual >= trade['entry_price'] * (1 + sl): razon_salida = "STOP_LOSS"
                        elif precio_actual <= trade['entry_price'] * (1 - tp): razon_salida = "TAKE_PROFIT"

                elif trade['estrategia'] == "REVERSION":
                    sl = parametros['stop_loss_reversion']
                    if es_largo:
                        if precio_actual <= trade['entry_price'] * (1 - sl): razon_salida = "STOP_LOSS"
                        elif precio_actual >= fila_actual['BBM_20_2.0']: razon_salida = "TAKE_PROFIT (Banda Media)"
                    else:
                        if precio_actual >= trade['entry_price'] * (1 + sl): razon_salida = "STOP_LOSS"
                        elif precio_actual <= fila_actual['BBM_20_2.0']: razon_salida = "TAKE_PROFIT (Banda Media)"

                if razon_salida:
                    precio_salida = precio_actual * (1 - config.SPREAD_SIMULADO_PCT / 2) if es_largo else precio_actual * (1 + config.SPREAD_SIMULADO_PCT / 2)
                    rendimiento = ((precio_salida - trade['entry_price']) / trade['entry_price']) * (1 if es_largo else -1)
                    ganancia_o_perdida = trade['capital_al_abrir'] * rendimiento
                    valor_salida = trade['capital_al_abrir'] * (1 + rendimiento)
                    comision_cierre = valor_salida * config.COMISION_POR_TRADE
                    capital += ganancia_o_perdida - comision_cierre
                    trade.update({'salida_fecha': fila_actual.name, 'salida_precio': precio_salida, 'razon_salida': razon_salida, 'rendimiento_%': rendimiento * 100, 'capital_final': capital})
                    if verbose: print(f"  CIERRE {trade['direction']} {razon_salida} (ID: ...{str(trade['id'])[-4:]}): P: {precio_salida:.2f}, R: {rendimiento*100:.2f}%")
                    open_positions.remove(trade)

            # B. Lógica de Apertura de Nuevas Posiciones
            if len(open_positions) < config.MAX_POSICIONES_ABIERTAS and i > 0:
                fila_anterior = velas_del_dia.iloc[i-1]
                entrada, razon_entrada, estrat, direccion = False, None, None, None

                if regimen_vol == "BAJA" and regimen_momento == "POSITIVO":
                    if fila_anterior['MA_9'] < fila_anterior['MA_21'] and fila_actual['MA_9'] > fila_actual['MA_21'] and fila_actual['RSI_14'] < 70:
                        entrada, razon_entrada, estrat, direccion = True, 'TEND_ALCISTA', "TENDENCIA", "LONG"
                elif regimen_vol == "ALTA" and regimen_momento == "POSITIVO":
                    if fila_actual['close'] < fila_actual['BBL_20_2.0']:
                        entrada, razon_entrada, estrat, direccion = True, 'REV_ALCISTA', "REVERSION", "LONG"
                elif regimen_vol == "BAJA" and regimen_momento == "NEGATIVO":
                    if fila_anterior['MA_9'] > fila_anterior['MA_21'] and fila_actual['MA_9'] < fila_actual['MA_21'] and fila_actual['RSI_14'] > 30:
                        entrada, razon_entrada, estrat, direccion = True, 'TEND_BAJISTA', "TENDENCIA", "SHORT"
                elif regimen_vol == "ALTA" and regimen_momento == "NEGATIVO":
                    if fila_actual['close'] > fila_actual['BBU_20_2.0']:
                        entrada, razon_entrada, estrat, direccion = True, 'REV_BAJISTA', "REVERSION", "SHORT"

                if entrada and fila_actual['volume'] > fila_actual['volume_MA_50'] * config.FACTOR_AUMENTO_VOLUMEN:
                    precio_entrada_val = fila_actual['close'] * (1 + config.SPREAD_SIMULADO_PCT / 2) if direccion == "LONG" else fila_actual['close'] * (1 - config.SPREAD_SIMULADO_PCT / 2)
                    capital_al_abrir = capital / (config.MAX_POSICIONES_ABIERTAS - len(open_positions))
                    comision_apertura = capital_al_abrir * config.COMISION_POR_TRADE
                    capital -= comision_apertura
                    nuevo_trade = { 'id': uuid.uuid4(), 'direction': direccion, 'razon_entrada': razon_entrada, 'estrategia': estrat, 'entrada_fecha': fila_actual.name, 'entry_price': precio_entrada_val, 'capital_al_abrir': capital_al_abrir }
                    open_positions.append(nuevo_trade)
                    if verbose: print(f"  ENTRADA {razon_entrada} (ID: ...{str(nuevo_trade['id'])[-4:]}): P: {precio_entrada_val:.2f} (Vol OK)")

            # C. Lógica de Cierre al Final del Día
            if i == len(velas_del_dia) - 1 and len(open_positions) > 0:
                if verbose: print(f"  --- CERRANDO {len(open_positions)} POSICIONES POR FIN DEL DÍA ---")
                for trade in list(open_positions):
                    es_largo = trade['direction'] == 'LONG'
                    precio_salida = fila_actual['close'] * (1 - config.SPREAD_SIMULADO_PCT / 2) if es_largo else fila_actual['close'] * (1 + config.SPREAD_SIMULADO_PCT / 2)
                    rendimiento = ((precio_salida - trade['entry_price']) / trade['entry_price']) * (1 if es_largo else -1)
                    ganancia_o_perdida = trade['capital_al_abrir'] * rendimiento
                    valor_salida = trade['capital_al_abrir'] * (1 + rendimiento)
                    comision_cierre = valor_salida * config.COMISION_POR_TRADE
                    capital += ganancia_o_perdida - comision_cierre
                    trade.update({'salida_fecha': fila_actual.name, 'salida_precio': precio_salida, 'razon_salida': 'FIN_DEL_DIA', 'rendimiento_%': rendimiento * 100, 'capital_final': capital})
                    if verbose: print(f"  CIERRE FIN_DEL_DIA {trade['direction']} (ID: ...{str(trade['id'])[-4:]}): P: {precio_salida:.2f}, R: {rendimiento*100:.2f}%")
                    open_positions.remove(trade)

            # D. Registro de Equity y Drawdown
            valor_posiciones_abiertas = sum(
                t['capital_al_abrir'] * (1 + (((fila_actual['close'] - t['entry_price']) / t['entry_price']) * (1 if t['direction'] == 'LONG' else -1)))
                for t in open_positions
            )
            equity_actual = capital + valor_posiciones_abiertas
            equity_curve.append({'timestamp': fila_actual.name, 'equity': equity_actual})
            if equity_actual > peak_capital: peak_capital = equity_actual
            drawdown = (peak_capital - equity_actual) / peak_capital
            if drawdown > max_drawdown: max_drawdown = drawdown
        
        regimen_vol_anterior = regimen_vol
    
    # 5. Calcular y devolver resultados finales
    rendimiento_total = ((capital - config.CAPITAL_INICIAL) / config.CAPITAL_INICIAL) * 100
    if verbose: print(f"\nResultado final del backtest: {rendimiento_total:.2f}%")
    
    return {
        "rendimiento": rendimiento_total,
        "max_drawdown": max_drawdown * 100,
        "max_value": peak_capital,
        "equity_curve": equity_curve,
        "parametros": parametros
    }

# --- FUNCIÓN PARA EJECUTAR EL BACKTESTER DE FORMA INDEPENDIENTE ---
if __name__ == "__main__":
    print("--- EJECUTANDO BACKTESTER EN MODO INDEPENDIENTE (DETALLADO) ---")

    token = api_client.obtener_token()
    if not token:
        print("Fallo al obtener token. Abortando.")
    else:
        symbol_to_test = api_client.encontrar_futuro_dolar_mas_corto(token)
        if not symbol_to_test:
            print("No se pudo encontrar el símbolo del futuro. Abortando.")
        else:
            print(f"--- Símbolo a testear: {symbol_to_test} ---")

            # Descargar un historial suficientemente largo para los cálculos de régimen
            parametros = config.ESTRATEGIA_PARAMS
            dias_historial_requerido = max(parametros['dias_volatilidad'], parametros['dias_momento']) + config.DIAS_BACKTEST + 5
            fecha_inicio_historial = datetime.now() - timedelta(days=dias_historial_requerido)

            trades_data = api_client.obtener_datos_historicos(
                token,
                symbol_to_test,
                fecha_inicio_historial.strftime('%Y-%m-%d'),
                datetime.now().strftime('%Y-%m-%d')
            )

            if trades_data:
                datos_completos = indicators.procesar_y_calcular_indicadores(trades_data)
                if datos_completos is not None:
                    print("\n--- Datos procesados. Iniciando backtest detallado... ---")
                    resultados = ejecutar_backtest_avanzado(symbol_to_test, parametros, datos_completos, verbose=True)

                    print("\n\n--- RESUMEN DEL BACKTEST INDEPENDIENTE ---")
                    print(f"Rendimiento Final: {resultados['rendimiento']:.2f}%")
                    print(f"Máximo Drawdown: {resultados['max_drawdown']:.2f}%")
                    print(f"Valor Máximo del Portafolio: ${resultados['max_value']:,.2f}")
                    print("-----------------------------------------")