# optimizer.py (Versión Final v2 - Acelerado con Multiprocesamiento de CPU)

import itertools
import pandas as pd
from datetime import datetime, timedelta
import multiprocessing
import time
from tqdm import tqdm
import matplotlib.pyplot as plt
import numpy as np
from backtester import ejecutar_backtest_avanzado
import api_client
import indicators
import config

pd.set_option('display.max_colwidth', None)
pd.set_option('display.width', 1000) # Para que la tabla se vea más ancha

# Reducimos la grilla de parámetros para una optimización más rápida
parameter_grid = {
    'dias_volatilidad': [9, 10],
    'umbral_vol_alto': [0.009],
    'umbral_vol_bajo': [0.006],
    'dias_momento': [2, 3],
    'stop_loss_tendencia': [0.015, 0.02],
    'take_profit_tendencia': [0.03, 0.04],
    'stop_loss_reversion': [0.015],
}

def worker_backtest(params_tuple):
    symbol, params, datos_completos = params_tuple
    return ejecutar_backtest_avanzado(symbol, params, datos_completos, verbose=False)

def optimizar_estrategia_paralelo():
    start_time = time.time()
    print("--- INICIANDO OPTIMIZADOR DE ESTRATEGIA (CON MÉTRICAS AVANZADAS) ---")
    
    token = api_client.obtener_token()
    if not token: return

    symbol_to_test = api_client.encontrar_futuro_dolar_mas_corto(token)
    if not symbol_to_test:
        print("No se pudo encontrar el símbolo del futuro para optimizar. Abortando.")
        return
    print(f"\n--- Optimizando para el símbolo: {symbol_to_test} ---")
    
    # Calculamos un historial suficiente para cubrir el backtest y los indicadores
    dias_historial_requerido = config.DIAS_BACKTEST + max(parameter_grid['dias_volatilidad']) + max(parameter_grid['dias_momento']) + 5 # 5 días de margen
    fecha_inicio_historial = datetime.now() - timedelta(days=dias_historial_requerido)

    trades_data = api_client.obtener_datos_historicos(token, symbol_to_test,
        fecha_inicio_historial.strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d'))
    if not trades_data: return
    
    datos_completos = indicators.procesar_y_calcular_indicadores(trades_data)
    if datos_completos is None: return

    keys, values = zip(*parameter_grid.items())
    combinaciones = [dict(zip(keys, v)) for v in itertools.product(*values)]
    tasks = [(symbol_to_test, params, datos_completos) for params in combinaciones]
    
    num_cores = multiprocessing.cpu_count()
    print(f"\nSe usarán {num_cores} núcleos de CPU para probar {len(combinaciones)} combinaciones.")

    resultados = []
    with multiprocessing.Pool(processes=num_cores) as pool:
        for resultado in tqdm(pool.imap_unordered(worker_backtest, tasks), total=len(tasks), desc="Optimizando"):
            resultados.append(resultado)

    if not resultados:
        print("\nNo se completó ninguna prueba.")
        return

    resultados_planos = []
    for res in resultados:
        fila = res['parametros'].copy()
        fila['rendimiento'] = res['rendimiento']
        fila['max_drawdown'] = res['max_drawdown']
        fila['max_value'] = res['max_value']
        fila['equity_curve'] = res['equity_curve']
        resultados_planos.append(fila)
        
    resultados_df = pd.DataFrame(resultados_planos)
    resultados_df = resultados_df.sort_values(by='rendimiento', ascending=False).reset_index(drop=True)
    
    end_time = time.time()
    
    print("\n\n--- RANKING DE MEJORES PARÁMETROS ENCONTRADOS ---")
    display_cols = ['rendimiento', 'max_drawdown'] + list(parameter_grid.keys())
    print(resultados_df[display_cols].head(5).to_string())
    print("\n--------------------------------------------------")
    print(f"Optimización completada en { (end_time - start_time) / 60:.2f} minutos.")

    # --- NUEVO: GENERAR GRÁFICO COMPARATIVO CON TABLA ---
    print("\n--- Generando Gráfico Comparativo de Rendimiento para el Top 3 ---")
    
    # 1. Preparar la figura y los ejes para el gráfico
    fig, ax = plt.subplots(figsize=(15, 8))
    
    table_data = []
    colors = ['blue', 'orange', 'green']
    
    # 2. Iterar sobre los 3 mejores resultados para plotear cada curva
    for i in range(min(3, len(resultados_df))):
        top_resultado = resultados_df.iloc[i]
        curva = top_resultado['equity_curve']
        
        if not curva:
            print(f"Rank {i+1} no tiene curva de equity para graficar.")
            continue
            
        df_curva = pd.DataFrame(curva)
        df_curva['timestamp'] = pd.to_datetime(df_curva['timestamp'])
        
        # Plotear la curva de equity en los ejes
        ax.plot(df_curva['timestamp'], df_curva['equity'], label=f'Rank #{i+1} (Rend: {top_resultado["rendimiento"]:.2f}%)', color=colors[i])
        
        # Guardar los datos de los parámetros para la tabla
        params_list = [f"{top_resultado[key]}" for key in parameter_grid.keys()]
        table_data.append(params_list)

    # Configurar el gráfico principal
    ax.set_title(f'Comparación de Rendimiento - Top 3 Parámetros\n{symbol_to_test}')
    ax.set_ylabel('Valor del Portafolio (Equity)')
    ax.grid(True)
    ax.legend()
    
    # 3. Crear y añadir la tabla de parámetros al gráfico
    if table_data:
        # Transponer los datos para que los parámetros queden como filas
        table_data = np.array(table_data).T 
        col_labels = [f'Rank #{j+1}' for j in range(len(table_data[0]))]
        row_labels = list(parameter_grid.keys())
        
        # Ajustar el espacio inferior del gráfico para hacer lugar a la tabla
        fig.subplots_adjust(bottom=0.3)
        
        # Añadir la tabla
        the_table = ax.table(cellText=table_data,
                             rowLabels=row_labels,
                             colLabels=col_labels,
                             loc='bottom',
                             cellLoc='center',
                             bbox=[0, -0.5, 1, 0.3]) # Posición y tamaño de la tabla
        the_table.auto_set_font_size(False)
        the_table.set_fontsize(8)

    # 4. Guardar la figura completa (gráfico + tabla)
    filename = 'top_3_rendimiento_comparativo.png'
    plt.savefig(filename, bbox_inches='tight')
    print(f"Gráfico comparativo guardado como: {filename}")
    
if __name__ == "__main__":
    optimizar_estrategia_paralelo()
