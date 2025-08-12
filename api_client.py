# api_client.py

import requests
import config  # Importamos nuestro archivo de configuración
from datetime import datetime, date
from dateutil.relativedelta import relativedelta # Para cálculos de fechas

def obtener_token():
    """
    Se autentica en la API de Remarkets y obtiene un token de sesión.
    """
    print("Obteniendo token de autenticación...")
    url = f"{config.BASE_URL}/auth/getToken"
    headers = {
        "X-Username": config.API_USERNAME,
        "X-Password": config.API_PASSWORD
    }
    
    try:
        response = requests.post(url, headers=headers)
        
        # request.raise_for_status() lanzará una excepción si el status es 4xx o 5xx
        response.raise_for_status()
        
        token = response.headers.get("X-Auth-Token")
        if token:
            print("Token obtenido exitosamente.")
            return token
        else:
            print("Error: No se encontró el X-Auth-Token en la respuesta.")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión al autenticar: {e}")
        return None
    
# CÓDIGO CORREGIDO PARA api_client.py

def encontrar_futuro_dolar_mas_corto(auth_token):
    """
    Encuentra el contrato de futuro de dólar (DLR) con el vencimiento más cercano.
    """
    print("Buscando el contrato de futuro de dólar más corto...")
    url = f"{config.BASE_URL}/rest/instruments/byCFICode"
    headers = {"X-Auth-Token": auth_token}
    params = {"CFICode": "FXXXSX"}

    meses = {'ENE': 1, 'FEB': 2, 'MAR': 3, 'ABR': 4, 'MAY': 5, 'JUN': 6, 
             'JUL': 7, 'AGO': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DIC': 12}

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        instrumentos = response.json().get('instruments', [])
        
        # --- INICIO DE LA CORRECCIÓN ---
        # Filtramos solo los futuros de dólar simples (ej. DLR/OCT25)
        futuros_dolar = [
            inst for inst in instrumentos 
            # CAMBIO AQUÍ: accedemos a 'symbol' directamente
            if inst['symbol'].startswith('DLR/') and '/' not in inst['symbol'][4:]
        ]
        # --- FIN DE LA CORRECCIÓN ---

        futuros_validos = []
        hoy = date.today()

        for fut in futuros_dolar:
            # --- INICIO DE LA CORRECCIÓN ---
            # CAMBIO AQUÍ: accedemos a 'symbol' directamente
            simbolo = fut['symbol']
            # --- FIN DE LA CORRECCIÓN ---
            try:
                parte_fecha = simbolo.split('/')[1]
                mes_str = parte_fecha[:3]
                ano_str = parte_fecha[3:]
                
                mes = meses[mes_str.upper()]
                ano = 2000 + int(ano_str)
                
                vencimiento = date(ano, mes, 1) + relativedelta(months=1) - relativedelta(days=1)
                
                if vencimiento > hoy:
                    futuros_validos.append((vencimiento, simbolo))

            except (IndexError, ValueError, KeyError):
                continue
        
        if not futuros_validos:
            print("No se encontraron futuros de dólar válidos.")
            return None
        
        vencimiento_mas_corto, simbolo_mas_corto = min(futuros_validos)
        print(f"Contrato más corto encontrado: {simbolo_mas_corto} (Vence: {vencimiento_mas_corto.strftime('%Y-%m-%d')})")
        return simbolo_mas_corto

    except requests.exceptions.RequestException as e:
        print(f"Error de conexión al buscar instrumentos: {e}")
        return None
    
def obtener_datos_historicos(auth_token, symbol, fecha_inicio, fecha_fin):
    """
    Obtiene los trades históricos para un símbolo en un rango de fechas.
    """
    print(f"Obteniendo datos históricos para {symbol}...")
    url = f"{config.BASE_URL}/rest/data/getTrades"
    headers = {"X-Auth-Token": auth_token}
    params = {
        "marketId": "ROFX",
        "symbol": symbol,
        "dateFrom": fecha_inicio,
        "dateTo": fecha_fin
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        trades = response.json().get('trades', [])
        print(f"Se encontraron {len(trades)} trades históricos.")
        return trades
        
    except requests.exceptions.RequestException as e:
        print(f"Error de conexión al obtener datos históricos: {e}")
        return []