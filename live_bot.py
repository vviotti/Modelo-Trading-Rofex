# live_bot.py (Versión Final v2 - Sincronizado con Backtester Avanzado)

import websocket
import json
import time
import uuid
from datetime import datetime, timedelta
import threading
import pandas as pd

# Importamos nuestros módulos, incluyendo el de configuración y alertas
import api_client
import indicators
import config
from alerter import enviar_alerta

# --- CONFIGURACIÓN DEL BOT ---
CUENTA_OPERATIVA = config.API_USERNAME
HORA_CIERRE_MERCADO = "14:55"
MAX_POSICIONES_ABIERTAS = 3
INTERVALO_LOGICA_SEGUNDOS = 300 # Ejecutar la lógica de trading cada 5 minutos
FACTOR_AUMENTO_VOLUMEN = 1.5

# --- ESTADO DEL BOT Y DEL MERCADO (Variables Globales) ---
open_positions = []
positions_lock = threading.Lock()

market_data = {"bids": [], "offers": [], "last": {}}
market_data_lock = threading.Lock()

# Variable para guardar el régimen del día y evitar recalcularlo constantemente
regimen_diario = {"volatilidad": "BAJA", "momento": "NEUTRAL", "fecha": None}
regimen_lock = threading.Lock()

# --- FUNCIONES DE MICROESTRUCTURA (sin cambios) ---
def calcular_imbalance(bids, offers, depth=5):
    if not bids or not offers: return 1.0
    vol_compra = sum(bid.get('size', 0) for bid in bids[:depth])
    vol_venta = sum(offer.get('size', 0) for offer in offers[:depth])
    if vol_venta == 0: return float('inf')
    return vol_compra / vol_venta

def analizar_agresion(last_price, best_bid, best_ask):
    if not last_price or not best_bid or not best_ask: return "NEUTRAL"
    if last_price >= best_ask: return "COMPRA_AGRESIVA"
    if last_price <= best_bid: return "VENTA_AGRESIVA"
    return "NEUTRAL"

