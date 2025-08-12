# config.py

# --- API CREDENTIALS ---
API_USERNAME = "vviotti21748"
API_PASSWORD = "nszowG6$"
BASE_URL = "https://api.remarkets.primary.com.ar"

# --- TELEGRAM (OPCIONAL, SI SE USA) ---
TELEGRAM_BOT_TOKEN = "8439141528:AAErZluaO4SaNk4eRk8z_HyVp-nXp_Qb3dA"
TELEGRAM_CHAT_ID = "1134159054"

# --- PARÁMETROS DE BACKTESTING Y SIMULACIÓN ---
CAPITAL_INICIAL = 1000000
COMISION_POR_TRADE = 0.001  # 0.1% por operación
SPREAD_SIMULADO_PCT = 0.001 # 0.1% de deslizamiento
DIAS_BACKTEST = 20 # Días de trading para el backtest

# --- PARÁMETROS DE LA ESTRATEGIA DE TRADING ---
# Estos son los parámetros que el optimizador ajustará
ESTRATEGIA_PARAMS = {
    "dias_volatilidad": 10,
    "umbral_vol_alto": 0.009,
    "umbral_vol_bajo": 0.006,
    "dias_momento": 3,
    "stop_loss_tendencia": 0.02,
    "take_profit_tendencia": 0.04,
    "stop_loss_reversion": 0.015,
}

# --- CONFIGURACIÓN DEL OPTIMIZADOR (NUEVO PARA RANDOM SEARCH) ---
OPTIMIZER_CONFIG = {
    # Cantidad de combinaciones aleatorias a probar
    'n_combinations': 100,

    # Rangos de búsqueda para cada parámetro.
    # 'type' puede ser 'int' para enteros o 'float' para decimales.
    'param_ranges': {
        'dias_volatilidad':   {'min': 5, 'max': 20, 'type': 'int'},
        'umbral_vol_alto':    {'min': 0.007, 'max': 0.015, 'type': 'float'},
        'umbral_vol_bajo':    {'min': 0.003, 'max': 0.006, 'type': 'float'},
        'dias_momento':       {'min': 2, 'max': 10, 'type': 'int'},
        'stop_loss_tendencia':{'min': 0.01, 'max': 0.03, 'type': 'float'},
        'take_profit_tendencia': {'min': 0.02, 'max': 0.06, 'type': 'float'},
        'stop_loss_reversion':{'min': 0.01, 'max': 0.02, 'type': 'float'},
    }
}


# --- PARÁMETROS DEL BOT EN VIVO ---
HORA_CIERRE_MERCADO = "14:55"
MAX_POSICIONES_ABIERTAS = 1
FACTOR_AUMENTO_VOLUMEN = 1.5
INTERVALO_LOGICA_SEGUNDOS = 60
IMBALANCE_THRESHOLD_LONG = 1.1  # Umbral de desequilibrio para compras
IMBALANCE_THRESHOLD_SHORT = 0.9 # Umbral de desequilibrio para ventas