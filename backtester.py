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
    open_positions_m1 = [] # Posiciones del Modelo 1 (Volatilidad/Momentum)
    open_positions_m2 = [] # Posiciones del Modelo 2 (Order Book)
    equity_curve = []
    peak_capital = config.CAPITAL_INICIAL
    max_drawdown = 0

    # 2. Determinar el rango de fechas del backtest (últimos N días)
    todos_los_dias = datos_completos.index.normalize().unique()
    dias_de_trading = todos_los_dias[todos_los_dias > todos_los_dias.max() - timedelta(days=config.DIAS_BACKTEST + 1)]

    if verbose: print(f"Período de Backtest: {dias_de_trading.min().strftime('%Y-%m-%d')} al {dias_de_trading.max().strftime('%Y-%m-%d')}")

    # 3. Iterar por cada día del período de backtest
    for dia_actual in dias_de_trading:
        if verbose: print(f"\n--- {dia_actual.strftime('%Y-%m-%d')} ---")
        
        # 4. Iterar por cada vela (minuto) del día
        velas_del_dia = datos_completos.loc[dia_actual.strftime('%Y-%m-%d')]
        for i in range(len(velas_del_dia)):
            fila_actual = velas_del_dia.iloc[i]

            # A. Lógica de Cierre de Posiciones Abiertas (Modelo 1)
            for trade in list(open_positions_m1):
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
                    # El Take Profit para una reversión es la media de las bandas a corto plazo
                    tp_price = (fila_actual['BBU_SHORT'] + fila_actual['BBL_SHORT']) / 2
                    if es_largo:
                        if precio_actual <= trade['entry_price'] * (1 - sl): razon_salida = "STOP_LOSS"
                        elif precio_actual >= tp_price: razon_salida = "TAKE_PROFIT (Banda Media Corto Plazo)"
                    else: # Es un SHORT
                        if precio_actual >= trade['entry_price'] * (1 + sl): razon_salida = "STOP_LOSS"
                        elif precio_actual <= tp_price: razon_salida = "TAKE_PROFIT (Banda Media Corto Plazo)"

                if razon_salida:
                    precio_salida = precio_actual * (1 - config.SPREAD_SIMULADO_PCT / 2) if es_largo else precio_actual * (1 + config.SPREAD_SIMULADO_PCT / 2)
                    rendimiento = ((precio_salida - trade['entry_price']) / trade['entry_price']) * (1 if es_largo else -1)
                    ganancia_o_perdida = trade['capital_al_abrir'] * rendimiento
                    valor_salida = trade['capital_al_abrir'] * (1 + rendimiento)
                    comision_cierre = valor_salida * config.COMISION_POR_TRADE
                    # CORRECCIÓN: Devolver el valor total de la posición (principal + PnL) al capital líquido.
                    capital += valor_salida - comision_cierre
                    trade.update({'salida_fecha': fila_actual.name, 'salida_precio': precio_salida, 'razon_salida': razon_salida, 'rendimiento_%': rendimiento * 100, 'capital_final': capital})
                    if verbose: print(f"  CIERRE {trade['direction']} {razon_salida} (ID: ...{str(trade['id'])[-4:]}): P: {precio_salida:.2f}, R: {rendimiento*100:.2f}%")
                    open_positions_m1.remove(trade)

            # B. Lógica de Apertura de Nuevas Posiciones (Modelo 1: Volatilidad + Momentum)

            # Regla de Cierre de Mercado: No abrir nuevas posiciones después de las 14:55
            hora_actual = fila_actual.name.time()
            is_after_market_close = hora_actual >= datetime.strptime(config.HORA_CIERRE_MERCADO, '%H:%M').time()

            # Solo operar si no hemos alcanzado el límite de posiciones y el mercado está abierto
            if not is_after_market_close and (len(open_positions_m1) + len(open_positions_m2)) < config.MAX_POSICIONES_ABIERTAS:

                # 1. Determinar Momentum
                momentum_is_bullish = fila_actual['EMA_10'] > fila_actual['EMA_30']
                momentum_is_bearish = fila_actual['EMA_10'] < fila_actual['EMA_30']

                entrada, razon_entrada, estrat, direccion = False, None, None, None

                # 2. Lógica de "Alta Certeza" (Contra-tendencia sobre bandas largas)
                # Solo si las bandas largas no son NaN
                if pd.notna(fila_actual['BBU_LONG']) and pd.notna(fila_actual['BBL_LONG']):
                    if momentum_is_bullish and fila_actual['close'] > fila_actual['BBU_LONG']:
                        entrada, razon_entrada, estrat, direccion = True, 'M1_REVERSAL_SHORT', "REVERSION", "SHORT"
                    elif momentum_is_bearish and fila_actual['close'] < fila_actual['BBL_LONG']:
                        entrada, razon_entrada, estrat, direccion = True, 'M1_REVERSAL_LONG', "REVERSION", "LONG"

                # 3. Lógica de Tendencia (Mean Reversion sobre bandas cortas, a favor del momentum)
                if not entrada: # Solo si no se activó una señal de alta certeza
                    if momentum_is_bullish and fila_actual['close'] < fila_actual['BBL_SHORT']:
                        entrada, razon_entrada, estrat, direccion = True, 'M1_TREND_LONG', "TENDENCIA", "LONG"
                    elif momentum_is_bearish and fila_actual['close'] > fila_actual['BBU_SHORT']:
                        entrada, razon_entrada, estrat, direccion = True, 'M1_TREND_SHORT', "TENDENCIA", "SHORT"

                # 4. Ejecutar Entrada si hay señal y volumen suficiente
                if entrada and fila_actual['volume'] > fila_actual['volume_MA_50'] * config.FACTOR_AUMENTO_VOLUMEN:
                    num_posiciones_totales = len(open_positions_m1) + len(open_positions_m2)
                    if capital > 0 and config.MAX_POSICIONES_ABIERTAS > num_posiciones_totales:
                        precio_entrada_val = fila_actual['close'] * (1 + config.SPREAD_SIMULADO_PCT / 2) if direccion == "LONG" else fila_actual['close'] * (1 - config.SPREAD_SIMULADO_PCT / 2)

                        capital_al_abrir = capital / (config.MAX_POSICIONES_ABIERTAS - num_posiciones_totales)
                        comision_apertura = capital_al_abrir * config.COMISION_POR_TRADE

                        capital -= (capital_al_abrir + comision_apertura)

                        nuevo_trade = {
                            'id': uuid.uuid4(),
                            'model': 'Model 1', # Etiquetar el trade
                            'direction': direccion,
                            'razon_entrada': razon_entrada,
                            'estrategia': estrat,
                            'entrada_fecha': fila_actual.name,
                            'entry_price': precio_entrada_val,
                            'capital_al_abrir': capital_al_abrir
                        }
                        open_positions_m1.append(nuevo_trade)
                        if verbose: print(f"  ENTRADA {razon_entrada} (ID: ...{str(nuevo_trade['id'])[-4:]}): P: {precio_entrada_val:.2f} (Vol OK)")

            # C. Lógica de Cierre al Final del Día (o a las 14:55)
            hora_actual = fila_actual.name.time()
            is_eod_close_time = hora_actual >= datetime.strptime(config.HORA_CIERRE_MERCADO, '%H:%M').time()

            if is_eod_close_time or (i == len(velas_del_dia) - 1):
                if len(open_positions_m1) > 0:
                    if verbose: print(f"  --- CERRANDO {len(open_positions_m1)} POSICIONES (MODELO 1) POR FIN DEL DÍA/HORA DE CIERRE ---")
                    for trade in list(open_positions_m1):
                        es_largo = trade['direction'] == 'LONG'
                        precio_salida = fila_actual['close'] * (1 - config.SPREAD_SIMULADO_PCT / 2) if es_largo else fila_actual['close'] * (1 + config.SPREAD_SIMULADO_PCT / 2)
                        rendimiento = ((precio_salida - trade['entry_price']) / trade['entry_price']) * (1 if es_largo else -1)
                        ganancia_o_perdida = trade['capital_al_abrir'] * rendimiento
                        valor_salida = trade['capital_al_abrir'] * (1 + rendimiento)
                        comision_cierre = valor_salida * config.COMISION_POR_TRADE
                        capital += valor_salida - comision_cierre
                        trade.update({'salida_fecha': fila_actual.name, 'salida_precio': precio_salida, 'razon_salida': 'FIN_DEL_DIA', 'rendimiento_%': rendimiento * 100, 'capital_final': capital})
                        if verbose: print(f"  CIERRE FIN_DEL_DIA {trade['direction']} (ID: ...{str(trade['id'])[-4:]}): P: {precio_salida:.2f}, R: {rendimiento*100:.2f}%")
                        open_positions_m1.remove(trade)
                if len(open_positions_m2) > 0:
                    if verbose: print(f"  --- CERRANDO {len(open_positions_m2)} POSICIONES (MODELO 2) POR FIN DEL DÍA ---")
                    for trade in list(open_positions_m2):
                        es_largo = trade['direction'] == 'LONG'
                        precio_salida = fila_actual['close'] * (1 - config.SPREAD_SIMULADO_PCT / 2) if es_largo else fila_actual['close'] * (1 + config.SPREAD_SIMULADO_PCT / 2)
                        rendimiento = ((precio_salida - trade['entry_price']) / trade['entry_price']) * (1 if es_largo else -1)
                        ganancia_o_perdida = trade['capital_al_abrir'] * rendimiento
                        valor_salida = trade['capital_al_abrir'] * (1 + rendimiento)
                        comision_cierre = valor_salida * config.COMISION_POR_TRADE
                        capital += valor_salida - comision_cierre
                        trade.update({'salida_fecha': fila_actual.name, 'salida_precio': precio_salida, 'razon_salida': 'FIN_DEL_DIA', 'rendimiento_%': rendimiento * 100, 'capital_final': capital})
                        if verbose: print(f"  CIERRE FIN_DEL_DIA {trade['direction']} (ID: ...{str(trade['id'])[-4:]}): P: {precio_salida:.2f}, R: {rendimiento*100:.2f}%")
                        open_positions_m2.remove(trade)

            # D. Registro de Equity y Drawdown
            todas_posiciones_abiertas = open_positions_m1 + open_positions_m2
            valor_posiciones_abiertas = sum(
                t['capital_al_abrir'] * (1 + (((fila_actual['close'] - t['entry_price']) / t['entry_price']) * (1 if t['direction'] == 'LONG' else -1)))
                for t in todas_posiciones_abiertas
            )
            equity_actual = capital + valor_posiciones_abiertas
            equity_curve.append({'timestamp': fila_actual.name, 'equity': equity_actual})
            if equity_actual > peak_capital: peak_capital = equity_actual
            drawdown = (peak_capital - equity_actual) / peak_capital
            if drawdown > max_drawdown: max_drawdown = drawdown
    
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
            # Se necesitan ~90 días de historial para el indicador de volatilidad de 3 meses (18000 velas de 1min)
            dias_historial_requerido = config.DIAS_BACKTEST + 95 # 90 días para el indicador + 5 de margen
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