# live_bot.py (Versión Final - Gestor de Portafolio Intradiario)

import websocket
import json
import time
import uuid
from datetime import datetime, timedelta
import threading

# Importamos nuestros módulos, incluyendo el de configuración y alertas
import api_client
import indicators
import config
from alerter import enviar_alerta

# --- CONFIGURACIÓN DEL BOT ---
SIMBOLO = "DLR/AGO25"
CUENTA_OPERATIVA = config.API_USERNAME # Lee la cuenta desde el config para centralizar
HORA_CIERRE_MERCADO = "17:55" # Hora para empezar a cerrar todas las posiciones
MAX_POSICIONES_ABIERTAS = 3 # Límite de operaciones simultáneas
INTERVALO_LOGICA_SEGUNDOS = 300 # Ejecutar la lógica de trading cada 5 minutos

# --- ESTADO DEL BOT Y DEL MERCADO (Variables Globales) ---
# La nueva "libreta de operaciones"
open_positions = []
positions_lock = threading.Lock() # Lock para manejar acceso seguro a la lista de posiciones

market_data = {"bids": [], "offers": [], "last": {}}
market_data_lock = threading.Lock() # Lock para manejar acceso seguro a los datos de mercado

# --- FUNCIONES DE MICROESTRUCTURA ---
def calcular_imbalance(bids, offers, depth=5):
    """Calcula el ratio de volumen entre las puntas de compra y venta."""
    if not bids or not offers:
        return 1.0
    
    vol_compra = sum(bid.get('size', 0) for bid in bids[:depth])
    vol_venta = sum(offer.get('size', 0) for offer in offers[:depth])
    
    if vol_venta == 0:
        return float('inf')
    
    return vol_compra / vol_venta

def analizar_agresion(last_price, best_bid, best_ask):
    """Determina si la última operación fue una compra o venta agresiva."""
    if not last_price or not best_bid or not best_ask:
        return "NEUTRAL"
    if last_price >= best_ask:
        return "COMPRA_AGRESIVA"
    if last_price <= best_bid:
        return "VENTA_AGRESIVA"
    return "NEUTRAL"

# --- LÓGICA PRINCIPAL DE TRADING (Se ejecuta en un hilo separado) ---
def logica_de_trading():
    global market_data, open_positions
    print(f"--- [TRADING]: Ciclo de decisión. Posiciones abiertas: {len(open_positions)} ---")

    # Obtenemos datos y calculamos indicadores
    token = api_client.obtener_token()
    if not token: return
    fecha_fin = datetime.now()
    fecha_inicio = fecha_fin - timedelta(days=3)
    trades = api_client.obtener_datos_historicos(token, SIMBOLO, fecha_inicio.strftime('%Y-%m-%d'), fecha_fin.strftime('%Y-%m-%d'))
    if not trades: return
    datos_indicadores = indicators.procesar_y_calcular_indicadores(trades)
    if datos_indicadores is None: return
    ultima_vela = datos_indicadores.iloc[-1]
    
    # --- 1. LÓGICA DE CIERRE DE POSICIONES ---
    with positions_lock:
        for trade in list(open_positions): # Iteramos sobre una copia
            precio_actual = market_data['last'].get('price')
            if not precio_actual: continue # Si no hay precio, no podemos hacer nada

            # Lógica de cierre para posiciones de COMPRA (LONG)
            if trade['direction'] == 'LONG':
                razon_salida = None
                # Verificación de Stop-Loss
                if precio_actual <= trade['entry_price'] * (1 - config.ESTRATEGIA_PARAMS['stop_loss_tendencia']):
                    razon_salida = "STOP-LOSS"
                # Verificación de Take-Profit
                elif precio_actual >= trade['entry_price'] * (1 + config.ESTRATEGIA_PARAMS['take_profit_tendencia']):
                    razon_salida = "TAKE-PROFIT"

                if razon_salida:
                    print(f">>> CERRANDO TRADE {trade['id']} POR {razon_salida} <<<")
                    enviar_alerta(f"CIERRE {razon_salida}\nSímbolo: {SIMBOLO}\nPrecio Salida: {precio_actual}")
                    open_positions.remove(trade)

    # --- 2. LÓGICA DE APERTURA DE NUEVAS POSICIONES ---
    with positions_lock:
        if len(open_positions) < MAX_POSICIONES_ABIERTAS:
            # Aquí iría la lógica completa de la matriz 2x2 para decidir si hay una señal
            # Ejemplo simplificado: señal de compra por cruce de MA en régimen de TENDENCIA
            if ultima_vela['MA_9'] > ultima_vela['MA_21'] and ultima_vela['MA_9'] > ultima_vela['MA_21']:
                print("--- [TRADING]: Señal de COMPRA detectada por indicadores ---")
                
                with market_data_lock:
                    imbalance = calcular_imbalance(market_data['bids'], market_data['offers'])
                
                if imbalance > 1.2:
                    print(f">>> ABRIENDO NUEVO TRADE (COMPRA) <<<")
                    nuevo_trade = {
                        "id": uuid.uuid4(),
                        "direction": "LONG",
                        "entry_price": market_data['last'].get('price', ultima_vela['close']),
                        "size": 1,
                        "entry_time": datetime.now(),
                        "strategy": "TENDENCIA"
                    }
                    open_positions.append(nuevo_trade)
                    enviar_alerta(f"ALERTA DE COMPRA\nSímbolo: {SIMBOLO}\nPrecio: {nuevo_trade['entry_price']:.2f}\nEstrategia: {nuevo_trade['strategy']}")
                else:
                    print("--- [TRADING]: Señal de compra IGNORADA por bajo imbalance en el libro ---")

# --- MANEJO DE LA CONEXIÓN WEBSOCKET ---
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

def on_open(ws):
    print("--- Conexión WebSocket abierta ---")
    subscription_msg = { "type": "smd", "level": 1, "entries": ["BI", "OF", "LA"], "products": [{"symbol": SIMBOLO, "marketId": "ROFX"}], "depth": 5 }
    ws.send(json.dumps(subscription_msg))
    print(f"--- Suscrito a Market Data para {SIMBOLO} ---")

# --- FUNCIÓN PRINCIPAL DEL BOT ---
def run_bot():
    print("--- [BOT]: Iniciando Bot de Trading en Tiempo Real ---")
    # (En una versión completa, aquí se determinaría el régimen diario)
    
    token = api_client.obtener_token()
    if not token:
        print("No se pudo obtener el token. Abortando.")
        return

    # Iniciar la hebra de WebSocket para recibir datos de mercado
    ws_url = "wss://api.remarkets.primary.com.ar/ws/marketdata"
    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close, header={'X-Auth-Token': token})
    ws_thread = threading.Thread(target=ws.run_forever)
    ws_thread.daemon = True
    ws_thread.start()
    
    time.sleep(5) # Dar tiempo a que la conexión se establezca

    # Bucle principal de decisión
    while True:
        now = datetime.now().strftime("%H:%M")
        with positions_lock:
            if len(open_positions) > 0 and now > HORA_CIERRE_MERCADO:
                print(f">>> CERRANDO TODAS LAS {len(open_positions)} POSICIONES POR FIN DEL DÍA <<<")
                enviar_alerta(f"CIERRE FIN DE DÍA\nCerrando {len(open_positions)} posiciones abiertas.")
                open_positions.clear()

        # Ejecutar la lógica de decisión según el intervalo
        logica_de_trading()
        time.sleep(INTERVALO_LOGICA_SEGUNDOS)

if __name__ == "__main__":
    run_bot()