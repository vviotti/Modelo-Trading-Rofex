# backtester.py (Versión Final y Completa)

from datetime import datetime, timedelta
import pandas as pd
import uuid
import numpy as np

import api_client
import indicators
import config

# --- PARÁMETROS FIJOS DE LA SIMULACIÓN ---
SIMBOLO_A_TESTEAR = "DLR/AGO25"
FECHA_FIN = datetime.now()
FECHA_INICIO = FECHA_FIN - timedelta(days=60)
CAPITAL_INICIAL = 1000000 
COMISION_POR_TRADE = 0.001
SPREAD_SIMULADO_PCT = 0.001
FACTOR_AUMENTO_VOLUMEN = 1.5
MAX_POSICIONES_ABIERTAS = 3

def ejecutar_backtest_avanzado(parametros, datos_completos, verbose=False):
    """
    Ejecuta el backtest con un set de parámetros específico.
    - Maneja múltiples posiciones.
    - Utiliza una matriz de régimen 2x2 (Volatilidad x Momento).
    - Filtra las entradas por volumen.
    - Calcula y devuelve métricas de rendimiento avanzadas.
    """
    if verbose:
        print(f"Ejecutando backtest con: {parametros}")
    
    capital = CAPITAL_INICIAL
    open_positions = []
    trades_log = []
    dias_de_trading = datos_completos.index.normalize().unique()
    regimen_vol_anterior = "BAJA"

    # Seguimiento de equity para métricas
    equity_curve = []
    peak_capital = CAPITAL_INICIAL
    max_drawdown = 0

    for dia_actual in dias_de_trading:
        if dia_actual.date() < FECHA_INICIO.date(): continue

        # --- REEVALUACIÓN DIARIA DEL RÉGIMEN ---
        fecha_inicio_vol = dia_actual - timedelta(days=parametros['dias_volatilidad'])
        datos_para_volatilidad = datos_completos.loc[fecha_inicio_vol:dia_actual]
        rendimientos_diarios_vol = datos_para_volatilidad['close'].pct_change().resample('D').sum()
        volatilidad_reciente = rendimientos_diarios_vol.std()
        
        regimen_vol = regimen_vol_anterior
        if volatilidad_reciente > parametros['umbral_vol_alto']: regimen_vol = "ALTA"
        elif volatilidad_reciente < parametros['umbral_vol_bajo']: regimen_vol = "BAJA"

        fecha_inicio_mom = dia_actual - timedelta(days=parametros['dias_momento'])
        datos_para_momento = datos_completos.loc[fecha_inicio_mom:dia_actual]['close'].resample('D').last()
        ma_momento = datos_para_momento.rolling(window=parametros['dias_momento']).mean()
        
        regimen_momento = "NEUTRAL"
        if not ma_momento.empty and len(datos_para_momento) > 1 and not pd.isna(ma_momento.iloc[-1]):
            if datos_para_momento.iloc[-1] > ma_momento.iloc[-1]: regimen_momento = "POSITIVO"
            else: regimen_momento = "NEGATIVO"

        if verbose: print(f"\n--- {dia_actual.strftime('%Y-%m-%d')} | Vol: {regimen_vol} | Momento: {regimen_momento} ---")
        
        velas_del_dia = datos_completos.loc[dia_actual.strftime('%Y-%m-%d')]

        for i in range(len(velas_del_dia)):
            fila_actual = velas_del_dia.iloc[i]

            # A. LÓGICA DE CIERRE
            for trade in list(open_positions):
                precio_actual = fila_actual['close']
                razon_salida = None
                
                if trade['estrategia'] == "TENDENCIA":
                    if precio_actual <= trade['entry_price'] * (1 - parametros['stop_loss_tendencia']): razon_salida = "STOP_LOSS"
                    elif precio_actual >= trade['entry_price'] * (1 + parametros['take_profit_tendencia']): razon_salida = "TAKE_PROFIT"
                elif trade['estrategia'] == "REVERSION":
                    if precio_actual <= trade['entry_price'] * (1 - parametros['stop_loss_reversion']): razon_salida = "STOP_LOSS"
                    elif precio_actual >= fila_actual['BBM_20_2.0']: razon_salida = "TAKE_PROFIT (Banda Media)"

                if razon_salida:
                    precio_salida = fila_actual['close'] * (1 - SPREAD_SIMULADO_PCT / 2)
                    rendimiento = (precio_salida - trade['entry_price']) / trade['entry_price']
                    ganancia_o_perdida = trade['capital_al_abrir'] * rendimiento
                    capital_con_ganancia = capital + ganancia_o_perdida
                    comision_cierre = abs(ganancia_o_perdida) * COMISION_POR_TRADE
                    capital = capital_con_ganancia - comision_cierre
                    trade.update({'salida_fecha': fila_actual.name, 'salida_precio': precio_salida, 'razon_salida': razon_salida, 'rendimiento_%': rendimiento * 100, 'capital_final': capital})
                    if verbose: print(f"  CIERRE {razon_salida} (ID: ...{str(trade['id'])[-4:]}): Precio: {precio_salida:.2f}, Rendimiento: {rendimiento*100:.2f}%")
                    open_positions.remove(trade)

            # B. LÓGICA DE APERTURA
            if len(open_positions) < MAX_POSICIONES_ABIERTAS and i > 0:
                fila_anterior = velas_del_dia.iloc[i-1]
                entrada, razon_entrada, estrategia_entrada = False, None, None

                if regimen_vol == "BAJA" and regimen_momento == "POSITIVO":
                    if fila_anterior['MA_9'] < fila_anterior['MA_21'] and fila_actual['MA_9'] > fila_actual['MA_21'] and fila_actual['RSI_14'] < 70:
                        entrada, razon_entrada, estrategia_entrada = True, 'TEND_ALCISTA', "TENDENCIA"
                elif regimen_vol == "ALTA" and regimen_momento == "POSITIVO":
                    if fila_actual['close'] < fila_actual['BBL_20_2.0']:
                        entrada, razon_entrada, estrategia_entrada = True, 'REV_ALCISTA', "REVERSION"

                if entrada and fila_actual['volume'] > fila_actual['volume_MA_50'] * FACTOR_AUMENTO_VOLUMEN:
                    precio_entrada_val = fila_actual['close'] * (1 + SPREAD_SIMULADO_PCT / 2)
                    capital_al_abrir = capital / (MAX_POSICIONES_ABIERTAS - len(open_positions))
                    comision_apertura = capital_al_abrir * COMISION_POR_TRADE
                    capital -= comision_apertura
                    
                    nuevo_trade = { 'id': uuid.uuid4(), 'razon_entrada': razon_entrada, 'estrategia': estrategia_entrada, 'entrada_fecha': fila_actual.name, 'entry_price': precio_entrada_val, 'capital_al_abrir': capital_al_abrir }
                    open_positions.append(nuevo_trade)
                    trades_log.append(nuevo_trade)
                    if verbose: print(f"  ENTRADA {razon_entrada} (ID: ...{str(nuevo_trade['id'])[-4:]}): Precio: {precio_entrada_val:.2f} (Volumen OK)")

            # C. LÓGICA DE CIERRE AL FINAL DEL DÍA
            if i == len(velas_del_dia) - 1 and len(open_positions) > 0:
                if verbose: print(f"  --- CERRANDO {len(open_positions)} POSICIONES POR FIN DEL DÍA ---")
                for trade in list(open_positions):
                    precio_salida = fila_actual['close'] * (1 - SPREAD_SIMULADO_PCT / 2)
                    rendimiento = (precio_salida - trade['entry_price']) / trade['entry_price']
                    ganancia_o_perdida = trade['capital_al_abrir'] * rendimiento
                    capital_con_ganancia = capital + ganancia_o_perdida
                    comision_cierre = abs(ganancia_o_perdida) * COMISION_POR_TRADE
                    capital = capital_con_ganancia - comision_cierre
                    trade.update({'salida_fecha': fila_actual.name, 'salida_precio': precio_salida, 'razon_salida': 'FIN_DEL_DIA', 'rendimiento_%': rendimiento * 100, 'capital_final': capital})
                    if verbose: print(f"  CIERRE FIN_DEL_DIA (ID: ...{str(trade['id'])[-4:]}): Precio: {precio_salida:.2f}, Rendimiento: {rendimiento*100:.2f}%")
                    open_positions.remove(trade)
            
            # D. REGISTRO DE EQUITY Y DRAWDOWN
            valor_posiciones_abiertas = sum(t['capital_al_abrir'] * (1 + (fila_actual['close'] - t['entry_price']) / t['entry_price']) for t in open_positions)
            equity_actual = capital + valor_posiciones_abiertas
            equity_curve.append({'timestamp': fila_actual.name, 'equity': equity_actual})
            if equity_actual > peak_capital: peak_capital = equity_actual
            drawdown = (peak_capital - equity_actual) / peak_capital
            if drawdown > max_drawdown: max_drawdown = drawdown
        
        regimen_vol_anterior = regimen_vol
    
    rendimiento_total = ((capital - CAPITAL_INICIAL) / CAPITAL_INICIAL) * 100
    if verbose: print(f"\nResultado final: {rendimiento_total:.2f}%")
    
    return { "rendimiento": rendimiento_total, "max_drawdown": max_drawdown * 100, "max_value": peak_capital, "equity_curve": equity_curve, "parametros": parametros }

if __name__ == "__main__":
    parametros_default = config.ESTRATEGIA_PARAMS
    print("--- EJECUTANDO BACKTESTER EN MODO INDEPENDIENTE (DETALLADO) ---")
    token = api_client.obtener_token()
    if token:
        historial_extendido_inicio = FECHA_INICIO - timedelta(days=max(parametros_default['dias_volatilidad'], parametros_default['dias_momento']) + 50)
        trades_data = api_client.obtener_datos_historicos(token, SIMBOLO_A_TESTEAR, historial_extendido_inicio.strftime('%Y-%m-%d'), FECHA_FIN.strftime('%Y-%m-%d'))
        if trades_data:
            datos_completos = indicators.procesar_y_calcular_indicadores(trades_data)
            if datos_completos is not None:
                resultados = ejecutar_backtest_avanzado(parametros_default, datos_completos, verbose=True)
                print("\n--- RESUMEN DEL BACKTEST INDEPENDIENTE ---")
                print(f"Rendimiento Final: {resultados['rendimiento']:.2f}%")
                print(f"Valor Máximo del Portafolio: ${resultados['max_value']:,.2f}")
                print(f"Máximo Drawdown: {resultados['max_drawdown']:.2f}%")