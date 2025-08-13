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

# (La configuración ahora se lee directamente de config.py)

# --- ESTADO DEL BOT Y DEL MERCADO (Variables Globales) ---
open_positions_m1 = [] # Posiciones del Modelo 1 (Volatilidad/Momentum)
open_positions_m2 = [] # Posiciones del Modelo 2 (Order Book)
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

def _handle_trade_closure(trade, precio_actual, symbol, model_positions):
    """Función helper para cerrar un trade y enviar alerta."""
    print(f">>> CERRANDO TRADE {trade['model']} {trade['direction']} {trade['id']} POR {trade['razon_salida']} <<<")
    enviar_alerta(
        f"ALERTA DE CIERRE ({trade['model']}: {trade['razon_salida']})\n"
        f"Símbolo: {symbol}\n"
        f"Dirección: {trade['direction']}\n"
        f"Precio Salida: {precio_actual}"
    )
    model_positions.remove(trade)

def _handle_new_trade(symbol, direccion, razon, estrat, modelo):
    """Función helper para abrir un nuevo trade y enviar alerta."""
    precio_actual = market_data['last'].get('price')
    if not precio_actual:
        print(f"--- [TRADING]: Ignorando señal de {modelo} por falta de precio actual ---")
        return None

    print(f">>> ABRIENDO NUEVO TRADE ({modelo}: {direccion}) <<<")
    nuevo_trade = {
        "id": uuid.uuid4(),
        "model": modelo,
        "direction": direccion,
        "entry_price": precio_actual,
        "entry_time": datetime.now(),
        "estrategia": estrat
    }
    enviar_alerta(
        f"ALERTA DE {direccion} ({modelo})\n"
        f"Símbolo: {symbol}\n"
        f"Precio: {nuevo_trade['entry_price']:.2f}\n"
        f"Estrategia: {razon}"
    )
    return nuevo_trade

def logica_de_trading(symbol, datos_indicadores):
    global open_positions_m1, open_positions_m2, market_data
    
    if datos_indicadores is None or datos_indicadores.empty:
        print("--- [TRADING]: Datos de indicadores insuficientes.")
        return

    ultima_vela = datos_indicadores.iloc[-1]
    precio_actual = market_data['last'].get('price')
    if not precio_actual: return

    with positions_lock:
        # --- 1. LÓGICA DE CIERRE DE POSICIONES ---
        # Modelo 1: Volatilidad/Momentum
        for trade in list(open_positions_m1):
            sl, tp, razon_salida = None, None, None
            es_largo = trade['direction'] == 'LONG'

            if trade['estrategia'] == "TENDENCIA":
                sl = config.ESTRATEGIA_PARAMS['stop_loss_tendencia']
                tp = config.ESTRATEGIA_PARAMS['take_profit_tendencia']
                if es_largo:
                    if precio_actual <= trade['entry_price'] * (1 - sl): razon_salida = "STOP_LOSS"
                    elif precio_actual >= trade['entry_price'] * (1 + tp): razon_salida = "TAKE_PROFIT"
                else: # SHORT
                    if precio_actual >= trade['entry_price'] * (1 + sl): razon_salida = "STOP_LOSS"
                    elif precio_actual <= trade['entry_price'] * (1 - tp): razon_salida = "TAKE_PROFIT"

            elif trade['estrategia'] == "REVERSION":
                sl = config.ESTRATEGIA_PARAMS['stop_loss_reversion']
                tp_price = (ultima_vela['BBU_SHORT'] + ultima_vela['BBL_SHORT']) / 2
                if es_largo:
                    if precio_actual <= trade['entry_price'] * (1 - sl): razon_salida = "STOP_LOSS"
                    elif precio_actual >= tp_price: razon_salida = "TAKE_PROFIT (Banda Media)"
                else: # SHORT
                    if precio_actual >= trade['entry_price'] * (1 + sl): razon_salida = "STOP_LOSS"
                    elif precio_actual <= tp_price: razon_salida = "TAKE_PROFIT (Banda Media)"

            if razon_salida:
                trade['razon_salida'] = razon_salida
                _handle_trade_closure(trade, precio_actual, symbol, open_positions_m1)

        # Modelo 2: Order Book
        for trade in list(open_positions_m2):
            sl, tp = config.MODELO2_STOP_LOSS, config.MODELO2_TAKE_PROFIT
            razon_salida = None
            es_largo = trade['direction'] == 'LONG'
            if es_largo:
                if precio_actual <= trade['entry_price'] * (1 - sl): razon_salida = "STOP_LOSS"
                elif precio_actual >= trade['entry_price'] * (1 + tp): razon_salida = "TAKE_PROFIT"
            else: # SHORT
                if precio_actual >= trade['entry_price'] * (1 + sl): razon_salida = "STOP_LOSS"
                elif precio_actual <= trade['entry_price'] * (1 - tp): razon_salida = "TAKE_PROFIT"

            if razon_salida:
                trade['razon_salida'] = razon_salida
                _handle_trade_closure(trade, precio_actual, symbol, open_positions_m2)

        # --- 2. LÓGICA DE APERTURA DE NUEVAS POSICIONES ---
        num_posiciones_totales = len(open_positions_m1) + len(open_positions_m2)
        if num_posiciones_totales < config.MAX_POSICIONES_ABIERTAS:

            # Lógica de Apertura Modelo 1
            if len(open_positions_m1) == 0:
                momentum_is_bullish = ultima_vela['EMA_10'] > ultima_vela['EMA_30']
                momentum_is_bearish = ultima_vela['EMA_10'] < ultima_vela['EMA_30']
                entrada, razon, estrat, direccion = False, None, None, None

                if pd.notna(ultima_vela['BBU_LONG']):
                    if momentum_is_bullish and precio_actual > ultima_vela['BBU_LONG']:
                        entrada, razon, estrat, direccion = True, 'M1_REVERSAL_SHORT', "REVERSION", "SHORT"
                    elif momentum_is_bearish and precio_actual < ultima_vela['BBL_LONG']:
                        entrada, razon, estrat, direccion = True, 'M1_REVERSAL_LONG', "REVERSION", "LONG"

                if not entrada:
                    if momentum_is_bullish and precio_actual < ultima_vela['BBL_SHORT']:
                        entrada, razon, estrat, direccion = True, 'M1_TREND_LONG', "TENDENCIA", "LONG"
                    elif momentum_is_bearish and precio_actual > ultima_vela['BBU_SHORT']:
                        entrada, razon, estrat, direccion = True, 'M1_TREND_SHORT', "TENDENCIA", "SHORT"

                if entrada and ultima_vela['volume'] > ultima_vela['volume_MA_50'] * config.FACTOR_AUMENTO_VOLUMEN:
                    nuevo_trade = _handle_new_trade(symbol, direccion, razon, estrat, "Modelo 1")
                    if nuevo_trade: open_positions_m1.append(nuevo_trade)

            # Lógica de Apertura Modelo 2
            if config.MODELO2_ACTIVADO and len(open_positions_m2) == 0:
                with market_data_lock:
                    imbalance = calcular_imbalance(market_data['bids'], market_data['offers'])

                entrada, razon, estrat, direccion = False, None, None, None
                if imbalance > config.IMBALANCE_THRESHOLD_LONG:
                    entrada, razon, estrat, direccion = True, "M2_IMBALANCE_LONG", "IMBALANCE", "LONG"
                elif imbalance < config.IMBALANCE_THRESHOLD_SHORT:
                    entrada, razon, estrat, direccion = True, "M2_IMBALANCE_SHORT", "IMBALANCE", "SHORT"

                if entrada:
                    nuevo_trade = _handle_new_trade(symbol, direccion, razon, estrat, "Modelo 2")
                    if nuevo_trade: open_positions_m2.append(nuevo_trade)


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

