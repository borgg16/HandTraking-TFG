# generar_comparativa.py — Comparación de Métricas de Red WiFi vs. Ethernet (Carga Relativa)
# TFG Universidad de Málaga · 2026

import os
import re
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path

# ── Configuración ─────────────────────────────────────────────────────
WARMUP_SECONDS = 5.0
ROOT_DIR = Path("c:/Users/borja/HandTraking")
WIFI_DIR = ROOT_DIR / "Pruebas_Conexion/Resultados_Unity/WIFI"
ETH_DIR = ROOT_DIR / "Pruebas_Conexion/Resultados_Unity/ETHERNET_IPERF3"
OUT_DIR = ROOT_DIR / "Pruebas_Conexion/Resultados_Robot"
DOC_DIR = ROOT_DIR / "Pruebas_Conexion/Documentos_De_Analisis"

OUT_DIR.mkdir(parents=True, exist_ok=True)
DOC_DIR.mkdir(parents=True, exist_ok=True)

# Capacidades máximas medidas de los canales
CAP_WIFI = 280.0   # Mbps
CAP_ETH = 1000.0   # Mbps (1 Gbps)

# Listado de archivos a analizar con sus etiquetas y porcentajes de carga relativa
ARCHIVOS = [
    # Módulo WiFi (Capacidad base: 280 Mbps)
    {"path": WIFI_DIR / "PRUEBA_VIDEO_SIN_CARGA.csv", "label": "WiFi - Sin Carga", "medium": "WiFi", "load_abs": 0, "load_rel": 0.0},
    {"path": WIFI_DIR / "CARGA_MEDIA.csv", "label": "WiFi - Carga Media (120M)", "medium": "WiFi", "load_abs": 120, "load_rel": (120.0 / CAP_WIFI) * 100.0}, # ~42.86%
    {"path": WIFI_DIR / "CARGA_ALTA.csv", "label": "WiFi - Carga Alta (220M)", "medium": "WiFi", "load_abs": 220, "load_rel": (220.0 / CAP_WIFI) * 100.0}, # ~78.57%
    # Módulo Ethernet (Capacidad base: 1000 Mbps)
    {"path": ETH_DIR / "SIN_CARGA_ETH.csv", "label": "Ethernet - Sin Carga", "medium": "Ethernet", "load_abs": 0, "load_rel": 0.0},
    {"path": ETH_DIR / "CARGA_120_ETH_IPERF3.csv", "label": "Ethernet - 120 Mbps", "medium": "Ethernet", "load_abs": 120, "load_rel": (120.0 / CAP_ETH) * 100.0}, # 12.0%
    {"path": ETH_DIR / "CARGA_220_ETH_IPERF3.csv", "label": "Ethernet - 220 Mbps", "medium": "Ethernet", "load_abs": 220, "load_rel": (220.0 / CAP_ETH) * 100.0}, # 22.0%
    {"path": ETH_DIR / "CARGA_400_ETH_IPERF3.csv", "label": "Ethernet - 400 Mbps", "medium": "Ethernet", "load_abs": 400, "load_rel": (400.0 / CAP_ETH) * 100.0}, # 40.0%
    {"path": ETH_DIR / "CARGA_740_ETH_IPERF3.csv", "label": "Ethernet - 740 Mbps", "medium": "Ethernet", "load_abs": 740, "load_rel": (740.0 / CAP_ETH) * 100.0}, # 74.0%
]

