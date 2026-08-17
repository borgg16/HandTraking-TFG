#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 3 — Barrido de rejilla de puntos por UART (Fases P0.3 y P0.3b).

Recorre una rejilla espacial en el plano de trabajo del brazo robot RoArm-M2
sin Unity ni señalización WebRTC. Determina el área alcanzable real y valida
la ausencia de interferencias mecánicas entre el brazo y el soporte de la cámara.

Uso:
    python script_rejilla.py --puerto COM9 --modo-manual
    python script_rejilla.py --puerto COM9 --modo-automatico --pausa-auto 2.0
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

# Configurar rutas para importar módulos compartidos
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

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("script_rejilla")

# --- Límites de seguridad cinemática del robot (cm) ---
X_MIN, X_MAX = 5.0, 40.0     # profundidad / alcance radial
Y_MIN, Y_MAX = -40.0, 40.0   # eje lateral
Z_MIN, Z_MAX = -10.0, 50.0   # eje vertical

T_OPEN   = 0.5  # Pinza abierta en radianes
T_CLOSED = 1.4  # Pinza cerrada en radianes

def clamp(v, vmin, vmax):
    """Restringe un valor numérico al intervalo [vmin, vmax]."""
    return max(vmin, min(vmax, v))

def crear_conexion_serial(puerto, baudrate=115200):
    """
    Abre la conexión serie con el microcontrolador ESP32 del robot.
    Espera 2 segundos para permitir el reinicio de la placa.
    """
    import serial
    try:
        log.info(f"Abriendo puerto serie {puerto} a {baudrate} baudios...")
        ser = serial.Serial(puerto, baudrate, timeout=1)
        time.sleep(2)
        log.info("Conexion serie establecida con exito.")
        return ser
    except serial.SerialException as e:
        log.error(f"Error critico al abrir puerto serial {puerto}: {e}")
        return None

def enviar_comando_serial(ser, data: dict) -> str:
    """Envía un diccionario como cadena JSON + '\\n' por el puerto serie."""
    if ser is None or not ser.is_open:
        return ""
    json_str = json.dumps(data) + '\n'
    ser.write(json_str.encode('utf-8'))
    respuesta = ser.readline().decode('utf-8', errors='ignore').strip()
    return respuesta

def construir_comando_movimiento(x_cm, y_cm, z_cm, t_rad=T_OPEN) -> dict:
    """
    Genera el diccionario de comando de movimiento para el firmware ESP32 (T: 1041).
    Las coordenadas se escalan a décimas de milímetro (* 10) y el ángulo a * 5.
    """
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
    """
    Mueve el robot de p_actual a p_destino mediante interpolación lineal en pequeños pasos
    para evitar movimientos bruscos o a máxima velocidad en el hardware.
    """
    x1, y1, z1 = p_actual
    x2, y2, z2 = p_destino

    distancia = math.sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)
    n_pasos = max(1, int(math.ceil(distancia / paso_cm)))

    for i in range(1, n_pasos + 1):
        alpha = i / float(n_pasos)
        xi = x1 + alpha * (x2 - x1)
        yi = y1 + alpha * (y2 - y1)
        zi = z1 + alpha * (z2 - z1)

        cmd = construir_comando_movimiento(xi, yi, zi, t_rad)
        enviar_comando_serial(ser, cmd)
        time.sleep(pausa_paso)

    return p_destino

