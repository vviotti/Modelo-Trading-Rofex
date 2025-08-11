# alerter.py (Versión con Alertas de Escritorio)

import tkinter as tk
from tkinter import messagebox

def enviar_alerta(mensaje):
    """
    Muestra una ventana emergente (pop-up) en el escritorio con el mensaje de alerta.
    
    Args:
        mensaje (str): El texto del mensaje que se mostrará.
    """
    try:
        # Creamos una ventana principal invisible.
        # Es un paso necesario para que la ventana emergente funcione correctamente.
        root = tk.Tk()
        root.withdraw() 

        # Mostramos la ventana emergente con el mensaje.
        # El título de la ventana será "Alerta de Trading".
        messagebox.showinfo("Alerta de Trading", mensaje)

        # Cerramos la ventana invisible una vez que el usuario presiona "OK".
        root.destroy()
        
        print(f"Alerta de escritorio mostrada: '{mensaje}'")
        return True
        
    except Exception as e:
        print(f"Error al mostrar la alerta de escritorio: {e}")
        return False

# Ejemplo de uso (puedes descomentar para probar este archivo por separado)
# if __name__ == '__main__':
#    print("Mostrando una alerta de prueba...")
#    enviar_alerta("¡Prueba de Alerta!\n\nEl sistema de notificación de escritorio funciona.")