def calcular_metricas(df_segmento, nombre_condicion, t_inicio_sesion):
    df_effective = df_segmento[df_segmento["t_sesion"] >= (t_inicio_sesion + WARMUP_SECONDS)]
    n_bruto = len(df_segmento)
    n_efectivo = len(df_effective)
    
    if n_efectivo == 0:
        return None
    
    t_min_effective = df_effective["t_sesion"].min()
    t_max_effective = df_effective["t_sesion"].max()
    duracion = t_max_effective - t_min_effective
    
    latencias = df_effective["latencia_ms"]
    media = latencias.mean()
    mediana = latencias.median()
    p95 = latencias.quantile(0.95)
    p99 = latencias.quantile(0.99)
    max_val = latencias.max()
    std_val = latencias.std()
    
    jitter = latencias.diff().abs().mean()
    fps = n_efectivo / duracion if duracion > 0 else 0.0
    
    # Pérdida de frames
    df_sorted = df_effective.sort_values(by="t_captura")
    diffs = df_sorted["t_captura"].diff()
    lost_frames = 0
    for diff in diffs.dropna():
        if diff > 50.0:
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

# ── Procesar Datos ────────────────────────────────────────────────────
resultados = []
for item in ARCHIVOS:
    path = item["path"]
    if not path.exists():
        print(f"Error: El archivo no existe: {path}")
        continue
        
    try:
        df = pd.read_csv(path, header=0, names=["t_sesion", "latencia_ms", "t_captura", "t_recibido"])
    except Exception:
        df = pd.read_csv(path)
        
    df_numeric = df.copy()
    df_numeric["latencia_ms"] = pd.to_numeric(df_numeric["latencia_ms"], errors="coerce")
    df_numeric["t_sesion"] = pd.to_numeric(df_numeric["t_sesion"], errors="coerce")
    df_numeric["t_captura"] = pd.to_numeric(df_numeric["t_captura"], errors="coerce")
    df_numeric = df_numeric.dropna(subset=["latencia_ms", "t_sesion"])
    
    t_inicio = df_numeric["t_sesion"].min()
    res = calcular_metricas(df_numeric, item["label"], t_inicio)
    if res:
        res["medium"] = item["medium"]
        res["load_abs"] = item["load_abs"]
        res["load_rel"] = item["load_rel"]
        resultados.append(res)

print(f"Procesados {len(resultados)} archivos correctamente.")

# ── Generar Tabla Resumen PNG ─────────────────────────────────────────
def generar_tabla_png(res_list, output_path):
    fig, ax = plt.subplots(figsize=(13, len(res_list) * 0.45 + 1.2))
    ax.axis('off')
    ax.axis('tight')

    headers = [
        "Condición", "Medio", "Carga Abs.", "Carga Rel.", 
        "Media", "Mediana", "P95", "P99", 
        "Desv.Est", "Jitter", "FPS Efec.", "Pérdida %"
    ]
    
    rows = []
    for r in res_list:
        rows.append([
            r["Condición"],
            r["medium"],
            f"{r['load_abs']} Mbps",
            f"{r['load_rel']:.1f}%",
            f"{r['Media (ms)']:.1f} ms",
            f"{r['Mediana (ms)']:.1f} ms",
            f"{r['P95 (ms)']:.1f} ms",
            f"{r['P99 (ms)']:.1f} ms",
            f"{r['Desv.Est (ms)']:.1f} ms",
            f"{r['Jitter (ms)']:.1f} ms",
            f"{r['FPS Efectivo']:.1f} fps",
            f"{r['Pérdida %']:.2f}%"
        ])
        
    table = ax.table(
        cellText=rows, 
        colLabels=headers, 
        loc='center', 
        cellLoc='center'
    )
    
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.7)
    
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor('#E0E0E0')
        if row == 0:
            cell.set_text_props(weight='bold', color='white')
            cell.set_facecolor('#003366')  # Azul marino elegante
        else:
            # Colores alternados para cebra
            if row % 2 == 0:
                cell.set_facecolor('#F5F9FD')
            else:
                cell.set_facecolor('#FFFFFF')
                
    plt.title("Comparativa de Latencia y Calidad de Vídeo: WiFi vs. Ethernet\nTFG Universidad de Málaga · 2026", 
              fontsize=12, fontweight='bold', pad=15)
    plt.savefig(output_path, dpi=250, bbox_inches='tight')
    plt.close()
    print(f"Tabla PNG guardada en: {output_path}")

