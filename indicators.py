# indicators.py (Versión con procesamiento de Volumen)

import pandas as pd
import pandas_ta as ta

def procesar_y_calcular_indicadores(trades_historicos, 
                                    media_rapida=9, media_lenta=21, rsi_periodo=14, 
                                    bb_largo=20, bb_std=2.0, vol_ma_largo=50):
    """
    Toma una lista de trades, los procesa en velas de 5 minutos y calcula los indicadores,
    incluyendo ahora el volumen y su media móvil.
    """
    if not trades_historicos: return None
    df = pd.DataFrame(trades_historicos)
    
    # Convertimos price y size a tipos numéricos, manejando posibles errores
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df['size'] = pd.to_numeric(df['size'], errors='coerce')
    df.dropna(subset=['price', 'size'], inplace=True)
    
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    df = df.sort_index()

    # --- CAMBIO IMPORTANTE: Agregamos el volumen a la agregación ---
    # Usamos .agg() para aplicar diferentes funciones a diferentes columnas
    df_intradiario = df.resample('5min').agg({
        'price': 'last',  # El último precio es el cierre de la vela
        'size': 'sum'     # La suma de los tamaños es el volumen de la vela
    }).ffill()
    
    # Renombramos la columna 'size' a 'volume' para mayor claridad
    df_intradiario.rename(columns={'price': 'close', 'size': 'volume'}, inplace=True)
    
    if len(df_intradiario) < max(media_lenta, vol_ma_largo): return None

    # Calcular Medias Móviles y RSI (sin cambios)
    df_intradiario[f'MA_{media_rapida}'] = df_intradiario['close'].rolling(window=media_rapida).mean()
    df_intradiario[f'MA_{media_lenta}'] = df_intradiario['close'].rolling(window=media_lenta).mean()
    df_intradiario[f'RSI_{rsi_periodo}'] = ta.rsi(close=df_intradiario['close'], length=rsi_periodo)
    
    # Calcular Bandas de Bollinger (sin cambios)
    df_intradiario.ta.bbands(length=bb_largo, std=bb_std, append=True)
    
    # --- NUEVO: CALCULAR MEDIA MÓVIL DE VOLUMEN ---
    df_intradiario[f'volume_MA_{vol_ma_largo}'] = df_intradiario['volume'].rolling(window=vol_ma_largo).mean()

    return df_intradiario.dropna()