# --- LÓGICA PRINCIPAL DE TRADING ---
def logica_de_trading(symbol):
    global market_data, open_positions, regimen_diario
    print(f"--- [TRADING]: Ciclo de decisión. Posiciones abiertas: {len(open_positions)} ---")

    token = api_client.obtener_token()
    if not token: return
    
    fecha_fin = datetime.now()
    fecha_inicio = fecha_fin - timedelta(days=5)
    trades = api_client.obtener_datos_historicos(token, symbol, fecha_inicio.strftime('%Y-%m-%d'), fecha_fin.strftime('%Y-%m-%d'))
    if not trades: return
    
    datos_indicadores = indicators.procesar_y_calcular_indicadores(trades)
    if datos_indicadores is None: return
    ultima_vela = datos_indicadores.iloc[-1]
    
    # --- 1. LÓGICA DE CIERRE DE POSICIONES ---
    with positions_lock:
        for trade in list(open_positions):
            precio_actual = market_data['last'].get('price')
            if not precio_actual: continue
            
            razon_salida = None
            es_largo = trade['direction'] == 'LONG'

            if trade['estrategia'] == "TENDENCIA":
                sl = config.ESTRATEGIA_PARAMS['stop_loss_tendencia']
                tp = config.ESTRATEGIA_PARAMS['take_profit_tendencia']
                if es_largo:
                    if precio_actual <= trade['entry_price'] * (1 - sl): razon_salida = "STOP_LOSS"
                    elif precio_actual >= trade['entry_price'] * (1 + tp): razon_salida = "TAKE_PROFIT"
                else: # Corto
                    if precio_actual >= trade['entry_price'] * (1 + sl): razon_salida = "STOP_LOSS"
                    elif precio_actual <= trade['entry_price'] * (1 - tp): razon_salida = "TAKE_PROFIT"

            elif trade['estrategia'] == "REVERSION":
                sl = config.ESTRATEGIA_PARAMS['stop_loss_reversion']
                if es_largo:
                    if precio_actual <= trade['entry_price'] * (1 - sl): razon_salida = "STOP_LOSS"
                    elif precio_actual >= ultima_vela['BBM_20_2.0']: razon_salida = "TAKE_PROFIT (Banda Media)"
                else: # Corto
                    if precio_actual >= trade['entry_price'] * (1 + sl): razon_salida = "STOP_LOSS"
                    elif precio_actual <= ultima_vela['BBM_20_2.0']: razon_salida = "TAKE_PROFIT (Banda Media)"

            if razon_salida:
                print(f">>> CERRANDO TRADE {trade['direction']} {trade['id']} POR {razon_salida} <<<")
                enviar_alerta(f"ALERTA DE CIERRE ({razon_salida})\nSímbolo: {symbol}\nDirección: {trade['direction']}\nPrecio Salida: {precio_actual}")
                open_positions.remove(trade)

    # --- 2. LÓGICA DE APERTURA DE NUEVAS POSICIONES ---
    with positions_lock:
        if len(open_positions) < MAX_POSICIONES_ABIERTAS:
            with regimen_lock:
                regimen_vol = regimen_diario["volatilidad"]
                regimen_momento = regimen_diario["momento"]

            entrada, razon_entrada, estrat, direccion = False, None, None, None
            fila_anterior = datos_indicadores.iloc[-2]

            # Estrategias LONG
            if regimen_vol == "BAJA" and regimen_momento == "POSITIVO":
                if fila_anterior['MA_9'] < fila_anterior['MA_21'] and ultima_vela['MA_9'] > ultima_vela['MA_21'] and ultima_vela['RSI_14'] < 70:
                    entrada, razon_entrada, estrat, direccion = True, 'TEND_ALCISTA', "TENDENCIA", "LONG"
            elif regimen_vol == "ALTA" and regimen_momento == "POSITIVO":
                if ultima_vela['close'] < ultima_vela['BBL_20_2.0']:
                    entrada, razon_entrada, estrat, direccion = True, 'REV_ALCISTA', "REVERSION", "LONG"

            # Estrategias SHORT
            elif regimen_vol == "BAJA" and regimen_momento == "NEGATIVO":
                if fila_anterior['MA_9'] > fila_anterior['MA_21'] and ultima_vela['MA_9'] < ultima_vela['MA_21'] and ultima_vela['RSI_14'] > 30:
                    entrada, razon_entrada, estrat, direccion = True, 'TEND_BAJISTA', "TENDENCIA", "SHORT"
            elif regimen_vol == "ALTA" and regimen_momento == "NEGATIVO":
                if ultima_vela['close'] > ultima_vela['BBU_20_2.0']:
                    entrada, razon_entrada, estrat, direccion = True, 'REV_BAJISTA', "REVERSION", "SHORT"

            if entrada:
                print(f"--- [TRADING]: Señal de {direccion} ({razon_entrada}) detectada por indicadores ---")
                if ultima_vela['volume'] > ultima_vela['volume_MA_50'] * FACTOR_AUMENTO_VOLUMEN:
                    with market_data_lock:
                        imbalance = calcular_imbalance(market_data['bids'], market_data['offers'])
                        imbalance_check = (imbalance > 1.2) if direccion == "LONG" else (imbalance < 0.8) # Chequeo de imbalance para long y short
                    
                    if imbalance_check:
                        print(f">>> ABRIENDO NUEVO TRADE ({direccion}) <<<")
                        nuevo_trade = { "id": uuid.uuid4(), "direction": direccion, "entry_price": market_data['last'].get('price', ultima_vela['close']), "size": 1, "entry_time": datetime.now(), "strategy": estrat }
                        open_positions.append(nuevo_trade)
                        enviar_alerta(f"ALERTA DE {direccion}\nSímbolo: {symbol}\nPrecio: {nuevo_trade['entry_price']:.2f}\nEstrategia: {razon_entrada}")
                    else:
                        print(f"--- [TRADING]: Señal IGNORADA por bajo imbalance ({imbalance:.2f}) en el libro ---")
                else:
                    print("--- [TRADING]: Señal IGNORADA por bajo volumen ---")

# --- MANEJO DE WEBSOCKET Y BUCLE PRINCIPAL ---
def on_message(ws, message):
    global market_data
    data = json.loads(message)
    if data.get('type') == 'Md':
        with market_data_lock:
            md_update = data.get('marketData', {})
            if 'bids' in md_update: market_data['bids'] = md_update['bids']
            if 'offers' in md_update: market_data['offers'] = md_update['offers']
            if 'LA' in md_update: market_data['last'] = md_update['LA']

def on_error(ws, error): print(f"Error de WebSocket: {error}")
def on_close(ws, close_status_code, close_msg): print("--- Conexión WebSocket cerrada ---")