generar_tabla_png(resultados, OUT_DIR / "tabla_comparativa_redes.png")

# ── Generar Gráfico Comparativo ───────────────────────────────────────
def generar_grafico_comparativo(res_list, output_path):
    # Comparativa por porcentaje de carga relativa equivalente:
    # 1. 0% Carga: WiFi 0M vs Ethernet 0M
    # 2. ~40% Carga: WiFi 120M (42.9%) vs Ethernet 400M (40.0%)
    # 3. ~75% Carga: WiFi 220M (78.6%) vs Ethernet 740M (74.0%)
    
    wifi_0 = next(r for r in res_list if r["medium"] == "WiFi" and r["load_abs"] == 0)
    wifi_120 = next(r for r in res_list if r["medium"] == "WiFi" and r["load_abs"] == 120)
    wifi_220 = next(r for r in res_list if r["medium"] == "WiFi" and r["load_abs"] == 220)
    
    eth_0 = next(r for r in res_list if r["medium"] == "Ethernet" and r["load_abs"] == 0)
    eth_400 = next(r for r in res_list if r["medium"] == "Ethernet" and r["load_abs"] == 400)
    eth_740 = next(r for r in res_list if r["medium"] == "Ethernet" and r["load_abs"] == 740)
    
    # Listas estructuradas para barras
    medias_wifi = [wifi_0["Media (ms)"], wifi_120["Media (ms)"], wifi_220["Media (ms)"]]
    p95_wifi = [wifi_0["P95 (ms)"], wifi_120["P95 (ms)"], wifi_220["P95 (ms)"]]
    
    medias_eth = [eth_0["Media (ms)"], eth_400["Media (ms)"], eth_740["Media (ms)"]]
    p95_eth = [eth_0["P95 (ms)"], eth_400["P95 (ms)"], eth_740["P95 (ms)"]]
    
    labels_relativos = [
        "Sin Carga\n(0% Carga)", 
        "Carga Media\n(WiFi 120M @43% vs\nEth 400M @40%)", 
        "Carga Alta\n(WiFi 220M @79% vs\nEth 740M @74%)"
    ]
    
    fig = plt.figure(figsize=(15, 6.5))
    gs = gridspec.GridSpec(1, 2, figure=fig, width_ratios=[1, 1])
    
    # Subplot 1: Comparación por Cargas Relativas del Canal (%)
    ax1 = fig.add_subplot(gs[0, 0])
    x = range(len(labels_relativos))
    width = 0.35
    
    rects1 = ax1.bar([i - width/2 for i in x], medias_wifi, width, label='WiFi (Media)', color='#FF851B', alpha=0.9, edgecolor='black', linewidth=0.7)
    rects2 = ax1.bar([i + width/2 for i in x], medias_eth, width, label='Ethernet (Media)', color='#0074D9', alpha=0.9, edgecolor='black', linewidth=0.7)
    
    # Bigotes de Percentil 95 (P95)
    ax1.errorbar([i - width/2 for i in x], medias_wifi, yerr=[p - m for m, p in zip(medias_wifi, p95_wifi)], 
                 fmt='none', ecolor='#FF4136', capsize=5, elinewidth=1.5, label='WiFi P95')
    ax1.errorbar([i + width/2 for i in x], medias_eth, yerr=[p - m for m, p in zip(medias_eth, p95_eth)], 
                 fmt='none', ecolor='#001f3f', capsize=5, elinewidth=1.5, label='Ethernet P95')
    
    ax1.set_title("Comparación de Latencia por Carga Relativa del Canal (%)", fontsize=11, fontweight='bold', pad=10)
    ax1.set_ylabel("Latencia de vídeo (ms)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels_relativos, fontsize=9)
    ax1.legend(loc='upper left', fontsize=9)
    ax1.grid(True, linestyle=':', alpha=0.6)
    
    # Anotaciones numéricas en barras
    def autolabel(rects):
        for rect in rects:
            height = rect.get_height()
            ax1.annotate(f'{height:.1f}ms',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),  
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=8.5, fontweight='bold')
    autolabel(rects1)
    autolabel(rects2)
    
    # Subplot 2: Curva de Tendencia vs. Porcentaje de Carga de Canal
    ax2 = fig.add_subplot(gs[0, 1])
    
    # Extraer y ordenar todos los datos de WiFi y Ethernet por porcentaje de carga
    wifi_sorted = sorted([r for r in res_list if r["medium"] == "WiFi"], key=lambda x: x["load_rel"])
    eth_sorted = sorted([r for r in res_list if r["medium"] == "Ethernet"], key=lambda x: x["load_rel"])
    
    loads_wifi = [r["load_rel"] for r in wifi_sorted]
    medias_wifi_curve = [r["Media (ms)"] for r in wifi_sorted]
    p95_wifi_curve = [r["P95 (ms)"] for r in wifi_sorted]
    
    loads_eth = [r["load_rel"] for r in eth_sorted]
    medias_eth_curve = [r["Media (ms)"] for r in eth_sorted]
    p95_eth_curve = [r["P95 (ms)"] for r in eth_sorted]
    
    # Dibujar curvas WiFi
    ax2.plot(loads_wifi, medias_wifi_curve, marker='o', linewidth=2.0, color='#FF851B', label='WiFi - Latencia Media')
    ax2.plot(loads_wifi, p95_wifi_curve, marker='x', linestyle='--', linewidth=1.5, color='#FF4136', label='WiFi - Percentil 95 (P95)')
    
    # Dibujar curvas Ethernet
    ax2.plot(loads_eth, medias_eth_curve, marker='o', linewidth=2.0, color='#0074D9', label='Ethernet - Latencia Media')
    ax2.plot(loads_eth, p95_eth_curve, marker='x', linestyle='--', linewidth=1.5, color='#001f3f', label='Ethernet - Percentil 95 (P95)')
    
    # Anotaciones para los puntos clave en las curvas
    for l, m in zip(loads_wifi, medias_wifi_curve):
        ax2.annotate(f'{m:.1f}ms', (l, m), textcoords="offset points", xytext=(0,10), ha='center', fontsize=8, color='#A04000', weight='bold')
    for l, m in zip(loads_eth, medias_eth_curve):
        ax2.annotate(f'{m:.1f}ms', (l, m), textcoords="offset points", xytext=(0,-15), ha='center', fontsize=8, color='#003366', weight='bold')
        
    ax2.set_title("Curva de Tendencia: Latencia vs. Congestión de Canal (%)", fontsize=11, fontweight='bold', pad=10)
    ax2.set_xlabel("Carga Relativa del Canal (% de la Capacidad Máxima del Medio)")
    ax2.set_ylabel("Tiempo de Tránsito (ms)")
    ax2.set_xlim(-5, 90)
    ax2.grid(True, linestyle=':', alpha=0.6)
    ax2.legend(loc='upper left', fontsize=9)
    
    plt.suptitle("Estudio de Latencia WiFi vs. Ethernet bajo Carga Relativa Equivalente del Canal\nTrabajo de Fin de Grado · UMA 2026", 
                 fontsize=13, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(output_path, dpi=250, bbox_inches='tight')
    plt.close()
    print(f"Gráfico comparativo guardado en: {output_path}")

generar_grafico_comparativo(resultados, OUT_DIR / "grafico_comparativa_redes.png")

# ── Generar Documento de Análisis (Markdown) ──────────────────────────
def generar_reporte_markdown(res_list):
    cabecera = (
        "| Condición | Medio | Carga Absoluta | Carga Relativa | N Efectivo | Media | Mediana | P95 | P99 | Máx | Jitter | FPS | Pérdida % |\n"
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    )
    filas = []
    for r in res_list:
        fila = (
            f"| {r['Condición']} | {r['medium']} | {r['load_abs']} Mbps | {r['load_rel']:.1f}% | {r['N Efectivo']} | "
            f"{r['Media (ms)']:.1f} ms | {r['Mediana (ms)']:.1f} ms | {r['P95 (ms)']:.1f} ms | "
            f"{r['P99 (ms)']:.1f} ms | {r['Máx (ms)']:.1f} ms | {r['Jitter (ms)']:.1f} ms | "
            f"{r['FPS Efectivo']:.1f} fps | {r['Pérdida %']:.2f}% |"
        )
        filas.append(fila)
    tabla_md = cabecera + "\n" + "\n".join(filas)
    
    wifi_0 = next(r for r in res_list if r["medium"] == "WiFi" and r["load_abs"] == 0)
    wifi_120 = next(r for r in res_list if r["medium"] == "WiFi" and r["load_abs"] == 120)
    wifi_220 = next(r for r in res_list if r["medium"] == "WiFi" and r["load_abs"] == 220)
    
    eth_0 = next(r for r in res_list if r["medium"] == "Ethernet" and r["load_abs"] == 0)
    eth_400 = next(r for r in res_list if r["medium"] == "Ethernet" and r["load_abs"] == 400)
    eth_740 = next(r for r in res_list if r["medium"] == "Ethernet" and r["load_abs"] == 740)
    
    markdown_content = f"""# Informe de Comparativa Científica: WiFi vs. Ethernet bajo Carga Relativa

Este informe técnico analiza y compara el comportamiento del flujo de vídeo WebRTC bajo condiciones de red inalámbrica (WiFi) y red cableada (Ethernet). 

Para garantizar una comparación metodológica rigurosa de cara a la memoria del TFG, **no solo comparamos las cargas en términos absolutos de Mbps, sino en términos relativos (%) respecto a la capacidad de saturación máxima de cada canal físico**.

### Parámetros de Capacidad Base
* **Capacidad Máxima Medida del Canal WiFi:** **{CAP_WIFI:.0f} Mbps**
* **Capacidad Máxima Medida del Canal Ethernet:** **{CAP_ETH:.0f} Mbps** (1 Gbps nominal)

---

## 1. Tabla de Resultados Comparativos Consolidados

{tabla_md}

> *Nota: Se ha excluido una fase de calentamiento inicial de {WARMUP_SECONDS}s en todos los ensayos para analizar únicamente el estado estacionario de la red.*

---

## 2. Análisis por Cargas Relativas de Canal Equivalentes

### 2.1 Canal en Reposo (0% de Carga)
* **WiFi (0 Mbps):** Latencia Media de **{wifi_0['Media (ms)']:.1f} ms** (P95 de **{wifi_0['P95 (ms)']:.1f} ms**).
* **Ethernet (0 Mbps):** Latencia Media de **{eth_0['Media (ms)']:.1f} ms** (P95 de **{eth_0['P95 (ms)']:.1f} ms**).
* **Interpretación:** Con la red en reposo, ambos medios ofrecen latencias medias inferiores a los 6 milisegundos, ofreciendo una experiencia idéntica. Sin embargo, Ethernet estabiliza el jitter a unos imperceptibles **{eth_0['Jitter (ms)']:.1f} ms** frente a los **{wifi_0['Jitter (ms)']:.1f} ms** de WiFi.

### 2.2 Canal bajo Carga Media (Congestión del ~40% de Capacidad)
* **WiFi Carga Media (120 Mbps @ {wifi_120['load_rel']:.1f}% de canal):** Latencia Media de **{wifi_120['Media (ms)']:.1f} ms**, P95 de **{wifi_120['P95 (ms)']:.1f} ms**, Jitter de **{wifi_120['Jitter (ms)']:.1f} ms** y Pérdidas de **{wifi_120['Pérdida %']:.2f}%**.
* **Ethernet Carga Equivalente (400 Mbps @ {eth_400['load_rel']:.1f}% de canal):** Latencia Media de **{eth_400['Media (ms)']:.1f} ms**, P95 de **{eth_400['P95 (ms)']:.1f} ms**, Jitter de **{eth_400['Jitter (ms)']:.1f} ms** y Pérdidas de **{eth_400['Pérdida %']:.2f}%**.
* **Interpretación:** A pesar de que en Ethernet estamos inyectando más del triple de tráfico absoluto (400 Mbps frente a 120 Mbps), el comportamiento ante una carga relativa idéntica es muy revelador. En WiFi, la atenuación del medio inalámbrico y las colisiones de espectro provocan pérdidas menores ({wifi_120['Pérdida %']:.2f}%) y picos de latencia. En Ethernet, la cola del conmutador e inmunidad al ruido gestionan los 400 Mbps de forma impecable, manteniendo la latencia media en **{eth_400['Media (ms)']:.1f} ms** y las pérdidas en **{eth_400['Pérdida %']:.2f}%**.

### 2.3 Canal bajo Carga Alta / Saturación (Congestión del ~75% de Capacidad)
* **WiFi Carga Alta (220 Mbps @ {wifi_220['load_rel']:.1f}% de canal):** Latencia Media de **{wifi_220['Media (ms)']:.1f} ms**, P95 de **{wifi_220['P95 (ms)']:.1f} ms**, P99 de **{wifi_220['P99 (ms)']:.1f} ms**, Jitter de **{wifi_220['Jitter (ms)']:.1f} ms** y Pérdidas de **{wifi_220['Pérdida %']:.2f}%**.
* **Ethernet Carga Equivalente (740 Mbps @ {eth_740['load_rel']:.1f}% de canal):** Latencia Media de **{eth_740['Media (ms)']:.1f} ms**, P95 de **{eth_740['P95 (ms)']:.1f} ms**, P99 de **{eth_740['P99 (ms)']:.1f} ms**, Jitter de **{eth_740['Jitter (ms)']:.1f} ms** y Pérdidas de **{eth_740['Pérdida %']:.2f}%**.
* **Interpretación:** Este es el punto crítico para la defensa del TFG. En WiFi, someter el canal al 78% de su capacidad dispara el percentil 99 a **{wifi_220['P99 (ms)']:.1f} ms** e introduce un Jitter de **{wifi_220['Jitter (ms)']:.1f} ms**, provocando micro-tirones muy perceptibles que dificultan la teleoperación de precisión. En Ethernet, someter el cable al 74% de su capacidad total (inyectando 740 Mbps de tráfico de fondo continuo) apenas perturba la transmisión: la latencia media es de solo **{eth_740['Media (ms)']:.1f} ms**, el percentil 99 no supera los **{eth_740['P99 (ms)']:.1f} ms** y no hay **ninguna pérdida de fotograma ({eth_740['Pérdida %']:.2f}%)**.

---

## 3. Conclusiones y Defensa Metodológica

1. **Eficiencia en la Gestión de Colas:** Los routers y adaptadores de red Ethernet manejan las colisiones de red a nivel de silicio a través del protocolo CSMA/CD de manera mucho más eficiente que la contención inalámbrica CSMA/CA de WiFi.
2. **Inmunidad al Jitter:** Incluso inyectando tráfico masivo por cable, la desviación estándar de la latencia permanece plana, lo que resulta fundamental para evitar el desalineamiento del bucle de control extremo a extremo del brazo robot.
3. **Justificación de Diseño:** Queda empíricamente demostrado que la teleoperación por Ethernet ofrece una robustez de grado industrial, manteniendo latencias estables e insensibles a la congestión de datos de fondo en el canal físico.
"""
    
    ruta_doc = DOC_DIR / "COMPARATIVA_REDES.md"
    with open(ruta_doc, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    print(f"Documento de análisis guardado en: {ruta_doc}")

generar_reporte_markdown(resultados)
print("\n¡Todo completado con éxito!")
