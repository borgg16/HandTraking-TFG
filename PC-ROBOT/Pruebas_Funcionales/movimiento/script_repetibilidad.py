#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 4 — Prueba de Repetibilidad Mecánica sin Operador (Fase P0.7).

Comanda de forma repetida (30 ciclos por defecto) un punto objetivo fijo en el
espacio de trabajo del robot, aproximándose desde 8 direcciones predefinidas
y deterministas para medir la histéresis y repetibilidad mecánica pura del brazo
como línea base para el TFG.

Uso:
    python script_repetibilidad.py --puerto COM9 --n-repeticiones 30
    python script_repetibilidad.py --puerto COM9 --x 25.0 --y 0.0 --z 10.0
"""

import argparse
import csv
import datetime
import json
import logging
import math
import os
import sys
import time
from pathlib import Path

# Configurar rutas
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
CONFIG_DIR = PROJECT_ROOT / "Configuracion"
RESULTADOS_DIR = CURRENT_DIR.parent / "resultados"

if str(CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR))

try:
    import config as central_config
    DEFAULT_BAUDRATE = getattr(central_config, "DEFAULT_BAUDRATE", 115200)
    DEFAULT_SERIAL_PORT = getattr(central_config, "DEFAULT_SERIAL_PORT", "COM9")
except ImportError:
    DEFAULT_BAUDRATE = 115200
    DEFAULT_SERIAL_PORT = "COM9"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("script_repetibilidad")

# --- Límites de seguridad del robot (cm) ---
X_MIN, X_MAX = 5.0, 40.0
Y_MIN, Y_MAX = -40.0, 40.0
Z_MIN, Z_MAX = -10.0, 50.0

T_OPEN   = 0.5
T_CLOSED = 1.4

def clamp(v, vmin, vmax):
    return max(vmin, min(vmax, v))

def crear_conexion_serial(puerto, baudrate=115200):
    import serial
    try:
        log.info(f"Abriendo puerto serie {puerto} a {baudrate} baudios...")
        ser = serial.Serial(puerto, baudrate, timeout=1)
        time.sleep(2)
        log.info("Conexion serie establecida.")
        return ser
    except serial.SerialException as e:
        log.error(f"Error critico al abrir puerto serial {puerto}: {e}")
        return None

def enviar_comando_serial(ser, data: dict) -> str:
    if ser is None or not ser.is_open:
        return ""
    json_str = json.dumps(data) + '\n'
    ser.write(json_str.encode('utf-8'))
    return ser.readline().decode('utf-8', errors='ignore').strip()

def construir_comando(x_cm, y_cm, z_cm, t_rad=T_OPEN) -> dict:
    cx = clamp(x_cm, X_MIN, X_MAX)
    cy = clamp(y_cm, Y_MIN, Y_MAX)
    cz = clamp(z_cm, Z_MIN, Z_MAX)
    return {
        "T": 1041,
        "x": int(cx * 10),
        "y": int(cy * 10),
        "z": int(cz * 10),
        "t": round(t_rad * 5, 1)
    }

def mover_interpolado(ser, p_actual, p_destino, paso_cm=1.0, pausa_paso=0.04, t_rad=T_OPEN):
    x1, y1, z1 = p_actual
    x2, y2, z2 = p_destino

    distancia = math.sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)
    n_pasos = max(1, int(math.ceil(distancia / paso_cm)))

    for i in range(1, n_pasos + 1):
        alpha = i / float(n_pasos)
        xi = x1 + alpha * (x2 - x1)
        yi = y1 + alpha * (y2 - y1)
        zi = z1 + alpha * (z2 - z1)

        cmd = construir_comando(xi, yi, zi, t_rad)
        enviar_comando_serial(ser, cmd)
        time.sleep(pausa_paso)

    return p_destino

# 8 direcciones de aproximación en el plano XY (ángulos en grados)
DIRECCIONES_APROXIMACION = [
    ("NORTE (+X)", 0),
    ("NORESTE (+X, +Y)", 45),
    ("ESTE (+Y)", 90),
    ("SURESTE (-X, +Y)", 135),
    ("SUR (-X)", 180),
    ("SUROESTE (-X, -Y)", 225),
    ("OESTE (-Y)", 270),
    ("NOROESTE (+X, -Y)", 315)
]

def main():
    parser = argparse.ArgumentParser(
        description="Prueba de Repetibilidad Mecánica sin Operador (P0.7)"
    )
    parser.add_argument("--puerto", type=str, default=DEFAULT_SERIAL_PORT,
                        help=f"Puerto serial del robot (default: {DEFAULT_SERIAL_PORT})")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE,
                        help=f"Velocidad del puerto serial (default: {DEFAULT_BAUDRATE})")
    parser.add_argument("--x", type=float, default=25.0,
                        help="Coordenada X objetivo en cm (default: 25.0)")
    parser.add_argument("--y", type=float, default=0.0,
                        help="Coordenada Y objetivo en cm (default: 0.0)")
    parser.add_argument("--z", type=float, default=10.0,
                        help="Coordenada Z objetivo en cm (default: 10.0)")
    parser.add_argument("--n-repeticiones", type=int, default=30,
                        help="Numero total de repeticiones a comandar (default: 30)")
    parser.add_argument("--dist-aprox", type=float, default=5.0,
                        help="Distancia radial en cm para los puntos de aproximación (default: 5.0)")
    parser.add_argument("--subpaso-cm", type=float, default=1.0,
                        help="Tamaño de subpaso para interpolación en cm (default: 1.0)")
    parser.add_argument("--pausa-subpaso", type=float, default=0.04,
                        help="Pausa en segundos entre subpasos de interpolación (default: 0.04)")
    parser.add_argument("--modo-automatico", action="store_true",
                        help="No pausar para confirmación manual de marca física")
    parser.add_argument("--pausa-auto", type=float, default=2.0,
                        help="Pausa en segundos en la diana en modo automático (default: 2.0)")

    args = parser.parse_args()

    p_objetivo = (args.x, args.y, args.z)
    log.info(f"Punto objetivo de prueba fijado en: X={args.x:.1f}, Y={args.y:.1f}, Z={args.z:.1f} cm")
    log.info(f"Total repeticiones programadas: {args.n_repeticiones}")

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTADOS_DIR / f"repetibilidad_p07_{timestamp}.csv"

    ser = crear_conexion_serial(args.puerto, args.baudrate)
    if ser is None:
        log.error("No se pudo conectar con el hardware. Abortando.")
        sys.exit(1)

    pos_actual = (20.0, 0.0, 20.0)
    log.info(f"Moviendo a posicion inicial de seguridad: {pos_actual}")
    mover_interpolado(ser, pos_actual, pos_actual, paso_cm=args.subpaso_cm, pausa_paso=args.pausa_subpaso)

    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f_csv:
            fieldnames = [
                "n_intento", "x_objetivo", "y_objetivo", "z_objetivo",
                "direccion_aproximacion", "timestamp_envio"
            ]
            writer = csv.DictWriter(f_csv, fieldnames=fieldnames)
            writer.writeheader()

            for n in range(1, args.n_repeticiones + 1):
                dir_nombre, angulo_deg = DIRECCIONES_APROXIMACION[(n - 1) % len(DIRECCIONES_APROXIMACION)]
                rad = math.radians(angulo_deg)

                # Calcular punto de aproximación alrededor del objetivo
                x_aprox = args.x + args.dist_aprox * math.cos(rad)
                y_aprox = args.y + args.dist_aprox * math.sin(rad)
                z_aprox = args.z + 2.0  # ligero offset vertical para simular descenso
                p_aprox = (x_aprox, y_aprox, z_aprox)

                log.info(f"--- [Ciclo {n}/{args.n_repeticiones}] Aproximacion: {dir_nombre} ---")

                # 1. Mover al punto de aproximación
                pos_actual = mover_interpolado(
                    ser, pos_actual, p_aprox,
                    paso_cm=args.subpaso_cm,
                    pausa_paso=args.pausa_subpaso
                )
                time.sleep(0.2)

                # 2. Mover al punto objetivo final
                pos_actual = mover_interpolado(
                    ser, pos_actual, p_objetivo,
                    paso_cm=args.subpaso_cm,
                    pausa_paso=args.pausa_subpaso
                )

                t_envio = time.time() * 1000.0

                writer.writerow({
                    "n_intento": n,
                    "x_objetivo": args.x,
                    "y_objetivo": args.y,
                    "z_objetivo": args.z,
                    "direccion_aproximacion": dir_nombre,
                    "timestamp_envio": f"{t_envio:.2f}"
                })
                f_csv.flush()

                if not args.modo_automatico:
                    input(f" -> Diana alcanzada (intento {n}). Marcar fisicamente y pulsar Enter para continuar...")
                else:
                    time.sleep(args.pausa_auto)

        log.info("==========================================================")
        log.info(f" Prueba P0.7 completada ({args.n_repeticiones} repeticiones).")
        log.info(f" Datos registrados en: {csv_path}")
        log.info(" Medir ahora las marcas con calibre/regla para analisis_estadistico_p7.py")
        log.info("==========================================================")

    except KeyboardInterrupt:
        log.warning("Prueba de repetibilidad interrumpida por el operador.")
    finally:
        log.info("Retornando a posicion de reposo...")
        try:
            mover_interpolado(ser, pos_actual, (20.0, 0.0, 20.0), paso_cm=args.subpaso_cm, pausa_paso=args.pausa_subpaso)
            ser.close()
            log.info("Puerto serie cerrado con exito.")
        except Exception as e:
            log.error(f"Error cerrando sesion: {e}")

if __name__ == "__main__":
    main()
