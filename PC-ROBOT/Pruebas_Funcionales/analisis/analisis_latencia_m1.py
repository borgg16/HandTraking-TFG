#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 6 — Análisis Automático de Latencia de Control M1 mediante Procesamiento de Vídeo.

Procesa grabaciones de vídeo de alta cadencia para detectar el desfase temporal entre
el inicio del movimiento de la mano del operador y la respuesta física del robot.

Uso:
    python analisis_latencia_m1.py --video prueba1.mp4 --condicion C1_WIFI_SIN_CARGA
    python analisis_latencia_m1.py --carpeta-videos ./videos_c1/ --condicion C1_WIFI_SIN_CARGA
"""

import argparse
import csv
import glob
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

# Configurar directorios
CURRENT_DIR = Path(__file__).resolve().parent
RESULTADOS_DIR = CURRENT_DIR.parent / "resultados"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("analisis_latencia_m1")

def parsear_roi(roi_str: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    """Convierte una cadena 'x,y,w,h' a una tupla de enteros."""
    if not roi_str:
        return None
    partes = [int(p.strip()) for p in roi_str.split(",")]
    if len(partes) != 4:
        raise ValueError("El ROI debe tener el formato x,y,w,h")
    return (partes[0], partes[1], partes[2], partes[3])

def seleccionar_roi_interactivo(video_path: Path, nombre_roi: str) -> Tuple[int, int, int, int]:
    """Abre el primer fotograma del vídeo con cv2.selectROI para que el usuario seleccione la región."""
    cap = cv2.VideoCapture(str(video_path))
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise RuntimeError(f"No se pudo leer el primer frame del video: {video_path}")

    log.info(f"Selecciona con el ratón la ROI de [{nombre_roi}] y pulsa ENTER o ESPACIO (C para cancelar)...")
    r = cv2.selectROI(f"Seleccion ROI - {nombre_roi}", frame, fromCenter=False, showCrosshair=True)
    cv2.destroyAllWindows()
    log.info(f"ROI seleccionada para [{nombre_roi}]: x={r[0]}, y={r[1]}, w={r[2]}, h={r[3]}")
    return (int(r[0]), int(r[1]), int(r[2]), int(r[3]))

def detectar_inicio_movimiento(
    video_path: Path,
    roi: Tuple[int, int, int, int],
    umbral: float = 15.0,
    frames_sostenidos: int = 3
) -> Optional[int]:
    """
    Analiza la ROI en escala de grises y localiza el primer fotograma donde la diferencia
    absoluta consecutiva media supera el umbral durante frames_sostenidos consecutivos.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.error(f"No se pudo abrir el archivo de video: {video_path}")
        return None

    x, y, w, h = roi
    ret, frame_prev = cap.read()
    if not ret or frame_prev is None:
        cap.release()
        return None

    gray_prev = cv2.cvtColor(frame_prev[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)

    frame_idx = 1
    candidato_inicio = None
    consecutivos = 0

    while True:
        ret, frame_curr = cap.read()
        if not ret or frame_curr is None:
            break

        gray_curr = cv2.cvtColor(frame_curr[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray_curr, gray_prev)
        score = float(np.mean(diff))

        if score >= umbral:
            if consecutivos == 0:
                candidato_inicio = frame_idx
            consecutivos += 1
            if consecutivos >= frames_sostenidos:
                cap.release()
                return candidato_inicio
        else:
            consecutivos = 0
            candidato_inicio = None

        gray_prev = gray_curr
        frame_idx += 1

    cap.release()
    return None

def procesar_video(
    video_path: Path,
    roi_mano: Tuple[int, int, int, int],
    roi_robot: Tuple[int, int, int, int],
    umbral: float = 15.0,
    frames_sostenidos: int = 3,
    fps_override: Optional[float] = None
) -> dict:
    """Procesa un único vídeo y calcula la latencia de control M1."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    if fps_override and fps_override > 0:
        fps = fps_override
    elif fps <= 0 or np.isnan(fps):
        fps = 30.0  # Fallback estándar

    f_mano = detectar_inicio_movimiento(video_path, roi_mano, umbral, frames_sostenidos)
    f_robot = detectar_inicio_movimiento(video_path, roi_robot, umbral, frames_sostenidos)

    if f_mano is not None and f_robot is not None:
        latencia_ms = round(((f_robot - f_mano) / fps) * 1000.0, 2)
        f_mano_str = str(f_mano)
        f_robot_str = str(f_robot)
        latencia_str = str(latencia_ms)
    else:
        f_mano_str = str(f_mano) if f_mano is not None else "NO_DETECTADO"
        f_robot_str = str(f_robot) if f_robot is not None else "NO_DETECTADO"
        latencia_str = "NO_DETECTADO"

    return {
        "video": video_path.name,
        "f_mano": f_mano_str,
        "f_robot": f_robot_str,
        "fps": f"{fps:.2f}",
        "L_control_ms": latencia_str
    }

def main():
    parser = argparse.ArgumentParser(
        description="Análisis Automático de Latencia de Control M1 por Visión"
    )
    parser.add_argument("--video", type=str, default=None,
                        help="Ruta a un archivo de video específico")
    parser.add_argument("--carpeta-videos", type=str, default=None,
                        help="Carpeta que contiene videos para procesamiento por lotes")
    parser.add_argument("--condicion", type=str, default="C1_WIFI_SIN_CARGA",
                        help="Nombre de la condición de red evaluada (default: C1_WIFI_SIN_CARGA)")
    parser.add_argument("--roi-mano", type=str, default=None,
                        help="Coordenadas de la ROI de la mano: 'x,y,w,h'")
    parser.add_argument("--roi-robot", type=str, default=None,
                        help="Coordenadas de la ROI del robot: 'x,y,w,h'")
    parser.add_argument("--umbral-movimiento", type=float, default=15.0,
                        help="Umbral de diferencia media de intensidad (default: 15.0)")
    parser.add_argument("--frames-sostenidos", type=int, default=3,
                        help="Fotogramas consecutivos sobre el umbral para validar (default: 3)")
    parser.add_argument("--fps", type=float, default=None,
                        help="Tasa de FPS manual para el cálculo de tiempo")
    parser.add_argument("--salida-csv", type=str, default=None,
                        help="Ruta personalizada del fichero CSV de salida")

    args = parser.parse_args()

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    lista_videos: List[Path] = []
    if args.video:
        v_path = Path(args.video)
        if v_path.exists():
            lista_videos.append(v_path)
        else:
            log.error(f"El fichero indicado no existe: {args.video}")
            sys.exit(1)
    elif args.carpeta_videos:
        c_path = Path(args.carpeta_videos)
        for ext in ["*.mp4", "*.avi", "*.mkv", "*.mov", "*.MP4", "*.AVI"]:
            lista_videos.extend(c_path.glob(ext))
        lista_videos = sorted(lista_videos)
        if not lista_videos:
            log.error(f"No se encontraron videos en la carpeta: {args.carpeta_videos}")
            sys.exit(1)
    else:
        log.error("Debe especificar --video o --carpeta-videos.")
        sys.exit(1)

    # Determinar ROIs
    roi_mano = parsear_roi(args.roi_mano)
    roi_robot = parsear_roi(args.roi_robot)

    if roi_mano is None:
        roi_mano = seleccionar_roi_interactivo(lista_videos[0], "MANO DEL OPERADOR")
    if roi_robot is None:
        roi_robot = seleccionar_roi_interactivo(lista_videos[0], "EFECTOR ROBOT")

    # CSV de salida
    if args.salida_csv:
        csv_salida = Path(args.salida_csv)
    else:
        csv_salida = RESULTADOS_DIR / f"latencia_m1_{args.condicion}.csv"

    log.info(f"Iniciando analisis de {len(lista_videos)} videos. Salida en: {csv_salida}")

    resultados = []
    for v in lista_videos:
        log.info(f"Procesando: {v.name}...")
        res = procesar_video(
            v, roi_mano, roi_robot,
            umbral=args.umbral_movimiento,
            frames_sostenidos=args.frames_sostenidos,
            fps_override=args.fps
        )
        res["condicion"] = args.condicion
        resultados.append(res)
        log.info(f" -> Resultado {v.name}: f_mano={res['f_mano']}, f_robot={res['f_robot']}, L_control={res['L_control_ms']} ms")

    # Escribir CSV
    with open(csv_salida, mode="w", newline="", encoding="utf-8") as f:
        fieldnames = ["video", "f_mano", "f_robot", "fps", "L_control_ms", "condicion"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(resultados)

    log.info(f"Analisis M1 finalizado. Guardado en {csv_salida}")

if __name__ == "__main__":
    main()
