# optimizer.py (Versión Final v2 - Acelerado con Multiprocesamiento de CPU)

import random
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

def generate_random_combinations(param_ranges, n_combinations):
    """Genera n_combinations de parámetros aleatorios basados en los rangos definidos."""
    combinations = []
    for _ in range(n_combinations):
        params = {}
        for key, value_spec in param_ranges.items():
            if value_spec['type'] == 'int':
                params[key] = random.randint(value_spec['min'], value_spec['max'])
            elif value_spec['type'] == 'float':
                # Redondeamos a 4 decimales para evitar números muy largos
                params[key] = round(random.uniform(value_spec['min'], value_spec['max']), 4)
        combinations.append(params)
    return combinations

def worker_backtest(params_tuple):
    symbol, params, datos_completos = params_tuple
    return ejecutar_backtest_avanzado(symbol, params, datos_completos, verbose=False)

def optimizar_estrategia_paralelo():
    start_time = time.time()
    print("--- INICIANDO OPTIMIZADOR DE ESTRATEGIA (RANDOM SEARCH) ---")
    
    token = api_client.obtener_token()
    if not token: return

    symbol_to_test = api_client.encontrar_futuro_dolar_mas_corto(token)
    if not symbol_to_test:
        print("No se pudo encontrar el símbolo del futuro para optimizar. Abortando.")
        return
    print(f"\n--- Optimizando para el símbolo: {symbol_to_test} ---")
    
    # Calculamos un historial suficiente para cubrir el backtest y los indicadores
    # Se necesitan ~90 días de historial para el indicador de volatilidad de 3 meses (18000 velas de 1min)
    dias_historial_requerido = config.DIAS_BACKTEST + 95 # 90 días para el indicador + 5 de margen
    fecha_inicio_historial = datetime.now() - timedelta(days=dias_historial_requerido)

    trades_data = api_client.obtener_datos_historicos(token, symbol_to_test,
        fecha_inicio_historial.strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d'))
    if not trades_data: return
    
    datos_completos = indicators.procesar_y_calcular_indicadores(trades_data)
    if datos_completos is None: return

    # Generar combinaciones aleatorias
    param_ranges = config.OPTIMIZER_CONFIG['param_ranges']
    n_combinations = config.OPTIMIZER_CONFIG['n_combinations']
    combinaciones = generate_random_combinations(param_ranges, n_combinations)

    tasks = [(symbol_to_test, params, datos_completos) for params in combinaciones]
    
    num_cores = multiprocessing.cpu_count()
    print(f"\nSe usarán {num_cores} núcleos de CPU para probar {len(combinaciones)} combinaciones aleatorias.")

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
    
    # Usamos las keys de la configuración para mostrar los resultados
    param_keys = list(config.OPTIMIZER_CONFIG['param_ranges'].keys())

    print("\n\n--- RANKING DE MEJORES PARÁMETROS ENCONTRADOS ---")
    display_cols = ['rendimiento', 'max_drawdown'] + param_keys
    print(resultados_df[display_cols].head(5).to_string())
    print("\n--------------------------------------------------")
    print(f"Optimización completada en { (end_time - start_time) / 60:.2f} minutos.")

    # --- NUEVO: GENERAR GRÁFICO COMPARATIVO CON TABLA ---
    print("\n--- Generando Gráfico Comparativo de Rendimiento para el Top 25 ---")
    
    # 1. Preparar la figura y los ejes para el gráfico
    fig, ax = plt.subplots(figsize=(15, 8))
    
    # 2. Iterar sobre los 25 mejores resultados para plotear cada curva
    num_to_plot = min(25, len(resultados_df))
    # Generar un colormap para distinguir las curvas
    colors = plt.cm.jet(np.linspace(0, 1, num_to_plot))

    for i in range(num_to_plot):
        top_resultado = resultados_df.iloc[i]
        curva = top_resultado['equity_curve']
        
        if not curva:
            print(f"Rank {i+1} no tiene curva de equity para graficar.")
            continue
            
        df_curva = pd.DataFrame(curva)
        df_curva['timestamp'] = pd.to_datetime(df_curva['timestamp'])
        
        # Plotear la curva. Solo las 3 primeras tendrán una leyenda para no saturar el gráfico.
        label = f'Rank #{i+1} (Rend: {top_resultado["rendimiento"]:.2f}%)' if i < 3 else None
        ax.plot(df_curva['timestamp'], df_curva['equity'], label=label, color=colors[i], alpha=0.8, linewidth=1.5 if i < 3 else 1.0)

    # 3. Preparar los datos para la tabla (solo los 3 mejores)
    table_data = []
    param_keys = list(config.OPTIMIZER_CONFIG['param_ranges'].keys())
    for i in range(min(3, len(resultados_df))):
        top_resultado = resultados_df.iloc[i]
        params_list = [f"{top_resultado[key]}" for key in param_keys]
        table_data.append(params_list)

    # Configurar el gráfico principal
    ax.set_title(f'Comparación de Rendimiento - Top 25 Parámetros\n{symbol_to_test}')
    ax.set_ylabel('Valor del Portafolio (Equity)')
    ax.grid(True)
    ax.legend()
    
    # 3. Crear y añadir la tabla de parámetros al gráfico
    if table_data:
        # Transponer los datos para que los parámetros queden como filas
        table_data = np.array(table_data).T 
        col_labels = [f'Rank #{j+1}' for j in range(len(table_data[0]))]
        row_labels = param_keys
        
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
