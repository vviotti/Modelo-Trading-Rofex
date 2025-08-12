# indicators.py (Versión con procesamiento de Volumen)

import pandas as pd
import pandas_ta as ta

def procesar_y_calcular_indicadores(trades_historicos,
                                    media_rapida=9, media_lenta=21, rsi_periodo=14,
                                    bb_largo=20, bb_std=2.0, vol_ma_largo=50):
    """
    Toma una lista de trades, los procesa en velas de 1 minuto con OHLCV y calcula
    los indicadores técnicos necesarios para la estrategia.
    """
    if not trades_historicos:
        return None
    df = pd.DataFrame(trades_historicos)

    # Convertir a tipos numéricos, manejando errores
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df['size'] = pd.to_numeric(df['size'], errors='coerce')
    df.dropna(subset=['price', 'size'], inplace=True)

    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').sort_index()

    # --- CAMBIO IMPORTANTE: Resample a 1 minuto y calcular OHLCV ---
    agg_dict = {
        'price': 'ohlc',
        'size': 'sum'
    }
    df_intradiario = df.resample('1min').agg(agg_dict)
    df_intradiario.columns = ['open', 'high', 'low', 'close', 'volume'] # Aplanar MultiIndex
    
    # Rellenar fines de semana o huecos sin trades con el último valor conocido
    df_intradiario.ffill(inplace=True)

    if len(df_intradiario) < max(media_lenta, vol_ma_largo):
        return None

    # --- CÁLCULO DE INDICADORES USANDO LA COLUMNA 'close' ---
    # Medias Móviles
    df_intradiario[f'MA_{media_rapida}'] = df_intradiario['close'].rolling(window=media_rapida).mean()
    df_intradiario[f'MA_{media_lenta}'] = df_intradiario['close'].rolling(window=media_lenta).mean()

    # RSI
    df_intradiario[f'RSI_{rsi_periodo}'] = ta.rsi(close=df_intradiario['close'], length=rsi_periodo)

    # Bandas de Bollinger (usando pandas-ta para conveniencia)
    # pandas-ta automáticamente usa la columna 'close'
    df_intradiario.ta.bbands(length=bb_largo, std=bb_std, append=True)

    # Media Móvil de Volumen
    df_intradiario[f'volume_MA_{vol_ma_largo}'] = df_intradiario['volume'].rolling(window=vol_ma_largo).mean()

    return df_intradiario.dropna()