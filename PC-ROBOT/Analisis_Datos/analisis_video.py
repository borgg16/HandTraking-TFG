"""
analisis_video.py  —  Análisis de latencia de video del TFG con métricas avanzadas
Universidad de Málaga · 2026

Instalar dependencias (una sola vez):
    pip install pandas matplotlib

Uso:
    python analisis_video.py Pruebas_Conexion/resultados_unity/PRUEBA_VIDEO_SIN_CARGA.csv
    o para múltiples archivos:
    python analisis_video.py archivo1.csv archivo2.csv archivo3.csv
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path

# ── Configuración General ─────────────────────────────────────────────
WARMUP_SECONDS = 5.0  # Duración de la exclusión de fase de calentamiento (en segundos)
if Path("Pruebas_Conexion").exists():
    CARPETA_RESULTADOS = Path("Pruebas_Conexion/Resultados_Robot")
else:
    CARPETA_RESULTADOS = Path("resultados")
CARPETA_RESULTADOS.mkdir(exist_ok=True)

# ── Comprobación de Argumentos ────────────────────────────────────────
if len(sys.argv) < 2:
    print("Uso: python analisis_video.py ruta_al_archivo_video1.csv [ruta_al_archivo_video2.csv ...]")
    sys.exit(1)

csv_paths = sys.argv[1:]

# ── Funciones de Cálculo de Métricas ──────────────────────────────────
def calcular_metricas(df_segmento, nombre_condicion, t_inicio_sesion):
    """
    Calcula todas las métricas recomendadas para un segmento o sesión,
    excluyendo el período inicial de warm-up.
    """
    # Exclusión del warm-up
    df_effective = df_segmento[df_segmento["t_sesion"] >= (t_inicio_sesion + WARMUP_SECONDS)]
    
    n_bruto = len(df_segmento)
    n_efectivo = len(df_effective)
    
    if n_efectivo == 0:
        return {
            "Condición": nombre_condicion,
            "N Bruto": n_bruto,
            "N Efectivo": 0,
            "duracion": 0,
            "Media (ms)": 0.0,
            "Mediana (ms)": 0.0,
            "P95 (ms)": 0.0,
            "P99 (ms)": 0.0,
            "Máx (ms)": 0.0,
            "Desv.Est (ms)": 0.0,
            "Jitter (ms)": 0.0,
            "FPS Efectivo": 0.0,
            "Pérdida %": 0.0
        }
    
    # Duración efectiva
    t_min_effective = df_effective["t_sesion"].min()
    t_max_effective = df_effective["t_sesion"].max()
    duracion = t_max_effective - t_min_effective
    
    # Latencias
    latencias = df_effective["latencia_ms"]
    media = latencias.mean()
    mediana = latencias.median()
    p95 = latencias.quantile(0.95)
    p99 = latencias.quantile(0.99)
    max_val = latencias.max()
    std_val = latencias.std()
    
    # Jitter (RFC 3550): media de las diferencias absolutas entre latencias consecutivas
    jitter = latencias.diff().abs().mean()
    
    # FPS efectivo logrado
    fps = n_efectivo / duracion if duracion > 0 else 0.0
    
    # Tasa de frames perdidos/descartados por t_captura (en milisegundos)
    df_sorted = df_effective.sort_values(by="t_captura")
    diffs = df_sorted["t_captura"].diff()
    
    lost_frames = 0
    for diff in diffs.dropna():
        if diff > 50.0:  # Umbral para detectar frames perdidos (en 30fps el intervalo es ~33.3ms, >50ms es >1.5 intervalos)
            lost = round(diff / 33.33) - 1
            if lost > 0:
                lost_frames += lost
                
    total_frames = n_efectivo + lost_frames
    loss_pct = (lost_frames / total_frames) * 100.0 if total_frames > 0 else 0.0
    
    return {
        "Condición": nombre_condicion,
        "N Bruto": n_bruto,
        "N Efectivo": n_efectivo,
        "duracion": duracion,
        "Media (ms)": media,
        "Mediana (ms)": mediana,
        "P95 (ms)": p95,
        "P99 (ms)": p99,
        "Máx (ms)": max_val,
        "Desv.Est (ms)": std_val,
        "Jitter (ms)": jitter,
        "FPS Efectivo": fps,
        "Pérdida %": loss_pct
    }

# ── Función para Imprimir Resumen en Consola ─────────────────────────
def imprimir_resumen_consola(res, identificador):
    print("\n" + "=" * 65)
    print(f"  ESTADÍSTICAS: {identificador}")
    print("=" * 65)
    print(f"  Muestras brutas         : {res['N Bruto']}")
    print(f"  Muestras efectivas      : {res['N Efectivo']} (excluyendo warm-up)")
    print(f"  Duración efectiva       : {res['duracion']:.1f} segundos")
    print("-" * 65)
    print(f"  Latencia media          : {res['Media (ms)']:.1f} ms")
    print(f"  Latencia mediana (P50)  : {res['Mediana (ms)']:.1f} ms")
    print(f"  Desviación estándar     : {res['Desv.Est (ms)']:.1f} ms")
    print(f"  Latencia máxima (Máx)   : {res['Máx (ms)']:.1f} ms")
    print(f"  Percentil 95 (P95)      : {res['P95 (ms)']:.1f} ms")
    print(f"  Percentil 99 (P99)      : {res['P99 (ms)']:.1f} ms")
    print(f"  Jitter (RFC 3550)       : {res['Jitter (ms)']:.1f} ms")
    print("-" * 65)
    print(f"  FPS efectivo logrado    : {res['FPS Efectivo']:.2f} fps (objetivo: 30 fps)")
    print(f"  Tasa de frames perdidos : {res['Pérdida %']:.2f}%")
    print("=" * 65)

# ── Función de Generación de Gráficos ─────────────────────────────────
def generar_grafico(df_numeric, marcas, nombre_archivo, nombre_sin_ext, t_inicio_sesion, res_global):
    fig = plt.figure(figsize=(15, 8), constrained_layout=True)
    fig.suptitle(
        f"Análisis de Latencia de Vídeo — {nombre_archivo}\n"
        f"TFG Control de Brazo Robot · Universidad de Málaga",
        fontsize=14, fontweight="bold"
    )
    gs = gridspec.GridSpec(1, 2, figure=fig, width_ratios=[2, 1])

    # Filtrar datos post-warmup
    df_effective = df_numeric[df_numeric["t_sesion"] >= (t_inicio_sesion + WARMUP_SECONDS)]
    
    if df_effective.empty:
        print("Advertencia: No hay suficientes datos después de la fase de calentamiento.")
        return

    # ── Gráfica 1: Latencia a lo largo del tiempo ─────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    
    # Graficar muestras de calentamiento con opacidad baja
    ax1.plot(df_numeric["t_sesion"], df_numeric["latencia_ms"], color="#FF851B", linewidth=1.0, alpha=0.3, label="Calentamiento (Warm-up)")
    # Graficar muestras efectivas normales
    ax1.plot(df_effective["t_sesion"], df_effective["latencia_ms"], color="#FF851B", linewidth=1.2, label="Latencia de vídeo (Efectiva)")
    
    # Sombrear la zona de warm-up en gris
    ax1.axvspan(t_inicio_sesion, t_inicio_sesion + WARMUP_SECONDS, color='gray', alpha=0.15, label=f"Warm-up ({WARMUP_SECONDS}s)")
    
    # Líneas de estadísticas (basadas en datos efectivos)
    ax1.axhline(res_global["Media (ms)"], color="#0074D9", linestyle="-", linewidth=1.5, 
                label=f"Media: {res_global['Media (ms)']:.1f} ms")
    ax1.axhline(res_global["Mediana (ms)"], color="#2ECC40", linestyle="--", linewidth=1.2, 
                label=f"Mediana: {res_global['Mediana (ms)']:.1f} ms")
    ax1.axhline(res_global["P95 (ms)"], color="#FF4136", linestyle=":", linewidth=1.5, 
                label=f"P95: {res_global['P95 (ms)']:.1f} ms")
    ax1.axhline(res_global["P99 (ms)"], color="#B10DC9", linestyle="-.", linewidth=1.5, 
                label=f"P99: {res_global['P99 (ms)']:.1f} ms")

    # Marcas divisorias de condiciones
    colores_marcas = ["#FF4136", "#B10DC9", "#111111", "#001f3f"]
    for i, (_, row) in enumerate(marcas.iterrows()):
        t_marca = float(row["t_sesion"])
        etiqueta = str(row["latencia_ms"]).replace("MARCA_", "")
        color = colores_marcas[i % len(colores_marcas)]
        ax1.axvline(t_marca, color=color, linestyle=":", linewidth=2)
        y_pos = ax1.get_ylim()[1] * 0.85
        ax1.text(t_marca, y_pos, f" {etiqueta}", color=color, fontsize=10, fontweight="bold", rotation=90)

    ax1.set_title("Evolución Temporal de la Latencia")
    ax1.set_xlabel("Tiempo desde el inicio de la sesión (s)")
    ax1.set_ylabel("Latencia (ms)")
    ax1.legend(fontsize=9, loc="upper right")
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(bottom=max(0, df_numeric["latencia_ms"].min() - 10))

    # ── Gráfica 2: Histograma de distribución de la latencia ──────────────
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.hist(df_effective["latencia_ms"], bins=30, color="#FFDC00", edgecolor="black", linewidth=0.5, alpha=0.8, label="Frames efectivos")
    
    # Líneas de estadísticas en histograma
    ax2.axvline(res_global["Media (ms)"], color="#0074D9", linestyle="-", linewidth=1.5, label=f"Media: {res_global['Media (ms)']:.1f} ms")
    ax2.axvline(res_global["Mediana (ms)"], color="#2ECC40", linestyle="--", linewidth=1.2, label=f"Mediana (P50)")
    ax2.axvline(res_global["P95 (ms)"], color="#FF4136", linestyle=":", linewidth=1.5, label=f"P95: {res_global['P95 (ms)']:.1f} ms")
    ax2.axvline(res_global["P99 (ms)"], color="#B10DC9", linestyle="-.", linewidth=1.5, label=f"P99: {res_global['P99 (ms)']:.1f} ms")
    
    ax2.set_title("Distribución de la Latencia")
    ax2.set_xlabel("Latencia (ms)")
    ax2.set_ylabel("Frecuencia (número de frames)")
    ax2.grid(True, alpha=0.3, axis="y")
    ax2.legend(fontsize=8, loc="upper right")

    salida = CARPETA_RESULTADOS / f"informe_video_{nombre_sin_ext}.png"
    plt.savefig(salida, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nGráfica de análisis guardada en: {salida}")

# ── Función para Formatear Tabla Markdown ─────────────────────────────
def formatear_tabla(resultados):
    cabecera = (
        "| Condición | N Bruto | N Efectivo | Media | Mediana | P95 | P99 | Máx | Desv.Est | Jitter | FPS Efec. | Pérdida % |\n"
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    )
    filas = []
    for r in resultados:
        fila = (
            f"| {r['Condición']} | {r['N Bruto']} | {r['N Efectivo']} | "
            f"{r['Media (ms)']:.1f} ms | {r['Mediana (ms)']:.1f} ms | {r['P95 (ms)']:.1f} ms | "
            f"{r['P99 (ms)']:.1f} ms | {r['Máx (ms)']:.1f} ms | {r['Desv.Est (ms)']:.1f} ms | "
            f"{r['Jitter (ms)']:.1f} ms | {r['FPS Efectivo']:.1f} fps | {r['Pérdida %']:.2f}% |"
        )
        filas.append(fila)
    return cabecera + "\n" + "\n".join(filas)

# ── Función para Generar Tabla en PNG ──────────────────────────────────
def generar_tabla_png(resultados, ruta_salida):
    """
    Genera una imagen PNG con la tabla de resultados maquetada de forma profesional.
    """
    fig, ax = plt.subplots(figsize=(11, len(resultados) * 0.5 + 1.0))
    ax.axis('off')
    ax.axis('tight')

    cabeceras = [
        "Condición", "N Bruto", "N Efectivo", "Media", 
        "Mediana", "P95", "P99", "Máx", 
        "Desv.Est", "Jitter", "FPS Efec.", "Pérdida %"
    ]
    
    filas = []
    for r in resultados:
        filas.append([
            r["Condición"],
            f"{r['N Bruto']}",
            f"{r['N Efectivo']}",
            f"{r['Media (ms)']:.1f} ms",
            f"{r['Mediana (ms)']:.1f} ms",
            f"{r['P95 (ms)']:.1f} ms",
            f"{r['P99 (ms)']:.1f} ms",
            f"{r['Máx (ms)']:.1f} ms",
            f"{r['Desv.Est (ms)']:.1f} ms",
            f"{r['Jitter (ms)']:.1f} ms",
            f"{r['FPS Efectivo']:.1f} fps",
            f"{r['Pérdida %']:.2f}%"
        ])
        
    tabla = ax.table(
        cellText=filas, 
        colLabels=cabeceras, 
        loc='center', 
        cellLoc='center'
    )
    
    # Estilizado de la tabla
    tabla.auto_set_font_size(False)
    tabla.set_fontsize(9)
    tabla.scale(1.0, 1.8)  # Ajuste de tamaño de celda para padding cómodo
    
    # Colores y fuentes de cabecera y celdas (Azul corporativo UMA / elegante)
    for (row, col), cell in tabla.get_celld().items():
        cell.set_edgecolor('#D3D3D3')  # Borde gris claro
        if row == 0:
            cell.set_text_props(weight='bold', color='white')
            cell.set_facecolor('#0074D9')  # Azul elegante para cabecera
        else:
            cell.set_text_props(color='#111111')
            if row % 2 == 0:
                cell.set_facecolor('#F9F9F9')  # Rayado cebra gris muy claro
            else:
                cell.set_facecolor('#FFFFFF')
                
    plt.savefig(ruta_salida, dpi=200, bbox_inches='tight')
    plt.close()
    print(f"Tabla de resultados guardada como imagen PNG en: {ruta_salida}")

# ── Ejecución Principal ───────────────────────────────────────────────
resultados_globales = []

if len(csv_paths) == 1:
    csv_path = csv_paths[0]
    nombre_archivo = Path(csv_path).name
    nombre_sin_ext = Path(csv_path).stem
    
    try:
        df = pd.read_csv(csv_path, header=0, names=["t_sesion", "latencia_ms", "t_captura", "t_recibido"])
    except Exception as e:
        df = pd.read_csv(csv_path)
        
    df_numeric = df.copy()
    df_numeric["latencia_ms"] = pd.to_numeric(df_numeric["latencia_ms"], errors="coerce")
    df_numeric["t_sesion"] = pd.to_numeric(df_numeric["t_sesion"], errors="coerce")
    df_numeric["t_captura"] = pd.to_numeric(df_numeric["t_captura"], errors="coerce")
    df_numeric["t_recibido"] = pd.to_numeric(df_numeric["t_recibido"], errors="coerce")
    df_numeric = df_numeric.dropna(subset=["latencia_ms", "t_sesion"])
    
    if df_numeric.empty:
        print(f"No se encontraron muestras válidas en {csv_path}")
        sys.exit(1)
        
    # Extraer marcas
    df["latencia_str"] = df["latencia_ms"].astype(str)
    marcas = df[df["latencia_str"].str.startswith("MARCA_")].copy()
    if not marcas.empty:
        marcas["t_sesion"] = pd.to_numeric(marcas["t_sesion"], errors="coerce")
    
    t_inicio_sesion = df_numeric["t_sesion"].min()
    
    if marcas.empty:
        # Analizar como una única sesión
        nombre_condicion = nombre_sin_ext.replace("PRUEBA_VIDEO_", "")
        res = calcular_metricas(df_numeric, nombre_condicion, t_inicio_sesion)
        resultados_globales.append(res)
        
        imprimir_resumen_consola(res, nombre_archivo)
        generar_grafico(df_numeric, marcas, nombre_archivo, nombre_sin_ext, t_inicio_sesion, res)
    else:
        # Segmentar por marcas
        puntos_corte = [t_inicio_sesion]
        etiquetas = ["Inicio"]
        for _, row in marcas.iterrows():
            puntos_corte.append(float(row["t_sesion"]))
            etiquetas.append(str(row["latencia_ms"]).replace("MARCA_", ""))
        puntos_corte.append(df_numeric["t_sesion"].max())
        etiquetas.append("Fin")
        
        for i in range(len(puntos_corte) - 2):
            t_inicio = puntos_corte[i]
            t_fin = puntos_corte[i+1]
            nombre_condicion = etiquetas[i+1]
            
            segmento = df_numeric[(df_numeric["t_sesion"] >= t_inicio) & (df_numeric["t_sesion"] < t_fin)]
            if not segmento.empty:
                # El warm-up se descuenta respecto al t_inicio de este segmento para ser justos en cada fase
                res = calcular_metricas(segmento, nombre_condicion, t_inicio)
                resultados_globales.append(res)
                
        # Último segmento
        t_inicio = puntos_corte[-2]
        t_fin = puntos_corte[-1]
        segmento = df_numeric[df_numeric["t_sesion"] >= t_inicio]
        if not segmento.empty and len(puntos_corte) > 2:
            res = calcular_metricas(segmento, "Post-Última Marca", t_inicio)
            resultados_globales.append(res)
            
        for res in resultados_globales:
            imprimir_resumen_consola(res, f"{nombre_archivo} [{res['Condición']}]")
            
        # Grafico global
        res_global = calcular_metricas(df_numeric, "Sesión Completa", t_inicio_sesion)
        generar_grafico(df_numeric, marcas, nombre_archivo, nombre_sin_ext, t_inicio_sesion, res_global)
else:
    # Múltiples archivos independientes
    for csv_path in csv_paths:
        nombre_archivo = Path(csv_path).name
        nombre_sin_ext = Path(csv_path).stem
        
        try:
            df = pd.read_csv(csv_path, header=0, names=["t_sesion", "latencia_ms", "t_captura", "t_recibido"])
        except Exception as e:
            df = pd.read_csv(csv_path)
            
        df_numeric = df.copy()
        df_numeric["latencia_ms"] = pd.to_numeric(df_numeric["latencia_ms"], errors="coerce")
        df_numeric["t_sesion"] = pd.to_numeric(df_numeric["t_sesion"], errors="coerce")
        df_numeric["t_captura"] = pd.to_numeric(df_numeric["t_captura"], errors="coerce")
        df_numeric["t_recibido"] = pd.to_numeric(df_numeric["t_recibido"], errors="coerce")
        df_numeric = df_numeric.dropna(subset=["latencia_ms", "t_sesion"])
        
        if df_numeric.empty:
            print(f"No se encontraron muestras válidas en {csv_path}. Saltando...")
            continue
            
        t_inicio_sesion = df_numeric["t_sesion"].min()
        nombre_condicion = nombre_sin_ext.replace("PRUEBA_VIDEO_", "")
        
        # Calcular estadísticas individuales
        res = calcular_metricas(df_numeric, nombre_condicion, t_inicio_sesion)
        resultados_globales.append(res)
        
        imprimir_resumen_consola(res, nombre_archivo)
        
        # Generar gráfico para este archivo
        df["latencia_str"] = df["latencia_ms"].astype(str)
        marcas = df[df["latencia_str"].str.startswith("MARCA_")].copy()
        if not marcas.empty:
            marcas["t_sesion"] = pd.to_numeric(marcas["t_sesion"], errors="coerce")
            
        generar_grafico(df_numeric, marcas, nombre_archivo, nombre_sin_ext, t_inicio_sesion, res)

# ── Generar y Guardar Tabla Resumen ───────────────────────────────────
if resultados_globales:
    tabla_md = formatear_tabla(resultados_globales)
    print("\n" + "─" * 40 + " TABLA RESUMEN TFG " + "─" * 40)
    print(tabla_md)
    print("─" * 99)
    
    # Determinar el sufijo para nombrar el archivo de forma descriptiva
    if len(csv_paths) == 1:
        sufijo = Path(csv_paths[0]).stem
    else:
        sufijo = "comparativa"
        
    # 1. Guardar en formato Markdown
    ruta_tabla = CARPETA_RESULTADOS / f"tabla_resumen_video_{sufijo}.md"
    with open(ruta_tabla, "w", encoding="utf-8") as f:
        f.write("# Tabla Resumen de Latencia y Calidad de Vídeo (TFG)\n\n")
        f.write(tabla_md)
        f.write("\n\n---\n")
        f.write(f"*Nota: Se ha excluido una fase de calentamiento inicial de {WARMUP_SECONDS}s en cada condición/archivo.*\n")
        f.write("*Jitter calculado según RFC 3550 como la media de las diferencias absolutas de latencia consecutivas.*\n")
        f.write("*Pérdida % estimada a partir de los saltos de tiempo en la captura de frames (gaps > 50ms, asumiendo 30 fps nominales).*\n")
        
    print(f"Tabla resumen guardada en formato Markdown en: {ruta_tabla}")
    
    # 2. Guardar en formato PNG (imagen maquetada para TFG)
    ruta_tabla_png = CARPETA_RESULTADOS / f"tabla_resumen_video_{sufijo}.png"
    generar_tabla_png(resultados_globales, ruta_tabla_png)