def run_bot():
    token = api_client.obtener_token()
    if not token: return

    symbol = api_client.encontrar_futuro_dolar_mas_corto(token)
    if not symbol: return

    print(f"\n--- INICIANDO BOT PARA EL SÍMBOLO: {symbol} ---")
    enviar_alerta(f"Bot iniciado para {symbol}")

    ws_url = "wss://api.remarkets.primary.com.ar/"
    ws = websocket.WebSocketApp(ws_url, on_message=on_message, on_error=on_error, on_close=on_close, header={'X-Auth-Token': token})

    def on_open(ws):
        print("--- Conexión WebSocket abierta ---")
        sub_msg = {"type": "smd", "level": 1, "entries": ["BI", "OF", "LA"], "products": [{"symbol": symbol, "marketId": "ROFX"}]}
        ws.send(json.dumps(sub_msg))
        print(f"--- Suscrito a Market Data para {symbol} ---")
    ws.on_open = on_open

    ws_thread = threading.Thread(target=ws.run_forever)
    ws_thread.daemon = True
    ws_thread.start()
    time.sleep(5) # Dar tiempo a que el websocket se conecte y reciba datos iniciales

    # Para el historial, ahora solo necesitamos lo suficiente para los indicadores de corto plazo del bot en vivo
    historial_trades = []
    fecha_inicio = datetime.now() - timedelta(days=5) # 5 días de historial para EMA_30, BB_SHORT, etc.
    initial_trades = api_client.obtener_datos_historicos(token, symbol, fecha_inicio.strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    if initial_trades:
        historial_trades.extend(initial_trades)

    while True:
        now_time = datetime.now().time()
        
        # Lógica de cierre de fin de día
        if now_time >= datetime.strptime(config.HORA_CIERRE_MERCADO, '%H:%M').time():
            with positions_lock:
                if len(open_positions_m1) > 0 or len(open_positions_m2) > 0:
                    print(f">>> CERRANDO TODAS LAS POSICIONES POR FIN DEL DÍA <<<")
                    enviar_alerta(f"CIERRE FIN DE DÍA\nCerrando {len(open_positions_m1) + len(open_positions_m2)} posiciones.")
                    open_positions_m1.clear()
                    open_positions_m2.clear()

        # Obtener nuevos trades para actualizar indicadores
        un_minuto_atras = datetime.now() - timedelta(minutes=1)
        nuevos_trades = api_client.obtener_datos_historicos(token, symbol, un_minuto_atras.strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        if nuevos_trades:
            historial_trades.extend(nuevos_trades)

        # Calcular indicadores con el historial actualizado
        datos_para_logica = indicators.procesar_y_calcular_indicadores(historial_trades)

        num_pos = len(open_positions_m1) + len(open_positions_m2)
        print(f"\n--- [{datetime.now().strftime('%H:%M:%S')}] Ciclo de Decisión. Posiciones Totales: {num_pos} (M1: {len(open_positions_m1)}, M2: {len(open_positions_m2)}) ---")
        logica_de_trading(symbol, datos_para_logica)

        time.sleep(config.INTERVALO_LOGICA_SEGUNDOS)

if __name__ == "__main__":
    run_bot()