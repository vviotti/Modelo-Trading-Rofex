# indicators.py (Refactorizado para Modelo 1)

import pandas as pd
import pandas_ta as ta

def procesar_y_calcular_indicadores(trades_historicos,
                                    # Parámetros para Modelo 1 (Volatilidad/Momentum)
                                    ema_rapida_periodo=10,
                                    ema_lenta_periodo=30,
                                    bb_corto_periodo=750,  # Aprox. 2.5 días en velas de 1min (300 min/día)
                                    bb_corto_std=2.0,
                                    bb_largo_periodo=18000, # Aprox. 3 meses en velas de 1min (60 días * 300 min/día)
                                    bb_largo_std=2.5, # Usamos más std para "alta certeza"

                                    # Parámetros originales (pueden ser deprecados o usados por otros modelos)
                                    rsi_periodo=14,
                                    vol_ma_largo=50):
    """
    Toma una lista de trades, los procesa en velas de 1 minuto con OHLCV y calcula
    los indicadores técnicos necesarios para la estrategia.
    """
    if not trades_historicos:
        print("No se proporcionaron trades históricos.")
        return None
    df = pd.DataFrame(trades_historicos)

    # Convertir a tipos numéricos, manejando errores
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df['size'] = pd.to_numeric(df['size'], errors='coerce')
    df.dropna(subset=['price', 'size'], inplace=True)

    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime').sort_index()

    # Resample a 1 minuto y calcular OHLCV
    agg_dict = { 'price': 'ohlc', 'size': 'sum' }
    df_intradiario = df.resample('1min').agg(agg_dict)
    df_intradiario.columns = ['open', 'high', 'low', 'close', 'volume'] # Aplanar MultiIndex
    
    # Rellenar fines de semana o huecos sin trades con el último valor conocido
    df_intradiario.ffill(inplace=True)

    # El df debe tener suficientes datos para el indicador más largo
    if len(df_intradiario) < bb_largo_periodo:
        print(f"ADVERTENCIA: Datos insuficientes para el indicador de volatilidad a largo plazo. Se necesitan {bb_largo_periodo} velas, pero solo hay {len(df_intradiario)}.")
        # No retornamos None para permitir pruebas con conjuntos de datos más pequeños, pero los indicadores largos serán NaN.

    # --- CÁLCULO DE INDICADORES PARA MODELO 1 ---
    # Medias Móviles Exponenciales (Momentum)
    df_intradiario[f'EMA_{ema_rapida_periodo}'] = ta.ema(close=df_intradiario['close'], length=ema_rapida_periodo)
    df_intradiario[f'EMA_{ema_lenta_periodo}'] = ta.ema(close=df_intradiario['close'], length=ema_lenta_periodo)

    # Bandas de Bollinger a corto plazo (Volatilidad de 2-3 días)
    short_ma = df_intradiario['close'].rolling(window=bb_corto_periodo).mean()
    short_std = df_intradiario['close'].rolling(window=bb_corto_periodo).std()
    df_intradiario[f'BBU_SHORT'] = short_ma + (short_std * bb_corto_std)
    df_intradiario[f'BBL_SHORT'] = short_ma - (short_std * bb_corto_std)

    # Bandas de Bollinger a largo plazo (Volatilidad de 3 meses, para "alta certeza")
    long_ma = df_intradiario['close'].rolling(window=bb_largo_periodo).mean()
    long_std = df_intradiario['close'].rolling(window=bb_largo_periodo).std()
    df_intradiario[f'BBU_LONG'] = long_ma + (long_std * bb_largo_std)
    df_intradiario[f'BBL_LONG'] = long_ma - (long_std * bb_largo_std)

    # --- OTROS INDICADORES ---
    df_intradiario[f'RSI_{rsi_periodo}'] = ta.rsi(close=df_intradiario['close'], length=rsi_periodo)
    df_intradiario[f'volume_MA_{vol_ma_largo}'] = df_intradiario['volume'].rolling(window=vol_ma_largo).mean()

    # Eliminar filas con NaN generados por los indicadores de período más corto
    # Los indicadores de período largo tendrán NaN al principio, lo cual es esperado
    return df_intradiario.dropna(subset=[f'EMA_{ema_lenta_periodo}', 'BBL_SHORT'])