def main():
    parser = argparse.ArgumentParser(
        description="Barrido de rejilla de puntos por UART para validacion de area y no-interferencia"
    )
    parser.add_argument("--puerto", type=str, default=DEFAULT_SERIAL_PORT,
                        help=f"Puerto serial del robot (default: {DEFAULT_SERIAL_PORT})")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE,
                        help=f"Velocidad del puerto serial (default: {DEFAULT_BAUDRATE})")
    parser.add_argument("--paso-cm", type=float, default=5.0,
                        help="Resolución de la rejilla en cm (default: 5.0)")
    parser.add_argument("--altura-z", type=float, default=10.0,
                        help="Altura fija Z en cm para el plano de barrido (default: 10.0)")
    parser.add_argument("--x-min", type=float, default=10.0,
                        help="Coordenada X mínima en cm (default: 10.0)")
    parser.add_argument("--x-max", type=float, default=40.0,
                        help="Coordenada X máxima en cm (default: 40.0)")
    parser.add_argument("--y-min", type=float, default=-25.0,
                        help="Coordenada Y mínima en cm (default: -25.0)")
    parser.add_argument("--y-max", type=float, default=25.0,
                        help="Coordenada Y máxima en cm (default: 25.0)")
    parser.add_argument("--subpaso-cm", type=float, default=1.0,
                        help="Tamaño de subpaso para interpolación en cm (default: 1.0)")
    parser.add_argument("--pausa-subpaso", type=float, default=0.04,
                        help="Pausa en segundos entre subpasos de interpolación (default: 0.04)")
    parser.add_argument("--modo-automatico", action="store_true",
                        help="Avanzar automáticamente entre puntos sin requerir confirmación")
    parser.add_argument("--pausa-auto", type=float, default=1.5,
                        help="Pausa en segundos en cada punto si está en modo automático (default: 1.5)")

    args = parser.parse_args()

    # Generación de puntos de la rejilla
    xs = []
    curr_x = args.x_min
    while curr_x <= args.x_max + 1e-5:
        xs.append(round(curr_x, 2))
        curr_x += args.paso_cm

    ys = []
    curr_y = args.y_min
    while curr_y <= args.y_max + 1e-5:
        ys.append(round(curr_y, 2))
        curr_y += args.paso_cm

    puntos = [(x, y, args.altura_z) for x in xs for y in ys]
    total_puntos = len(puntos)
    log.info(f"Rejilla generada: {len(xs)}x en X, {len(ys)}y en Y -> {total_puntos} puntos totales.")

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTADOS_DIR / f"rejilla_{timestamp}.csv"

    ser = crear_conexion_serial(args.puerto, args.baudrate)
    if ser is None:
        log.error("No se pudo iniciar la comunicacion serie. Abortando ejecucion.")
        sys.exit(1)

    # Posición inicial de reposo/seguridad
    pos_actual = (20.0, 0.0, 20.0)
    log.info(f"Moviendo a posicion inicial de seguridad: {pos_actual}")
    mover_interpolado(ser, pos_actual, pos_actual, paso_cm=args.subpaso_cm, pausa_paso=args.pausa_subpaso)

    registros = []

    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f_csv:
            fieldnames = ["x_cm", "y_cm", "z_cm", "alcanzado", "interferencia", "notas"]
            writer = csv.DictWriter(f_csv, fieldnames=fieldnames)
            writer.writeheader()

            for idx, p in enumerate(puntos, 1):
                x_t, y_t, z_t = p
                log.info(f"[{idx}/{total_puntos}] Desplazando hacia punto objetivo: X={x_t:.1f}, Y={y_t:.1f}, Z={z_t:.1f}")

                pos_actual = mover_interpolado(
                    ser, pos_actual, p,
                    paso_cm=args.subpaso_cm,
                    pausa_paso=args.pausa_subpaso
                )

                alcanzado = 1
                interferencia = 0
                notas = ""

                if not args.modo_automatico:
                    resp_alc = input(f" -> Punto ({x_t}, {y_t}, {z_t}). ¿Alcanzado correctamente? [S/n]: ").strip().lower()
                    if resp_alc in ["n", "no", "0"]:
                        alcanzado = 0

                    resp_int = input(" -> ¿Interferencia mecanica con soporte/camara? [s/N]: ").strip().lower()
                    if resp_int in ["s", "si", "sí", "1", "y"]:
                        interferencia = 1

                    notas = input(" -> Notas u observaciones (opcional): ").strip()
                else:
                    time.sleep(args.pausa_auto)

                fila = {
                    "x_cm": x_t,
                    "y_cm": y_t,
                    "z_cm": z_t,
                    "alcanzado": alcanzado,
                    "interferencia": interferencia,
                    "notas": notas
                }
                writer.writerow(fila)
                f_csv.flush()
                registros.append(fila)

        log.info(f"Barrido completado exitosamente. Resultados guardados en: {csv_path}")

    except KeyboardInterrupt:
        log.warning("Barrido interrumpido por el usuario (Ctrl+C).")
    finally:
        # Retorno seguro a posición de reposo
        log.info("Regresando de forma segura a posicion de reposo...")
        try:
            mover_interpolado(ser, pos_actual, (20.0, 0.0, 20.0), paso_cm=args.subpaso_cm, pausa_paso=args.pausa_subpaso)
            ser.close()
            log.info("Puerto serie cerrado correctamente.")
        except Exception as e:
            log.error(f"Error al cerrar la sesion: {e}")

if __name__ == "__main__":
    main()
