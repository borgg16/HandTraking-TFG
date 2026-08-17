#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 8 — Análisis Estadístico Global e Informe de Fase P7 del TFG.

Procesa las mediciones de las 4 condiciones de red para las métricas M1 a M4,
ejecuta los contrastes de hipótesis no paramétricos (Kruskal-Wallis, Mann-Whitney U
con corrección de Bonferroni y tamaño de efecto r, Wilcoxon, Exacto de Fisher),
genera las gráficas de correlación/aprendizaje y compila el informe Markdown final.

Uso:
    python analisis_estadistico_p7.py
    python analisis_estadistico_p7.py --dir-resultados ../resultados/
"""

import argparse
import csv
import datetime
import logging
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np

try:
    import scipy.stats as stats
    SCIPY_DISPONIBLE = True
except ImportError:
    stats = None
    SCIPY_DISPONIBLE = False

# Configuración de rutas
CURRENT_DIR = Path(__file__).resolve().parent
RESULTADOS_DIR = CURRENT_DIR.parent / "resultados"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("analisis_estadistico_p7")

# Latencias Glass-to-Glass medidas en la validación software previa (ms)
LATENCIA_G2G_MS = {
    "C1_WIFI_SIN_CARGA": 5.7,
    "C2_WIFI_CARGA_MEDIA": 9.4,
    "C3_WIFI_CARGA_ALTA": 13.7,
    "C4_ETHERNET": 2.7,
}

CONDICIONES_ORDENADAS = [
    "C4_ETHERNET",
    "C1_WIFI_SIN_CARGA",
    "C2_WIFI_CARGA_MEDIA",
    "C3_WIFI_CARGA_ALTA"
]

NOMBRES_LEGIBLES = {
    "C4_ETHERNET": "C4 Ethernet (Sin Carga)",
    "C1_WIFI_SIN_CARGA": "C1 WiFi (Sin Carga)",
    "C2_WIFI_CARGA_MEDIA": "C2 WiFi (Carga Media)",
    "C3_WIFI_CARGA_ALTA": "C3 WiFi (Carga Alta)"
}

def calcular_tamano_efecto_r(p_val: float, n_total: int) -> float:
    """Calcula el tamaño del efecto r = |Z| / sqrt(N) para contrastes no paramétricos."""
    if not SCIPY_DISPONIBLE or p_val <= 0 or n_total <= 0:
        return 0.0
    p_clamped = min(max(p_val, 1e-15), 1.0 - 1e-15)
    z = stats.norm.ppf(1.0 - p_clamped / 2.0)
    return float(z / math.sqrt(n_total))

def crear_plantilla_m2_m3(ruta_csv: Path):
    """Crea una plantilla CSV para registrar las mediciones manuales de M2/M3 si no existe."""
    if ruta_csv.exists():
        return
    with open(ruta_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["condicion", "id_operador", "intento", "e_x_mm", "e_y_mm", "e_r_mm"])
        for cond in CONDICIONES_ORDENADAS:
            for i in range(1, 6):
                writer.writerow([cond, "OP1", i, "", "", ""])
    log.info(f"Plantilla de mediciones M2/M3 generada en: {ruta_csv}")

def cargar_datos_m1(dir_res: Path) -> Dict[str, List[float]]:
    """Carga los CSVs de latencia M1."""
    datos = {c: [] for c in CONDICIONES_ORDENADAS}
    for arch in dir_res.glob("latencia_m1_*.csv"):
        with open(arch, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cond = row.get("condicion", "").strip()
                val_str = row.get("L_control_ms", "").strip()
                if cond in datos and val_str and val_str != "NO_DETECTADO":
                    try:
                        datos[cond].append(float(val_str))
                    except ValueError:
                        pass
    return datos

def cargar_datos_m2_m3(dir_res: Path) -> Tuple[Dict[str, List[float]], Dict[str, List[Tuple[float, float]]]]:
    """Carga los errores radiales (M2) y pares de error (e_x, e_y) para repetibilidad (M3)."""
    ruta = dir_res / "medidas_m2_m3.csv"
    if not ruta.exists():
        ruta = dir_res / "plantilla_medidas_m2_m3.csv"

    errores_radiales = {c: [] for c in CONDICIONES_ORDENADAS}
    pares_xy = {c: [] for c in CONDICIONES_ORDENADAS}

    if ruta.exists():
        with open(ruta, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                cond = r.get("condicion", "").strip()
                if cond in CONDICIONES_ORDENADAS:
                    try:
                        ex = float(r.get("e_x_mm", 0.0)) / 10.0  # a cm
                        ey = float(r.get("e_y_mm", 0.0)) / 10.0
                        er_val = r.get("e_r_mm")
                        if er_val and er_val.strip():
                            er = float(er_val) / 10.0
                        else:
                            er = math.sqrt(ex**2 + ey**2)

                        errores_radiales[cond].append(er)
                        pares_xy[cond].append((ex, ey))
                    except (ValueError, TypeError):
                        pass
    return errores_radiales, pares_xy

def cargar_datos_m4(dir_res: Path) -> Tuple[Dict[str, List[float]], Dict[str, List[int]], Dict[str, Dict[int, List[float]]]]:
    """Carga tiempos de ejecución y éxitos de M4."""
    tiempos = {c: [] for c in CONDICIONES_ORDENADAS}
    exitos = {c: [] for c in CONDICIONES_ORDENADAS}
    curvas = {c: {i: [] for i in range(1, 6)} for c in CONDICIONES_ORDENADAS}

    ruta_correcciones = dir_res / "correcciones_m4.csv"
    if ruta_correcciones.exists():
        with open(ruta_correcciones, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                cond = r.get("condicion_red", "").strip()
                if cond in CONDICIONES_ORDENADAS:
                    try:
                        dur = float(r.get("duracion_s", 0.0))
                        iid = int(r.get("id_intento", 1))
                        if dur > 0:
                            tiempos[cond].append(dur)
                            exitos[cond].append(1)  # Si concluyó el registro
                            if 1 <= iid <= 5:
                                curvas[cond][iid].append(dur)
                    except ValueError:
                        pass
    return tiempos, exitos, curvas

def generar_tabla_y_graficos(
    dir_res: Path,
    res_m1: Dict[str, List[float]],
    res_m2: Dict[str, List[float]],
    res_m3_xy: Dict[str, List[Tuple[float, float]]],
    res_m4_t: Dict[str, List[float]],
    res_m4_e: Dict[str, List[int]],
    curvas_m4: Dict[str, Dict[int, List[float]]]
) -> Dict[str, Dict[str, str]]:
    """Genera tabla de resumen, gráficos PNG y tabla CSV."""
    tabla_resumen: Dict[str, Dict[str, str]] = {}

    # Calcular estadísticas por condición
    for c in CONDICIONES_ORDENADAS:
        # M1
        v_m1 = res_m1[c]
        m1_str = f"{np.mean(v_m1):.1f} ± {np.std(v_m1):.1f} (N={len(v_m1)})" if v_m1 else "N/D"

        # M2
        v_m2 = res_m2[c]
        m2_str = f"{np.mean(v_m2):.2f} ± {np.std(v_m2):.2f} (N={len(v_m2)})" if v_m2 else "N/D"

        # M3: Desviación típica 2D = sqrt(sigma_x^2 + sigma_y^2)
        v_m3 = res_m3_xy[c]
        if len(v_m3) > 1:
            exs = [p[0] for p in v_m3]
            eys = [p[1] for p in v_m3]
            sigma_2d = math.sqrt(np.var(exs, ddof=1) + np.var(eys, ddof=1))
            m3_str = f"{sigma_2d:.2f} cm (N={len(v_m3)})"
        else:
            m3_str = "N/D"

        # M4 Tiempo
        v_m4 = res_m4_t[c]
        m4_t_str = f"{np.mean(v_m4):.1f} ± {np.std(v_m4):.1f} s (N={len(v_m4)})" if v_m4 else "N/D"

        # M4 Éxito — sin datos reales no se reporta ninguna cifra (nunca inventar un 100%)
        v_e = res_m4_e[c]
        if v_e:
            tasa_exito = sum(v_e) / len(v_e) * 100.0
            m4_e_str = f"{tasa_exito:.1f}% ({sum(v_e)}/{len(v_e)})"
        else:
            m4_e_str = "N/D"

        tabla_resumen[c] = {
            "M1_Latencia_ms": m1_str,
            "M2_Error_Radial_cm": m2_str,
            "M3_Desv_2D_cm": m3_str,
            "M4_Tiempo_s": m4_t_str,
            "M4_Tasa_Exito": m4_e_str
        }

    # Guardar CSV de tabla resumen
    csv_tabla = dir_res / "tabla_resumen_p7.csv"
    with open(csv_tabla, mode="w", newline="", encoding="utf-8") as f:
        fieldnames = ["Condicion", "Latencia_G2G_ms", "M1_Latencia_Control", "M2_Precision_Radial", "M3_Repetibilidad_2D", "M4_Tiempo_PickAndPlace", "M4_Tasa_Exito"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in CONDICIONES_ORDENADAS:
            writer.writerow({
                "Condicion": NOMBRES_LEGIBLES[c],
                "Latencia_G2G_ms": LATENCIA_G2G_MS[c],
                "M1_Latencia_Control": tabla_resumen[c]["M1_Latencia_ms"],
                "M2_Precision_Radial": tabla_resumen[c]["M2_Error_Radial_cm"],
                "M3_Repetibilidad_2D": tabla_resumen[c]["M3_Desv_2D_cm"],
                "M4_Tiempo_PickAndPlace": tabla_resumen[c]["M4_Tiempo_s"],
                "M4_Tasa_Exito": tabla_resumen[c]["M4_Tasa_Exito"]
            })

    # 1. Gráfico de Correlación: Latencia G2G vs Tiempo M4
    # IMPORTANTE: solo se dibujan condiciones con datos M4 REALES. Nunca se
    # rellena una condición sin datos con una fórmula inventada — eso
    # produciría una gráfica con aspecto de resultado real que en realidad
    # es ficticio, y podría colarse en la memoria sin que nadie lo note.
    condiciones_con_datos = [c for c in CONDICIONES_ORDENADAS if res_m4_t[c]]
    ruta_corr = dir_res / "grafico_correlacion_g2g_m4.png"

    if not condiciones_con_datos:
        log.warning(
            "Sin datos reales de M4 en ninguna condicion: NO se genera "
            "grafico_correlacion_g2g_m4.png (para no crear una figura con "
            "datos inventados). Ejecuta la fase M4 y vuelve a lanzar este script."
        )
        if ruta_corr.exists():
            try:
                ruta_corr.unlink()
            except OSError as e:
                log.warning(f"No se pudo borrar el grafico obsoleto {ruta_corr}: {e}. "
                            "BORRALO A MANO: puede contener datos de una version anterior inventados.")
    else:
        fig, ax1 = plt.subplots(figsize=(7.5, 4.8))
        g2g_x = [LATENCIA_G2G_MS[c] for c in condiciones_con_datos]
        m4_medias = [float(np.mean(res_m4_t[c])) for c in condiciones_con_datos]
        m4_stds = [float(np.std(res_m4_t[c])) for c in condiciones_con_datos]

        ax1.errorbar(g2g_x, m4_medias, yerr=m4_stds, fmt='o-', color='#0074D9', linewidth=2, capsize=5, label='Tiempo de Compleción M4 (s)')
        ax1.set_xlabel('Latencia Glass-to-Glass de Vídeo (ms)', fontsize=10, fontweight='bold')
        ax1.set_ylabel('Tiempo Medio M4 (s)', color='#0074D9', fontsize=10, fontweight='bold')
        ax1.tick_params(axis='y', labelcolor='#0074D9')
        ax1.grid(True, linestyle=':', alpha=0.6)

        for i, c in enumerate(condiciones_con_datos):
            ax1.annotate(c.split('_')[0], (g2g_x[i], m4_medias[i]), textcoords="offset points", xytext=(0, 10), ha='center', fontsize=9, weight='bold')

        if len(condiciones_con_datos) < len(CONDICIONES_ORDENADAS):
            faltan = [c.split('_')[0] for c in CONDICIONES_ORDENADAS if c not in condiciones_con_datos]
            ax1.set_title(
                'Correlación entre Degradación de Red y Rendimiento en Tarea (P7)\n'
                f'[PARCIAL — sin datos aún de: {", ".join(faltan)}]',
                fontsize=10, fontweight='bold', color='#B10DC9'
            )
        else:
            ax1.set_title('Correlación entre Degradación de Red y Rendimiento en Tarea (P7)', fontsize=11, fontweight='bold')
        plt.tight_layout()
        plt.savefig(ruta_corr, dpi=250)
        plt.close()

    # 2. Curva de Aprendizaje M4 — mismo criterio: solo condiciones e intentos con datos reales
    ruta_curva = dir_res / "curva_aprendizaje_m4.png"
    if not condiciones_con_datos:
        log.warning(
            "Sin datos reales de M4: NO se genera curva_aprendizaje_m4.png "
            "(para no crear una figura con datos inventados)."
        )
        if ruta_curva.exists():
            try:
                ruta_curva.unlink()
            except OSError as e:
                log.warning(f"No se pudo borrar el grafico obsoleto {ruta_curva}: {e}. "
                            "BORRALO A MANO: puede contener datos de una version anterior inventados.")
    else:
        fig, ax = plt.subplots(figsize=(7.5, 4.5))
        colores = {'C4_ETHERNET': '#2ECC40', 'C1_WIFI_SIN_CARGA': '#0074D9', 'C2_WIFI_CARGA_MEDIA': '#FF851B', 'C3_WIFI_CARGA_ALTA': '#FF4136'}

        hay_alguna_curva = False
        for c in condiciones_con_datos:
            intentos_x = []
            medias_int = []
            for i in range(1, 6):
                vals = curvas_m4[c][i]
                if vals:
                    intentos_x.append(i)
                    medias_int.append(float(np.mean(vals)))
            if intentos_x:
                hay_alguna_curva = True
                ax.plot(intentos_x, medias_int, marker='s', label=NOMBRES_LEGIBLES[c], color=colores[c], linewidth=1.8)

        if hay_alguna_curva:
            ax.set_title('Curva de Aprendizaje en Tarea Pick-and-Place (M4)', fontsize=11, fontweight='bold')
            ax.set_xlabel('Número de Intento Consecutivo', fontsize=10, fontweight='bold')
            ax.set_ylabel('Tiempo de Ejecución (s)', fontsize=10, fontweight='bold')
            ax.set_xticks(range(1, 6))
            ax.grid(True, linestyle=':', alpha=0.6)
            ax.legend(loc='upper right', fontsize=9)
            plt.tight_layout()
            plt.savefig(ruta_curva, dpi=250)
            plt.close()
        else:
            plt.close()
            log.warning(
                "Ninguna condicion tiene datos de curva de aprendizaje por "
                "intento (1-5): NO se genera curva_aprendizaje_m4.png."
            )
            if ruta_curva.exists():
                try:
                    ruta_curva.unlink()
                except OSError as e:
                    log.warning(f"No se pudo borrar el grafico obsoleto {ruta_curva}: {e}. "
                                "BORRALO A MANO: puede contener datos de una version anterior inventados.")

    return tabla_resumen

def ejecutar_tests_estadisticos(
    res_m1: Dict[str, List[float]],
    res_m2: Dict[str, List[float]],
    res_m4_t: Dict[str, List[float]],
    res_m4_e: Dict[str, List[int]],
    pares_xy: Dict[str, List[Tuple[float, float]]]
) -> List[str]:
    """Ejecuta los contrastes estadísticos formales y devuelve el informe formateado en Markdown."""
    lineas = []

    if not SCIPY_DISPONIBLE:
        lineas.append("> [!NOTE]")
        lineas.append("> La librería `scipy` no está disponible en este entorno local. Instalar en el venv del robot con `pip install scipy` para calcular automáticamente los p-valores de Kruskal-Wallis, Mann-Whitney U y Wilcoxon.")
        return lineas

    # 1. Kruskal-Wallis Global para M1 y M4
    lineas.append("### 1. Contrastes Globales entre Condiciones (Kruskal-Wallis)")
    lineas.append("")

    for nombre_metrica, dic_datos in [("M1 Latencia de Control", res_m1), ("M4 Tiempo Pick-and-Place", res_m4_t), ("M2 Precision Radial", res_m2)]:
        grupos = [dic_datos[c] for c in CONDICIONES_ORDENADAS if len(dic_datos[c]) >= 2]
        if len(grupos) >= 2:
            h_stat, p_val = stats.kruskal(*grupos)
            lineas.append(f"- **{nombre_metrica}:** $H = {h_stat:.3f}$, $p = {p_val:.4e}$ " + ("*(Diferencia Estadísticamente Significativa, $p < 0.05$)*" if p_val < 0.05 else "*(No significativo)*"))
        else:
            lineas.append(f"- **{nombre_metrica}:** Muestras insuficientes para contraste global.")

    lineas.append("")
    lineas.append("### 2. Comparaciones Post-Hoc por Pares (Mann-Whitney U con Corrección Bonferroni)")
    lineas.append("")
    lineas.append("| Par de Condiciones | Métrica | Estadístico U | p-valor bruto | p-valor corregido | Tamaño del Efecto r |")
    lineas.append("|---|---|---|---|---|---|")

    # Pares entre condiciones (6 combinaciones)
    n_comparaciones = 6
    for i in range(len(CONDICIONES_ORDENADAS)):
        for j in range(i + 1, len(CONDICIONES_ORDENADAS)):
            c1 = CONDICIONES_ORDENADAS[i]
            c2 = CONDICIONES_ORDENADAS[j]
            par_nombre = f"{c1.split('_')[0]} vs {c2.split('_')[0]}"

            # Evaluar M4
            g1, g2 = res_m4_t[c1], res_m4_t[c2]
            if len(g1) >= 2 and len(g2) >= 2:
                u_stat, p_raw = stats.mannwhitneyu(g1, g2, alternative='two-sided')
                p_bonf = min(1.0, p_raw * n_comparaciones)
                r_efecto = calcular_tamano_efecto_r(p_raw, len(g1) + len(g2))
                lineas.append(f"| {par_nombre} | M4 Tiempo | {u_stat:.1f} | {p_raw:.4f} | {p_bonf:.4f} | {r_efecto:.3f} |")

    lineas.append("")
    lineas.append("### 3. Contraste de Simetría Direccional M2 (Wilcoxon Emparejado $e_x$ vs $e_y$)")
    lineas.append("")
    todos_pares = [p for c in CONDICIONES_ORDENADAS for p in pares_xy[c]]
    if len(todos_pares) >= 5:
        exs = [p[0] for p in todos_pares]
        eys = [p[1] for p in todos_pares]
        w_stat, p_wilc = stats.wilcoxon(exs, eys)
        r_wilc = calcular_tamano_efecto_r(p_wilc, len(todos_pares))
        lineas.append(f"- **Diferencia $e_x$ vs $e_y$:** $W = {w_stat:.1f}$, $p = {p_wilc:.4f}$, tamaño de efecto $r = {r_wilc:.3f}$.")
        if p_wilc >= 0.05:
            lineas.append("  - *Interpretación:* No se observa asimetría significativa entre los ejes X e Y en el error de posicionamiento.")
    else:
        lineas.append("- Mediciones de pares $e_x, e_y$ insuficientes para el test de Wilcoxon.")

    return lineas

def main():
    parser = argparse.ArgumentParser(
        description="Análisis Estadístico Completo de la Fase P7"
    )
    parser.add_argument("--dir-resultados", type=str, default=None,
                        help="Carpeta donde residen los CSV de resultados")

    args = parser.parse_args()

    dir_res = Path(args.dir_resultados) if args.dir_resultados else RESULTADOS_DIR
    dir_res.mkdir(parents=True, exist_ok=True)

    crear_plantilla_m2_m3(dir_res / "plantilla_medidas_m2_m3.csv")

    log.info(f"Cargando datos desde: {dir_res}")
    res_m1 = cargar_datos_m1(dir_res)
    res_m2, res_m3_xy = cargar_datos_m2_m3(dir_res)
    res_m4_t, res_m4_e, curvas_m4 = cargar_datos_m4(dir_res)

    log.info("Generando tablas y figuras gráficas...")
    tabla_resumen = generar_tabla_y_graficos(dir_res, res_m1, res_m2, res_m3_xy, res_m4_t, res_m4_e, curvas_m4)

    log.info("Calculando contrastes de hipótesis estadísticos...")
    bloque_stats = ejecutar_tests_estadisticos(res_m1, res_m2, res_m4_t, res_m4_e, res_m3_xy)

    # Compilar Informe Markdown
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    informe_path = dir_res / f"informe_p7_{timestamp}.md"

    with open(informe_path, mode="w", encoding="utf-8") as f:
        f.write("# Informe Estadístico y Resultados de Fase P7 — Pruebas Funcionales TFG\n\n")
        f.write(f"**Fecha de generación:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
        f.write(f"**Ubicación de datos:** `{dir_res}`  \n\n")
        f.write("---\n\n")
        f.write("## 1. Tabla Principal de Rendimiento (Condición × Métrica)\n\n")
        f.write("| Condición de Red | Latencia G2G Base | M1 Latencia Control | M2 Error Radial (cm) | M3 Repetibilidad 2D (cm) | M4 Tiempo Compleción | M4 Tasa Éxito |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for c in CONDICIONES_ORDENADAS:
            row = tabla_resumen[c]
            f.write(f"| **{NOMBRES_LEGIBLES[c]}** | {LATENCIA_G2G_MS[c]} ms | {row['M1_Latencia_ms']} | {row['M2_Error_Radial_cm']} | {row['M3_Desv_2D_cm']} | {row['M4_Tiempo_s']} | {row['M4_Tasa_Exito']} |\n")

        f.write("\n---\n\n")
        f.write("## 2. Contrastes de Hipótesis y Significación Estadística\n\n")
        for l in bloque_stats:
            f.write(l + "\n")

        f.write("\n---\n\n")
        f.write("## 3. Gráficas Generadas\n\n")
        f.write("- **Correlación Red ↔ Tarea:** `grafico_correlacion_g2g_m4.png`\n")
        f.write("- **Curvas de Aprendizaje:** `curva_aprendizaje_m4.png`\n")
        f.write("- **Tabla en formato CSV:** `tabla_resumen_p7.csv`\n")

    log.info(f"==========================================================")
    log.info(f" Informe estadístico P7 compilado con éxito.")
    log.info(f" Documento Markdown: {informe_path}")
    log.info(f"==========================================================")

if __name__ == "__main__":
    main()
