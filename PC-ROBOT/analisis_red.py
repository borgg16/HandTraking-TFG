"""
analisis_red.py  —  Análisis de métricas de red del TFG
Universidad de Málaga · 2026

Instalar dependencias (una sola vez):
    pip install pandas matplotlib

Uso:
    python analisis_red.py red_20260528_101500.csv

Genera:
    informe_20260528_101500.png  (4 gráficas)
    Resumen estadístico impreso en consola
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path


# ── Argumento ─────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print("Uso: python analisis_red.py red_SESION.csv")
    sys.exit(1)

csv_path = sys.argv[1]
sesion   = Path(csv_path).stem.replace("red_", "")

# ── Carpeta de resultados ─────────────────────────────────────────────
CARPETA_RESULTADOS = Path("resultados")
CARPETA_RESULTADOS.mkdir(exist_ok=True)

df = pd.read_csv(csv_path)
t  = range(len(df))          # índice de muestras (cada intervaloMuestra segundos)
etiqueta_x = "Muestra (una cada 5 s)"

# ── Figura (2 × 2) ────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 8), constrained_layout=True)
fig.suptitle(
    f"Métricas de Red — Sesión {sesion}\n"
    f"TFG Control de Brazo Robot · Universidad de Málaga",
    fontsize=13, fontweight="bold"
)
gs = gridspec.GridSpec(2, 2, figure=fig)


# ── 1. RTT con banda de jitter ────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, 0])

ax1.plot(t, df["rtt_ms"], color="#0074D9", linewidth=1.8, label="RTT")
ax1.fill_between(
    t,
    df["rtt_ms"] - df["jitter_ms"],
    df["rtt_ms"] + df["jitter_ms"],
    alpha=0.20, color="#0074D9", label="±Jitter"
)
ax1.axhline(200, color="red",    linestyle="--", linewidth=0.9, label="Umbral 200 ms")
ax1.axhline(50,  color="orange", linestyle=":",  linewidth=0.9, label="Objetivo 50 ms")
ax1.set_title("Latencia RTT y Jitter")
ax1.set_xlabel(etiqueta_x)
ax1.set_ylabel("ms")
ax1.legend(fontsize=8)
ax1.grid(True, alpha=0.30)
ax1.set_ylim(bottom=0)


# ── 2. Tasa de envío de comandos ──────────────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])

ax2.plot(t, df["cmd_hz"], color="#2ECC40", linewidth=1.8)
ax2.axhline(30,  color="orange", linestyle="--", linewidth=0.9, label="Mínimo 30 Hz")
ax2.axhline(60,  color="green",  linestyle=":",  linewidth=0.9, label="Objetivo 60 Hz")
ax2.set_title("Tasa de Envío de Comandos")
ax2.set_xlabel(etiqueta_x)
ax2.set_ylabel("Comandos / s  (Hz)")
ax2.set_ylim(0, max(df["cmd_hz"].max() * 1.15, 100))
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.30)


# ── 3. Pérdida de pings ───────────────────────────────────────────────
ax3 = fig.add_subplot(gs[1, 0])

colores_barra = ["#FF4136" if v > 5 else "#AAAAAA" for v in df["tasa_perdida_pct"]]
ax3.bar(t, df["tasa_perdida_pct"], color=colores_barra, alpha=0.80)
ax3.axhline(5, color="orange", linestyle="--", linewidth=0.9, label="Umbral 5 %")
ax3.set_title("Pérdida de Paquetes")
ax3.set_xlabel(etiqueta_x)
ax3.set_ylabel("%")
ax3.legend(fontsize=8)
ax3.set_ylim(bottom=0)
ax3.grid(True, alpha=0.30, axis="y")


# ── 4. Histograma de RTT ──────────────────────────────────────────────
ax4 = fig.add_subplot(gs[1, 1])

bins = max(10, len(df) // 3)
ax4.hist(df["rtt_ms"], bins=bins, color="#7FDBFF", edgecolor="white", linewidth=0.5)
ax4.axvline(df["rtt_ms"].mean(),   color="#0074D9", linestyle="-",  linewidth=1.5,
            label=f"Media {df['rtt_ms'].mean():.1f} ms")
ax4.axvline(df["rtt_ms"].median(), color="#FF851B", linestyle="--", linewidth=1.2,
            label=f"Mediana {df['rtt_ms'].median():.1f} ms")
ax4.set_title("Distribución de RTT")
ax4.set_xlabel("RTT (ms)")
ax4.set_ylabel("Frecuencia")
ax4.legend(fontsize=8)
ax4.grid(True, alpha=0.30, axis="y")


# ── Guardar ───────────────────────────────────────────────────────────
salida = CARPETA_RESULTADOS / f"informe_{sesion}.png"
plt.savefig(salida, dpi=150, bbox_inches="tight")
print(f"\nGráfica guardada: {salida}")


# ── Resumen estadístico en consola ────────────────────────────────────
print("\n" + "=" * 45)
print(f"  RESUMEN DE RED — Sesión {sesion}")
print("=" * 45)
print(f"  Muestras totales  : {len(df)}")
print()
print(f"  RTT   media       : {df['rtt_ms'].mean():.1f} ms")
print(f"  RTT   mediana     : {df['rtt_ms'].median():.1f} ms")
print(f"  RTT   mínimo      : {df['rtt_ms'].min():.1f} ms")
print(f"  RTT   máximo      : {df['rtt_ms'].max():.1f} ms")
print(f"  RTT   > 200 ms    : {(df['rtt_ms'] > 200).sum()} muestras")
print()
print(f"  Jitter media      : {df['jitter_ms'].mean():.1f} ms")
print(f"  Jitter máximo     : {df['jitter_ms'].max():.1f} ms")
print()
print(f"  Hz    media       : {df['cmd_hz'].mean():.1f} cmd/s")
print(f"  Hz    mínimo      : {df['cmd_hz'].min():.1f} cmd/s")
print()
print(f"  Pérdida media     : {df['tasa_perdida_pct'].mean():.1f} %")
print(f"  Pérdida máxima    : {df['tasa_perdida_pct'].max():.1f} %")
print("=" * 45)