# main.py

import time
from datetime import datetime, timedelta

# Importamos las funciones de nuestros otros módulos
import api_client
import indicators
import alerter

# --- CONFIGURACIÓN DEL CICLO ---
# Intervalo de espera entre cada verificación (en segundos)
# 900 segundos = 15 minutos
INTERVALO_VERIFICACION_SEGUNDOS = 30 
DIAS_HISTORICOS_PARA_CALCULO = 3 # Usaremos 60 días de datos para los indicadores

# --- VARIABLES DE ESTADO ---
# Esta variable es CLAVE. Nos ayuda a recordar el estado anterior de las medias móviles
# para detectar solo el momento del CRUCE, y no enviar alertas constantemente.
# Puede ser "ALCISTA", "BAJISTA" o "INICIAL".
estado_previo_ma = "INICIAL"

def verificar_y_alertar(datos_indicadores, estado_previo):
    """
    Verifica los datos de los indicadores y envía una alerta si se cumple una condición de cruce.
    
    Returns:
        str: El nuevo estado de las medias móviles ("ALCISTA" o "BAJISTA").
    """
    global estado_previo_ma # Usamos la variable global para modificarla

    # Extraemos los valores del diccionario para mayor claridad
    ma_rapida = datos_indicadores['media_rapida']
    ma_lenta = datos_indicadores['media_lenta']
    rsi = datos_indicadores['rsi']
    ultimo_precio = datos_indicadores['ultimo_precio']

    # Determinamos el estado actual
    estado_actual_ma = "ALCISTA" if ma_rapida > ma_lenta else "BAJISTA"
    
    mensaje_alerta = ""

    # --- LÓGICA DE SEÑALES ---
    # 1. Señal de COMPRA: Si el estado previo era BAJISTA y el actual es ALCISTA.
    if estado_actual_ma == "ALCISTA" and estado_previo == "BAJISTA":
        print("¡CRUCE ALCISTA DETECTADO!")
        # Filtro de confirmación con RSI: no compramos si está en sobrecompra extrema.
        if rsi < 70:
            mensaje_alerta = (
                f"🚀 *Señal de Compra (Cruce Alcista)*\n\n"
                f"El cruce de medias móviles sugiere una posible tendencia alcista.\n\n"
                f"▪️ *Precio Actual:* ${ultimo_precio:,.2f}\n"
                f"▪️ *RSI:* {rsi:,.2f}\n"
                f"▪️ *MA Rápida:* {ma_rapida:,.2f}\n"
                f"▪️ *MA Lenta:* {ma_lenta:,.2f}"
            )
        else:
            print("Cruce alcista ignorado por RSI en sobrecompra (> 70).")

    # 2. Señal de VENTA: Si el estado previo era ALCISTA y el actual es BAJISTA.
    elif estado_actual_ma == "BAJISTA" and estado_previo == "ALCISTA":
        print("¡CRUCE BAJISTA DETECTADO!")
        # Filtro de confirmación con RSI: no vendemos si está en sobreventa extrema.
        if rsi > 30:
            mensaje_alerta = (
                f"📉 *Señal de Venta (Cruce Bajista)*\n\n"
                f"El cruce de medias móviles sugiere una posible tendencia bajista.\n\n"
                f"▪️ *Precio Actual:* ${ultimo_precio:,.2f}\n"
                f"▪️ *RSI:* {rsi:,.2f}\n"
                f"▪️ *MA Rápida:* {ma_rapida:,.2f}\n"
                f"▪️ *MA Lenta:* {ma_lenta:,.2f}"
            )
        else:
            print("Cruce bajista ignorado por RSI en sobreventa (< 30).")

    # Si generamos un mensaje de alerta, lo enviamos
    if mensaje_alerta:
        alerter.enviar_alerta(mensaje_alerta)
    
    # Actualizamos el estado para la próxima iteración
    estado_previo_ma = estado_actual_ma

def main():
    """Función principal que orquesta todo el proceso."""
    global estado_previo_ma # Declaramos que usaremos la variable global

    print("--- Iniciando Modelo de Alertas para Futuro de Dólar ---")
    
    # 1. Obtenemos el token de autenticación
    token = api_client.obtener_token()
    if not token:
        print("No se pudo obtener el token. Abortando ejecución.")
        return # Termina el programa si no hay token

    # --- INICIA EL CICLO PRINCIPAL ---
    while True:
        try:
            # 2. Encontramos el contrato de futuro de dólar más corto
            simbolo_activo = api_client.encontrar_futuro_dolar_mas_corto(token)
            if not simbolo_activo:
                print(f"No se pudo encontrar un símbolo activo. Reintentando en {INTERVALO_VERIFICACION_SEGUNDOS} segundos.")
                time.sleep(INTERVALO_VERIFICACION_SEGUNDOS)
                continue

            # 3. Obtenemos los datos históricos
            fecha_fin = datetime.now()
            fecha_inicio = fecha_fin - timedelta(days=DIAS_HISTORICOS_PARA_CALCULO)
            
            trades = api_client.obtener_datos_historicos(
                token, 
                simbolo_activo, 
                fecha_inicio.strftime('%Y-%m-%d'), 
                fecha_fin.strftime('%Y-%m-%d')
            )

            # 4. Calculamos los indicadores
            if trades:
                datos_indicadores = indicators.procesar_y_calcular_indicadores(trades)
                
                # 5. Verificamos si hay señales y enviamos alertas
                if datos_indicadores:
                    print(f"Estado previo MA: {estado_previo_ma} | Datos: {datos_indicadores}")
                    verificar_y_alertar(datos_indicadores, estado_previo_ma)
            
            # 6. Esperamos para la próxima verificación
            print(f"\nCiclo completado. Próxima verificación en {INTERVALO_VERIFICACION_SEGUNDOS :.0f} segundos...")
            time.sleep(INTERVALO_VERIFICACION_SEGUNDOS)

        except Exception as e:
            print(f"Ocurrió un error inesperado en el ciclo principal: {e}")
            print("Esperando 60 segundos antes de reintentar...")
            time.sleep(60)

if __name__ == "__main__":
    main()