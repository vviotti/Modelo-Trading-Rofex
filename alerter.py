# alerter.py (Refactorizado con Notificaciones Locales y Remotas)

import requests
import threading
from plyer import notification
import config

def enviar_alerta(mensaje):
    """
    Envía una alerta a través de múltiples canales:
    1. Notificación de escritorio (no bloqueante).
    2. Mensaje de Telegram (si está configurado).
    """
    print(f"--- ALERTA GENERADA ---\n{mensaje}\n-----------------------")

    # --- 1. Notificación de Escritorio (Visual) ---
    try:
        title = mensaje.split('\\n')[0]  # Usa la primera línea como título
        notification.notify(
            title=title,
            message=mensaje,
            app_name='Trading Bot',
            timeout=15  # La notificación desaparecerá después de 15 segundos
        )
    except Exception as e:
        print(f"--- [Alerta Visual] Error al mostrar notificación de escritorio: {e} ---")
        print("--- [Alerta Visual] >> Asegúrate de haber instalado los requerimientos para 'plyer' en tu sistema (ej. `sudo apt-get install libnotify-bin` en Debian/Ubuntu) << ---")

    # --- 3. Notificación de Telegram (Remota) ---
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': config.TELEGRAM_CHAT_ID,
                'text': mensaje,
                'parse_mode': 'Markdown'
            }
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code != 200:
                print(f"--- [Alerta Telegram] Error al enviar mensaje: {response.text} ---")
        except Exception as e:
            print(f"--- [Alerta Telegram] Excepción al enviar mensaje: {e} ---")

    return True

# Ejemplo de uso (puedes descomentar para probar este archivo por separado)
# if __name__ == '__main__':
#    print("Mostrando una alerta de prueba...")
#    enviar_alerta("¡Prueba de Alerta!\n\nEl sistema de notificación funciona.")
#    # Esperar a que el hilo del sonido termine si quieres oírlo antes de que el script principal termine
#    import time
#    time.sleep(3)