#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 7 — Contador Automático de Correcciones de Trayectoria (Fase M4).

Analiza las trayectorias registradas en los ficheros funcionales CSV y calcula
el número de cambios de signo en la derivada temporal del eje de movimiento dominante,
cuantificando las micro-correcciones de teleoperación realizadas por el operador.

Uso:
    python contador_correcciones.py --csv-funcional resultados/funcional_C1_OP1_xxx.csv --todos
    python contador_correcciones.py --csv-funcional resultados/funcional_C1_OP1_xxx.csv --id-intento 1
"""

import argparse
import csv
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

CURRENT_DIR = Path(__file__).resolve().parent
RESULTADOS_DIR = CURRENT_DIR.parent / "resultados"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("contador_correcciones")

def cargar_datos_funcionales(csv_path: Path) -> List[Dict[str, str]]:
    """Lee el CSV funcional y devuelve la lista de registros."""
    filas = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filas.append(row)
    return filas

def analizar_intento(
    filas_intento: List[Dict[str, str]],
    umbral_derivada: float = 0.05
) -> Optional[Dict[str, Any]]:
    """
    Calcula las correcciones y métricas temporales para un intento individual.
    """
    if len(filas_intento) < 3:
        return None

    # Extraer arrays
    ts = []
    xs = []
    ys = []
    zs = []

    for r in filas_intento:
        try:
            # Usar t_uart_escritura o fallback a t_robot_recepcion
            t_val = r.get("t_uart_escritura") or r.get("t_robot_recepcion")
            if not t_val:
                continue
            t = float(t_val)
            x = float(r["x_cm"])
            y = float(r["y_cm"])
            z = float(r["z_cm"])

            ts.append(t)
            xs.append(x)
            ys.append(y)
            zs.append(z)
        except (ValueError, KeyError):
            continue

    if len(ts) < 3:
        return None

    t_arr = np.array(ts)
    x_arr = np.array(xs)
    y_arr = np.array(ys)
    z_arr = np.array(zs)

    # Ordenar por tiempo
    orden = np.argsort(t_arr)
    t_arr = t_arr[orden]
    x_arr = x_arr[orden]
    y_arr = y_arr[orden]
    z_arr = z_arr[orden]

    # Rango total en cada eje
    rango_x = float(np.max(x_arr) - np.min(x_arr))
    rango_y = float(np.max(y_arr) - np.min(y_arr))
    rango_z = float(np.max(z_arr) - np.min(z_arr))

    rangos = {"X": (rango_x, x_arr), "Y": (rango_y, y_arr), "Z": (rango_z, z_arr)}
    eje_dominante = max(rangos.keys(), key=lambda k: rangos[k][0])
    rango_dominante, pos_dom = rangos[eje_dominante]

    # Calcular derivada numérica respecto al tiempo (en cm/s o unidades/tiempo)
    dt = np.diff(t_arr) / 1000.0  # segundos
    dpos = np.diff(pos_dom)

    # Evitar divisiones por cero
    dt_seguros = np.where(dt <= 0, 1e-4, dt)
    derivada = dpos / dt_seguros

    # Filtrar componentes de ruido por debajo del umbral
    derivada_filtrada = np.where(np.abs(derivada) < umbral_derivada, 0.0, derivada)

    # Contar cambios de signo estrictos
    signos = np.sign(derivada_filtrada)
    # Extraer solo signos no nulos
    signos_no_cero = signos[signos != 0]

    n_correcciones = 0
    if len(signos_no_cero) > 1:
        cambios = np.diff(signos_no_cero)
        # Un cambio de +1 a -1 o viceversa produce abs(diff) == 2
        n_correcciones = int(np.sum(np.abs(cambios) == 2))

    duracion_s = (t_arr[-1] - t_arr[0]) / 1000.0 if t_arr[-1] > t_arr[0] else 0.0

    meta = filas_intento[0]
    return {
        "id_intento": meta.get("id_intento", "1"),
        "id_operador": meta.get("id_operador", "OP"),
        "condicion_red": meta.get("condicion_red", "C1"),
        "eje_dominante": eje_dominante,
        "rango_dominante_cm": round(rango_dominante, 2),
        "n_correcciones": n_correcciones,
        "duracion_s": round(duracion_s, 2),
        "muestras_totales": len(t_arr)
    }

def main():
    parser = argparse.ArgumentParser(
        description="Contador Automático de Correcciones de Trayectoria (Fase M4)"
    )
    parser.add_argument("--csv-funcional", type=str, required=True,
                        help="Ruta al archivo CSV funcional generado durante la sesión")
    parser.add_argument("--id-intento", type=str, default=None,
                        help="ID específico del intento a analizar")
    parser.add_argument("--todos", action="store_true",
                        help="Analizar todos los intentos encontrados en el fichero CSV")
    parser.add_argument("--umbral-derivada", type=float, default=0.05,
                        help="Umbral de velocidad mínima (cm/s) para filtrar ruido de jitter (default: 0.05)")
    parser.add_argument("--salida-csv", type=str, default=None,
                        help="Ruta de salida para el CSV resumen de correcciones")

    args = parser.parse_args()

    csv_path = Path(args.csv_funcional)
    if not csv_path.exists():
        log.error(f"No existe el fichero: {csv_path}")
        sys.exit(1)

    filas = cargar_datos_funcionales(csv_path)
    if not filas:
        log.error(f"El archivo {csv_path} está vacío.")
        sys.exit(1)

    # Agrupar por intento
    intentos: Dict[str, List[Dict[str, str]]] = {}
    for r in filas:
        iid = r.get("id_intento", "1")
        if iid not in intentos:
            intentos[iid] = []
        intentos[iid].append(r)

    if args.id_intento:
        if args.id_intento not in intentos:
            log.error(f"El intento '{args.id_intento}' no está en el fichero. Intentos disponibles: {list(intentos.keys())}")
            sys.exit(1)
        intentos_a_procesar = [args.id_intento]
    else:
        intentos_a_procesar = list(intentos.keys())

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    if args.salida_csv:
        csv_salida = Path(args.salida_csv)
    else:
        csv_salida = RESULTADOS_DIR / "correcciones_m4.csv"

    resultados = []
    for iid in intentos_a_procesar:
        res = analizar_intento(intentos[iid], umbral_derivada=args.umbral_derivada)
        if res:
            res["archivo_origen"] = csv_path.name
            resultados.append(res)
            log.info(f"Intento {iid}: Eje dom={res['eje_dominante']} (Rango={res['rango_dominante_cm']} cm) -> Correcciones={res['n_correcciones']} en {res['duracion_s']} s")

    # Guardar resultados
    existe = csv_salida.exists()
    campos_salida = [
        "archivo_origen", "id_intento", "id_operador", "condicion_red",
        "eje_dominante", "rango_dominante_cm", "n_correcciones",
        "duracion_s", "muestras_totales"
    ]

    with open(csv_salida, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos_salida)
        if not existe:
            writer.writeheader()
        writer.writerows(resultados)

    log.info(f"Procesamiento finalizado. Resultados consolidados en: {csv_salida}")

if __name__ == "__main__":
    main()
