# optimizer.py (Versión Final v2 - Acelerado con Multiprocesamiento de CPU)

import itertools
import pandas as pd
from datetime import datetime, timedelta
import multiprocessing
import time
from tqdm import tqdm
import matplotlib.pyplot as plt

from backtester import ejecutar_backtest_avanzado, SIMBOLO_A_TESTEAR, FECHA_INICIO
import api_client
import indicators

pd.set_option('display.max_colwidth', None)
pd.set_option('display.width', 1000) # Para que la tabla se vea más ancha

# La grilla de parámetros es la misma
parameter_grid = {
    'dias_volatilidad': [8, 9, 10],
    'umbral_vol_alto': [0.008, 0.009, 0.010],
    'umbral_vol_bajo': [0.005, 0.006, 0.007],
    'dias_momento': [1, 2, 3, 4],
    'stop_loss_tendencia': [0.01, 0.015, 0.02, 0.025],
    'take_profit_tendencia': [0.025, 0.03, 0.04, 0.045],
    'stop_loss_reversion': [0.01, 0.015, 0.02],
}

def worker_backtest(params_tuple):
    """Función de envoltura para que el pool de procesos pueda llamar al backtester."""
    params, datos_completos = params_tuple
    # Devuelve el diccionario completo de resultados
    return ejecutar_backtest_avanzado(params, datos_completos, verbose=False)

def optimizar_estrategia_paralelo():
    start_time = time.time()
    print("--- INICIANDO OPTIMIZADOR DE ESTRATEGIA (ACELERADO CON MULTIPROCESAMIENTO) ---")
    
    token = api_client.obtener_token()
    if not token: return
    
    # Calcular fecha de inicio extendida para tener suficientes datos para cualquier combinación
    historial_extendido_inicio = FECHA_INICIO - timedelta(days=max(parameter_grid['dias_volatilidad']) + max(parameter_grid['dias_momento']))
    trades_data = api_client.obtener_datos_historicos(token, SIMBOLO_A_TESTEAR, 
        historial_extendido_inicio.strftime('%Y-%m-%d'), 
        datetime.now().strftime('%Y-%m-%d'))
    if not trades_data: return
    
    datos_completos = indicators.procesar_y_calcular_indicadores(trades_data)
    if datos_completos is None: return

    keys, values = zip(*parameter_grid.items())
    combinaciones = [dict(zip(keys, v)) for v in itertools.product(*values)]
    tasks = [(params, datos_completos) for params in combinaciones]
    
    num_cores = multiprocessing.cpu_count()
    print(f"\nSe usarán {num_cores} núcleos de CPU para probar {len(combinaciones)} combinaciones.")

    resultados = []
    with multiprocessing.Pool(processes=num_cores) as pool:
        for resultado in tqdm(pool.imap_unordered(worker_backtest, tasks), total=len(tasks), desc="Optimizando"):
            resultados.append(resultado)

    if not resultados:
        print("\nNo se completó ninguna prueba.")
        return

    # Aplanar los resultados para mostrarlos en una tabla
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

    # GENERAR GRÁFICOS
    print("\n--- Generando Gráficos de Rendimiento para el Top 3 ---")
    for i in range(min(3, len(resultados_df))):
        top_resultado = resultados_df.iloc[i]
        curva = top_resultado['equity_curve']
        
        if not curva: continue
            
        df_curva = pd.DataFrame(curva)
        df_curva['timestamp'] = pd.to_datetime(df_curva['timestamp'])
        
        plt.figure(figsize=(12, 6))
        plt.plot(df_curva['timestamp'], df_curva['equity'])
        plt.title(f'Rendimiento en el Tiempo - Rank #{i+1}\nRendimiento: {top_resultado["rendimiento"]:.2f}% | Max Drawdown: {top_resultado["max_drawdown"]:.2f}%')
        plt.xlabel('Fecha y Hora')
        plt.ylabel('Valor del Portafolio (Equity)')
        plt.grid(True)
        plt.tight_layout()
        
        filename = f'rendimiento_rank_{i+1}.png'
        plt.savefig(filename)
        print(f"Gráfico guardado como: {filename}")
    
if __name__ == "__main__":
    optimizar_estrategia_paralelo()