#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrar_camara_local.py — Panel de Calibración Visual Eye-in-Hand (Fase P0.6).

Presenta una ventana dividida:
 - Izquierda: Vídeo en directo de la cámara con retículo de alineación.
 - Derecha: Panel de control lateral con estado del robot, criterios de calibración y atajos.
"""

import argparse
import datetime
import json
import logging
import math
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# Rutas y configuración de guardado
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
CONFIG_DIR = PROJECT_ROOT / "Configuracion"

# ==============================================================================
# CARPETA DE SALIDA: Dónde se guardan las fotos y resultados de calibración.
# Puedes cambiar la ruta por defecto aquí o usar el parámetro --output-dir en terminal.
# Ejemplo: CARPETA_SALIDA_DEFECTO = Path(r"C:\Users\franm\Desktop\universidad\TFG\CALIBRACION BRAZO\resultados")
# ==============================================================================
CARPETA_SALIDA_DEFECTO = CURRENT_DIR.parent / "resultados"
RESULTADOS_DIR = CARPETA_SALIDA_DEFECTO

if str(CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR))

try:
    import config as central_config
    DEFAULT_BAUDRATE = getattr(central_config, "DEFAULT_BAUDRATE", 115200)
    DEFAULT_CAMERA_INDEX = getattr(central_config, "DEFAULT_CAMERA_INDEX", 0)
except ImportError:
    DEFAULT_BAUDRATE = 115200
    DEFAULT_CAMERA_INDEX = 0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Calibracion] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("calibracion_local")

# Límites de seguridad del robot (cm)
X_MIN, X_MAX = 5.0, 40.0
Y_MIN, Y_MAX = -40.0, 40.0
Z_MIN, Z_MAX = -10.0, 50.0

T_OPEN   = 0.35   # Pinza abierta (ajustado a 0.35 rad para mayor campo visual)
T_CLOSED = 1.40   # Pinza cerrada

CAM_WIDTH, CAM_HEIGHT = 640, 480
CAM_FPS = 30
PANEL_WIDTH = 380
TOTAL_WIDTH = CAM_WIDTH + PANEL_WIDTH
TOTAL_HEIGHT = CAM_HEIGHT

RETICULO_FRAC_MORDAZAS = 0.50  # 50% de la altura
RETICULO_FRAC_MESA     = 0.86  # 86% de la altura

POSTURAS = {
    ord('1'): ("1: Centro Medio (Z=15 cm)", (20.0, 0.0, 15.0)),
    ord('2'): ("2: Mesa Baja (Z=10 cm)",    (20.0, 0.0, 10.0)),
    ord('3'): ("3: Reposo Alto (Z=20 cm)",   (20.0, 0.0, 20.0)),
    ord('4'): ("4: Alcance Frontal",         (30.0, 0.0, 12.0)),
    ord('5'): ("5: Lateral Izquierdo",       (20.0, -15.0, 12.0)),
    ord('6'): ("6: Lateral Derecho",         (20.0, 15.0, 12.0)),
}

def clamp(v, vmin, vmax):
    return max(vmin, min(vmax, v))

def crear_conexion_serial(puerto, baudrate=115200):
    import serial
    try:
        log.info(f"Conectando al robot en {puerto} a {baudrate} baudios...")
        ser = serial.Serial(puerto, baudrate, timeout=1)
        time.sleep(2)
        log.info("Conexion serie con el robot establecida.")
        return ser
    except Exception as e:
        log.warning(f"No se pudo conectar al puerto serie ({e}). Modo solo camara.")
        return None

def enviar_comando_serial(ser, data: dict):
    if ser is None or not ser.is_open:
        return
    json_str = json.dumps(data) + '\n'
    ser.write(json_str.encode('utf-8'))
    ser.readline()

def mover_a_posicion(ser, p_actual, p_destino, paso_cm=1.0, pausa=0.03, t_rad=T_OPEN):
    if ser is None:
        return p_destino
    x1, y1, z1 = p_actual
    x2, y2, z2 = p_destino

    distancia = math.sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)
    n_pasos = max(1, int(math.ceil(distancia / paso_cm)))

    for i in range(1, n_pasos + 1):
        alpha = i / float(n_pasos)
        xi = x1 + alpha * (x2 - x1)
        yi = y1 + alpha * (y2 - y1)
        zi = z1 + alpha * (z2 - z1)

        cmd = {
            "T": 1041,
            "x": int(clamp(xi, X_MIN, X_MAX) * 10),
            "y": int(clamp(yi, Y_MIN, Y_MAX) * 10),
            "z": int(clamp(zi, Z_MIN, Z_MAX) * 10),
            "t": round(t_rad * 5, 1)
        }
        enviar_comando_serial(ser, cmd)
        time.sleep(pausa)

    return p_destino

def dibujar_reticulo_camara(frame, reticulo_activo):
    h, w = frame.shape[:2]
    VERDE = (0, 255, 0)
    AMARILLO = (0, 255, 255)

    if reticulo_activo:
        # Cruz central
        cv2.line(frame, (w // 2, 0), (w // 2, h), VERDE, 1)
        cv2.line(frame, (0, h // 2), (w, h // 2), VERDE, 1)
        cv2.circle(frame, (w // 2, h // 2), 5, VERDE, 1)

        # Líneas guía horizontales
        y_mordazas = int(h * RETICULO_FRAC_MORDAZAS)
        y_mesa = int(h * RETICULO_FRAC_MESA)

        cv2.line(frame, (0, y_mordazas), (w, y_mordazas), AMARILLO, 1, cv2.LINE_AA)
        cv2.putText(frame, "PUNTAS MORDAZAS (50%)", (10, y_mordazas - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, AMARILLO, 1, cv2.LINE_AA)

        cv2.line(frame, (0, y_mesa), (w, y_mesa), AMARILLO, 1, cv2.LINE_AA)
        cv2.putText(frame, "LINEA MESA / BASE (86%)", (10, y_mesa - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, AMARILLO, 1, cv2.LINE_AA)

    return frame

def construir_panel_lateral(pos_actual, nombre_postura, pinza_abierta, reticulo_activo, fps, t_open=0.35, t_closed=1.40):
    panel = np.zeros((CAM_HEIGHT, PANEL_WIDTH, 3), dtype=np.uint8)
    panel[:] = (26, 26, 26)  # Fondo oscuro elegante

    BLANCO = (240, 240, 240)
    VERDE = (80, 220, 100)
    AMARILLO = (70, 215, 255)
    CIAN = (230, 200, 50)
    MAGENTA = (230, 100, 220)
    GRIS = (140, 140, 140)
    GRIS_CLARO = (190, 190, 190)

    # 1. Cabecera
    cv2.rectangle(panel, (0, 0), (PANEL_WIDTH, 46), (35, 35, 35), -1)
    cv2.putText(panel, "CALIBRACION EYE-IN-HAND", (12, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.50, CIAN, 1, cv2.LINE_AA)
    cv2.putText(panel, "Alineacion visual y rango de vision", (12, 38),
                cv2.FONT_HERSHEY_SIMPLEX, 0.36, GRIS_CLARO, 1, cv2.LINE_AA)
    cv2.line(panel, (0, 46), (PANEL_WIDTH, 46), (60, 60, 60), 1)

    y = 66
    # 2. Estado Actual del Robot
    cv2.putText(panel, "ESTADO DEL ROBOT:", (12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.44, CIAN, 1, cv2.LINE_AA)
    y += 18
    cv2.putText(panel, f"Postura: {nombre_postura}", (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, AMARILLO, 1, cv2.LINE_AA)
    y += 18
    cv2.putText(panel, f"Posicion: X={pos_actual[0]:.1f}, Y={pos_actual[1]:.1f}, Z={pos_actual[2]:.1f} cm", (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, BLANCO, 1, cv2.LINE_AA)
    y += 18
    estado_pinza = f"ABIERTA (t={t_open:.2f} rad)" if pinza_abierta else f"CERRADA (t={t_closed:.2f} rad)"
    color_pinza = VERDE if pinza_abierta else (0, 165, 255)
    cv2.putText(panel, f"Pinza: {estado_pinza}", (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, color_pinza, 1, cv2.LINE_AA)
    y += 18
    ret_txt = "ACTIVO" if reticulo_activo else "OCULTO"
    cv2.putText(panel, f"Reticulo: {ret_txt} | {fps:.0f} FPS", (16, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, GRIS, 1, cv2.LINE_AA)

    # Separador
    y += 10
    cv2.line(panel, (12, y), (PANEL_WIDTH - 12, y), (50, 50, 50), 1)
    y += 16

    # 3. ¿Qué se debe buscar? (Criterios de calibración)
    cv2.putText(panel, "OBJETIVO DE CALIBRACION:", (12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.44, AMARILLO, 1, cv2.LINE_AA)
    y += 16
    criterios = [
        ("1. Cruz verde:", "Centro exacto de la camara"),
        ("2. Guia mordazas (50%):", "Puntas pinza tocan la linea"),
        ("3. Guia mesa (86%):", "Base objetos sobre la mesa"),
        ("4. Apertura visual:", f"[+/-] Ajustar apertura ({t_open:.2f} rad)")
    ]
    for tit, desc in criterios:
        cv2.putText(panel, tit, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.36, VERDE, 1, cv2.LINE_AA)
        y += 13
        cv2.putText(panel, f"   {desc}", (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.34, GRIS_CLARO, 1, cv2.LINE_AA)
        y += 15

    # Separador
    y += 2
    cv2.line(panel, (12, y), (PANEL_WIDTH - 12, y), (50, 50, 50), 1)
    y += 16

    # 4. Teclas y Controles
    cv2.putText(panel, "CONTROLES POR TECLADO:", (12, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.44, CIAN, 1, cv2.LINE_AA)
    y += 16
    controles = [
        ("[1] Centro (Z=15)", "[2] Mesa (Z=10)"),
        ("[3] Reposo (Z=20)", "[4] Frontal (X=30)"),
        ("[5] Lateral Izq",   "[6] Lateral Der"),
        ("[G] Pinza Abr/Cer", "[R] Reticulo ON/OFF"),
        ("[+/-] Apertura t",  "[S/ESPACIO] Foto"),
        ("[Q/ESC] Salir y Reposo", "")
    ]
    for c1, c2 in controles:
        cv2.putText(panel, c1, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, BLANCO, 1, cv2.LINE_AA)
        if c2:
            cv2.putText(panel, c2, (PANEL_WIDTH // 2 + 5, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, BLANCO, 1, cv2.LINE_AA)
        y += 15

    return panel

def main():
    parser = argparse.ArgumentParser(description="Panel de calibración visual Eye-in-Hand")
    parser.add_argument("--puerto", type=str, default="COM9", help="Puerto serie (default: COM9)")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE, help="Baudrate (default: 115200)")
    parser.add_argument("--camera", type=int, default=DEFAULT_CAMERA_INDEX, help="Cámara (default: 0)")
    parser.add_argument("--t-open", type=float, default=T_OPEN, help=f"Ángulo de apertura pinza en rad (default: {T_OPEN})")
    parser.add_argument("--t-closed", type=float, default=T_CLOSED, help=f"Ángulo de cierre pinza en rad (default: {T_CLOSED})")
    parser.add_argument("--output-dir", "--carpeta-salida", type=str, default=str(CARPETA_SALIDA_DEFECTO),
                        help=f"Carpeta donde se guardarán las fotos de calibración (default: {CARPETA_SALIDA_DEFECTO})")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    t_open_actual = args.t_open
    t_closed_actual = args.t_closed

    ser = crear_conexion_serial(args.puerto, args.baudrate)
    pos_actual = (20.0, 0.0, 20.0)
    pinza_abierta = True
    reticulo_activo = True
    nombre_postura = "1: Centro Medio (Z=15 cm)"

    # Mover a postura estándar de calibración
    postura_inicial = (20.0, 0.0, 15.0)
    if ser:
        log.info(f"Colocando robot en postura inicial: {postura_inicial} con t_open={t_open_actual:.2f} rad")
        pos_actual = mover_a_posicion(ser, pos_actual, postura_inicial, t_rad=t_open_actual)

    log.info(f"Abriendo cámara índice {args.camera}...")
    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)

    if not cap.isOpened():
        log.error(f"No se pudo acceder a la cámara {args.camera}.")
        if ser:
            mover_a_posicion(ser, pos_actual, (20.0, 0.0, 20.0), t_rad=t_open_actual)
            ser.close()
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAM_FPS)

    window_name = "Calibracion Eye-in-Hand (P0.6) — Visualizacion y Controles"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, TOTAL_WIDTH, TOTAL_HEIGHT)

    log.info(f"Ventana de calibración lateral abierta (Apertura: {t_open_actual:.2f} rad).")
    prev_time = time.time()
    fps = 30.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                frame = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
                cv2.putText(frame, "CAMARA NO DISPONIBLE", (50, CAM_HEIGHT // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            else:
                if (frame.shape[1], frame.shape[0]) != (CAM_WIDTH, CAM_HEIGHT):
                    frame = cv2.resize(frame, (CAM_WIDTH, CAM_HEIGHT))

            curr_time = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(1e-5, (curr_time - prev_time)))
            prev_time = curr_time

            # 1. Procesar vídeo con retículo
            frame_video = dibujar_reticulo_camara(frame, reticulo_activo)

            # 2. Construir panel lateral con controles y objetivos
            panel_lateral = construir_panel_lateral(
                pos_actual, nombre_postura, pinza_abierta, reticulo_activo, fps,
                t_open=t_open_actual, t_closed=t_closed_actual
            )

            # 3. Concatenar horizontalmente (Vídeo + Panel)
            dashboard = np.hstack([frame_video, panel_lateral])

            cv2.imshow(window_name, dashboard)

            key = cv2.waitKey(1) & 0xFF

            if key in [ord('q'), ord('Q'), 27]: # Salir
                log.info("Cerrando sesión de calibración...")
                break

            elif key in POSTURAS and ser: # Posturas 1-6
                nombre_postura, target_pos = POSTURAS[key]
                t_rad = t_open_actual if pinza_abierta else t_closed_actual
                log.info(f"Moviendo a {nombre_postura}: {target_pos}")
                pos_actual = mover_a_posicion(ser, pos_actual, target_pos, t_rad=t_rad)

            elif key in [ord('g'), ord('G')] and ser: # Pinza
                pinza_abierta = not pinza_abierta
                t_rad = t_open_actual if pinza_abierta else t_closed_actual
                cmd = {
                    "T": 1041,
                    "x": int(pos_actual[0] * 10),
                    "y": int(pos_actual[1] * 10),
                    "z": int(pos_actual[2] * 10),
                    "t": round(t_rad * 5, 1)
                }
                enviar_comando_serial(ser, cmd)
                log.info(f"Pinza: {'ABIERTA' if pinza_abierta else 'CERRADA'} (t={t_rad:.2f} rad)")

            elif key in [ord('+'), ord('=')] and ser: # Abrir más la pinza (bajar t)
                t_open_actual = max(0.20, round(t_open_actual - 0.02, 2))
                if pinza_abierta:
                    cmd = {
                        "T": 1041,
                        "x": int(pos_actual[0] * 10),
                        "y": int(pos_actual[1] * 10),
                        "z": int(pos_actual[2] * 10),
                        "t": round(t_open_actual * 5, 1)
                    }
                    enviar_comando_serial(ser, cmd)
                log.info(f"Apertura pinza ajustada (+ abierta): t_open = {t_open_actual:.2f} rad")

            elif key in [ord('-'), ord('_')] and ser: # Cerrar un poco la apertura (subir t)
                t_open_actual = min(1.0, round(t_open_actual + 0.02, 2))
                if pinza_abierta:
                    cmd = {
                        "T": 1041,
                        "x": int(pos_actual[0] * 10),
                        "y": int(pos_actual[1] * 10),
                        "z": int(pos_actual[2] * 10),
                        "t": round(t_open_actual * 5, 1)
                    }
                    enviar_comando_serial(ser, cmd)
                log.info(f"Apertura pinza ajustada (- abierta): t_open = {t_open_actual:.2f} rad")

            elif key in [ord('r'), ord('R')]: # Retículo
                reticulo_activo = not reticulo_activo

            elif key in [ord('s'), ord('S'), 32]: # Foto
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = output_dir / f"calibracion_dashboard_{ts}.png"
                cv2.imwrite(str(save_path), dashboard)
                log.info(f"Captura del dashboard guardada en: {save_path}")

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if ser:
            log.info("Regresando a posición segura de reposo (20, 0, 20)...")
            mover_a_posicion(ser, pos_actual, (20.0, 0.0, 20.0), t_rad=t_open_actual)
            ser.close()
            log.info("Puerto serie cerrado.")

if __name__ == "__main__":
    main()