def determinar_regimen_diario(token, symbol):
    global regimen_diario
    
    hoy = datetime.now().date()
    with regimen_lock:
        if regimen_diario.get("fecha") == hoy:
            return # Ya lo calculamos hoy

    print("--- [RÉGIMEN]: Calculando estrategia para el día de hoy... ---")
    parametros = config.ESTRATEGIA_PARAMS
    dia_anterior = hoy - timedelta(days=1)

    # El historial se busca hasta el día anterior
    fecha_inicio_hist = dia_anterior - timedelta(days=max(parametros['dias_volatilidad'], parametros['dias_momento']) + 50)
    trades_data = api_client.obtener_datos_historicos(token, symbol, fecha_inicio_hist.strftime('%Y-%m-%d'), dia_anterior.strftime('%Y-%m-%d'))
    if not trades_data:
        print("--- [RÉGIMEN]: No se obtuvieron datos históricos para calcular el régimen.")
        return

    datos_completos = indicators.procesar_y_calcular_indicadores(trades_data)
    if datos_completos is None:
        print("--- [RÉGIMEN]: No se pudieron procesar los indicadores para el régimen.")
        return

    # Lógica de Volatilidad (calculada con datos hasta ayer)
    fecha_inicio_vol = dia_anterior - timedelta(days=parametros['dias_volatilidad'])
    datos_para_volatilidad = datos_completos.loc[fecha_inicio_vol.strftime('%Y-%m-%d'):dia_anterior.strftime('%Y-%m-%d')]
    
    nuevo_regimen_vol = "BAJA" # Default
    if not datos_para_volatilidad.empty:
        rendimientos_diarios_vol = datos_para_volatilidad['close'].pct_change().resample('D').sum()
        volatilidad_reciente = rendimientos_diarios_vol.std()
        if volatilidad_reciente > parametros['umbral_vol_alto']: nuevo_regimen_vol = "ALTA"
        elif volatilidad_reciente < parametros['umbral_vol_bajo']: nuevo_regimen_vol = "BAJA"
    
    # Lógica de Momento (calculada con datos hasta ayer)
    fecha_inicio_mom = dia_anterior - timedelta(days=parametros['dias_momento'])
    datos_para_momento = datos_completos.loc[fecha_inicio_mom.strftime('%Y-%m-%d'):dia_anterior.strftime('%Y-%m-%d')]['close'].resample('D').last()
    
    nuevo_regimen_momento = "NEUTRAL"
    if len(datos_para_momento) >= parametros['dias_momento']:
        ma_momento = datos_para_momento.rolling(window=parametros['dias_momento']).mean()
        if not ma_momento.empty and not pd.isna(ma_momento.iloc[-1]) and not pd.isna(datos_para_momento.iloc[-1]):
            if datos_para_momento.iloc[-1] > ma_momento.iloc[-1]:
                nuevo_regimen_momento = "POSITIVO"
            else:
                nuevo_regimen_momento = "NEGATIVO"

    with regimen_lock:
        regimen_diario = {"volatilidad": nuevo_regimen_vol, "momento": nuevo_regimen_momento, "fecha": hoy}
    
    print(f"--- [RÉGIMEN]: Volatilidad: {nuevo_regimen_vol} | Momento: {nuevo_regimen_momento} ---")

def run_bot():
    token = api_client.obtener_token()
    if not token:
        print("No se pudo obtener el token. Abortando.")
        return

    symbol = api_client.encontrar_futuro_dolar_mas_corto(token)
    if not symbol:
        print("No se pudo encontrar el símbolo del futuro para operar. Abortando.")
        return

    print(f"\n--- INICIANDO BOT PARA EL SÍMBOLO: {symbol} ---")

    def on_open(ws):
        print("--- Conexión WebSocket abierta ---")
        subscription_msg = { "type": "smd", "level": 1, "entries": ["BI", "OF", "LA"], "products": [{"symbol": symbol, "marketId": "ROFX"}], "depth": 5 }
        ws.send(json.dumps(subscription_msg))
        print(f"--- Suscrito a Market Data para {symbol} ---")

    ws_url = "wss://api.remarkets.primary.com.ar/ws/marketdata"
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close, header={'X-Auth-Token': token})
    ws_thread = threading.Thread(target=ws.run_forever)
    ws_thread.daemon = True
    ws_thread.start()
    
    time.sleep(5)

    while True:
        determinar_regimen_diario(token, symbol) # Se ejecuta una vez al día o al inicio
        
        now_time = datetime.now().strftime("%H:%M")
        with positions_lock:
            if len(open_positions) > 0 and now_time > HORA_CIERRE_MERCADO:
                print(f">>> CERRANDO TODAS LAS {len(open_positions)} POSICIONES POR FIN DEL DÍA <<<")
                enviar_alerta(f"CIERRE FIN DE DÍA\nCerrando {len(open_positions)} posiciones.")
                open_positions.clear()

        logica_de_trading(symbol)
        time.sleep(INTERVALO_LOGICA_SEGUNDOS)

if __name__ == "__main__":
    run_bot()