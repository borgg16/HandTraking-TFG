#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 6 — Análisis Automático de Latencia de Control M1 mediante Procesamiento de Vídeo (240 FPS).

Diseñado específicamente para grabaciones de cámara lenta a 240 FPS (High Speed Recording).
Calcula el retardo temporal exacto entre el inicio del movimiento de la mano del operador
y el inicio de la respuesta física del brazo robótico (Métrica M1).

Uso:
    python PC-ROBOT/Pruebas_Funcionales/analisis/analisis_latencia_m1.py --video PC-ROBOT/Pruebas_Funcionales/grabaciones_m1/video_M1_C1_ETHERNET_SIN_CARGA.mp4 --condicion C1_ETHERNET_SIN_CARGA
    python PC-ROBOT/Pruebas_Funcionales/analisis/analisis_latencia_m1.py --carpeta-videos PC-ROBOT/Pruebas_Funcionales/grabaciones_m1/

Nota: el proyecto usa siempre Ethernet + Clumsy (nunca Wi-Fi real) para las condiciones C1-C4, por
motivos de reproducibilidad. Nombra los vídeos con "C1"/"C2"/"C3"/"C4" en el nombre de archivo para
que el script asigne automáticamente la condición Ethernet+Clumsy correspondiente.
"""

import argparse
import csv
import glob
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# Configurar directorios
CURRENT_DIR = Path(__file__).resolve().parent
RESULTADOS_DIR = CURRENT_DIR.parent / "resultados" / "M1" / "latencias_resultados"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("analisis_latencia_m1_240fps")

def parsear_roi(roi_str: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    """Convierte una cadena 'x,y,w,h' a una tupla de enteros."""
    if not roi_str:
        return None
    partes = [int(p.strip()) for p in roi_str.split(",")]
    if len(partes) != 4:
        raise ValueError("El ROI debe tener el formato x,y,w,h")
    return (partes[0], partes[1], partes[2], partes[3])

def seleccionar_roi_interactivo(video_path: Path, nombre_roi: str) -> Optional[Tuple[int, int, int, int]]:
    """Abre el primer fotograma del vídeo con cv2.selectROI para que el usuario seleccione la región."""
    cap = cv2.VideoCapture(str(video_path))
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        log.warning(f"No se pudo leer el primer frame de {video_path}")
        return None

    try:
        h, w = frame.shape[:2]
        max_h, max_w = 850, 1280
        scale = min(max_w / w, max_h / h, 1.0)

        if scale < 1.0:
            new_w, new_h = int(w * scale), int(h * scale)
            display_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            display_frame = frame

        window_name = f"Seleccion ROI - {nombre_roi} (240 FPS)"
        log.info(f"Selecciona con el ratón la ROI de [{nombre_roi}] y pulsa ENTER o ESPACIO (C o ESC para omitir)...")
        r = cv2.selectROI(window_name, display_frame, fromCenter=False, showCrosshair=True)
        cv2.destroyAllWindows()
        if r[2] > 0 and r[3] > 0:
            rx = int(round(r[0] / scale))
            ry = int(round(r[1] / scale))
            rw = int(round(r[2] / scale))
            rh = int(round(r[3] / scale))
            rx = max(0, min(rx, w - 1))
            ry = max(0, min(ry, h - 1))
            rw = min(rw, w - rx)
            rh = min(rh, h - ry)
            log.info(f"ROI seleccionada para [{nombre_roi}] (ajustada a resolucion original): x={rx}, y={ry}, w={rw}, h={rh}")
            return (rx, ry, rw, rh)
    except Exception as e:
        log.warning(f"Interacción gráfica no disponible ({e}). Usando partición automática.")
    return None

def detectar_inicio_movimiento_240fps(
    video_path: Path,
    roi: Optional[Tuple[int, int, int, int]] = None,
    lado_defecto: str = "izquierda",
    sensibilidad_sigma: float = 5.0,
    slack_k: float = 0.5,
    ventana_suavizado: int = 5
) -> Optional[int]:
    """
    Detecta el fotograma de inicio de movimiento adaptado a cámaras de 240 FPS, mediante CUSUM
    (suma acumulada de control) sobre la velocidad fotograma-a-fotograma.

    Un gesto humano, aunque se sienta "brusco" al hacerlo, nunca es un salto de posición: el brazo
    acelera y decelera de forma continua a lo largo de ~150-300 ms (biomecánica normal), así que a
    240 FPS la señal de actividad no da un escalón limpio, da una rampa suave. Un umbral fijo sobre
    la diferencia acumulada respecto al primer fotograma (método anterior) es muy sensible a dónde
    se ponga exactamente ese umbral cuando la señal es una rampa, y puede desplazar el "inicio"
    detectado decenas de fotogramas de un lado a otro sin que cambie casi nada en el vídeo real.

    Este método corrige eso de dos formas:
    1. Mide la velocidad fotograma-a-fotograma (diferencia entre fotogramas consecutivos), no la
       diferencia acumulada contra el fotograma 0, así que no arrastra deriva de todo lo que ya se
       ha movido antes, solo lo que se está moviendo ahora mismo.
    2. Usa CUSUM, un método estándar de control de procesos para detectar el inicio de un cambio
       sostenido en una señal ruidosa: acumula evidencia de que la señal está por encima del ruido
       de fondo (con un margen de tolerancia "slack" para no disparar con el ruido normal) y solo
       marca el inicio cuando esa evidencia acumulada supera un umbral de decisión. Es más robusto
       que un umbral instantáneo frente a señales que suben poco a poco en vez de dar un salto.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        log.error(f"No se pudo abrir el archivo de video: {video_path}")
        return None

    frames_gray = []
    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frames_gray.append(gray)
    cap.release()

    if not frames_gray:
        return None

    h, w = frames_gray[0].shape

    if roi is not None and roi[2] > 0 and roi[3] > 0:
        rx, ry, rw, rh = roi
        # Asegurar límites dentro del frame
        rx, ry = max(0, rx), max(0, ry)
        rw = min(rw, w - rx)
        rh = min(rh, h - ry)
        cropped_frames = [f[ry:ry+rh, rx:rx+rw] for f in frames_gray]
    else:
        # Fallback espacial automático: mitad izquierda (mano/operador) o mitad derecha (robot).
        # ADVERTENCIA: esta partición incluye fondo, mesa y otros objetos que no son lo que se
        # quiere medir, y añade ruido real a la detección. Usar --roi-mano/--roi-robot o
        # --interactivo siempre que sea posible; este fallback es solo para pruebas rápidas.
        log.warning(
            f"No se especificó ROI para el lado '{lado_defecto}': usando la partición automática "
            "de media pantalla (incluye fondo). Esto puede introducir ruido y variar bastante el "
            "resultado. Usa --interactivo o --roi-mano/--roi-robot para una medida fiable."
        )
        if lado_defecto == "izquierda":
            cropped_frames = [f[:, :w//2] for f in frames_gray]
        else:
            cropped_frames = [f[:, w//2:] for f in frames_gray]

    n_frames = len(cropped_frames)
    if n_frames < 25:
        return None

    # Velocidad fotograma-a-fotograma: diferencia contra el fotograma ANTERIOR, no contra el 0.
    velocidad = np.array([
        float(np.mean(cv2.absdiff(cropped_frames[i], cropped_frames[i - 1])))
        for i in range(1, n_frames)
    ])

    # Suavizado por media móvil para reducir ruido de compresión/exposición fotograma a fotograma
    if ventana_suavizado > 1 and len(velocidad) >= ventana_suavizado:
        kernel = np.ones(ventana_suavizado) / ventana_suavizado
        velocidad_suave = np.convolve(velocidad, kernel, mode="same")
    else:
        velocidad_suave = velocidad

    # Estadísticas de reposo (primeros 20 fotogramas = ~83 ms) sobre la velocidad, no sobre la
    # diferencia acumulada
    n_base = min(20, len(velocidad_suave) // 4)
    base_media = float(np.mean(velocidad_suave[:n_base]))
    base_std = float(np.std(velocidad_suave[:n_base]))
    base_std = max(base_std, 0.05)
    slack = slack_k * base_std
    umbral_decision = sensibilidad_sigma * base_std

    # CUSUM: acumula (velocidad - media_reposo - margen_slack) mientras sea positivo, se resetea a
    # 0 si la señal vuelve al ruido de fondo. Dispara en el primer fotograma donde la suma
    # acumulada supera el umbral de decisión.
    S = 0.0
    for i in range(1, len(velocidad_suave)):
        S = max(0.0, S + (velocidad_suave[i] - base_media - slack))
        if i >= n_base and S > umbral_decision:
            # +1 porque velocidad[i] compara cropped_frames[i+1] contra cropped_frames[i]
            return i + 1

    return None

def procesar_video_240fps(
    video_path: Path,
    roi_mano: Optional[Tuple[int, int, int, int]] = None,
    roi_robot: Optional[Tuple[int, int, int, int]] = None,
    fps_override: Optional[float] = None
) -> Dict[str, str]:
    """Procesa un vídeo de alta cadencia (240 FPS) y calcula la latencia de control M1."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    if fps_override and fps_override > 0:
        fps = fps_override
    elif fps <= 0 or np.isnan(fps):
        fps = 240.32  # Fallback a 240 FPS

    f_mano = detectar_inicio_movimiento_240fps(video_path, roi_mano, lado_defecto="izquierda")
    f_robot = detectar_inicio_movimiento_240fps(video_path, roi_robot, lado_defecto="derecha")

    if f_mano is not None and f_robot is not None:
        diff_frames = f_robot - f_mano
        latencia_ms = round((diff_frames / fps) * 1000.0, 2)
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
        description="Análisis Automático de Latencia de Control M1 para Grabaciones a 240 FPS"
    )
    parser.add_argument("--video", type=str, default=None,
                        help="Ruta a un archivo de vídeo MP4 individual")
    parser.add_argument("--carpeta-videos", type=str, default=None,
                        help="Carpeta que contiene los vídeos a procesar")
    parser.add_argument("--condicion", type=str, default="C1_ETHERNET_SIN_CARGA",
                        help="Condición de red evaluada (ej: C1_ETHERNET_SIN_CARGA, C2_ETHERNET_CLUMSY_CARGA_MEDIA, C3_ETHERNET_CLUMSY_CARGA_ALTA)")
    parser.add_argument("--roi-mano", type=str, default=None,
                        help="Coordenadas manuales ROI mano: 'x,y,w,h'")
    parser.add_argument("--roi-robot", type=str, default=None,
                        help="Coordenadas manuales ROI robot: 'x,y,w,h'")
    parser.add_argument("--interactivo", action="store_true", default=False,
                        help="Forzar ventana interactiva de selección de ROI con ratón")
    parser.add_argument("--fps", type=float, default=None,
                        help="Tasa de FPS manual (default: extraído del vídeo, ~240.32)")
    parser.add_argument("--salida-csv", type=str, default=None,
                        help="Carpeta personalizada donde guardar los CSV de salida (por defecto: "
                             "resultados/M1/latencias_resultados/)")

    args = parser.parse_args()

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    lista_videos: List[Path] = []
    if args.video:
        v_path = Path(args.video)
        if v_path.exists():
            lista_videos.append(v_path)
        else:
            log.error(f"El vídeo no existe: {args.video}")
            sys.exit(1)
    elif args.carpeta_videos:
        c_path = Path(args.carpeta_videos)
        for ext in ["*.mp4", "*.avi", "*.mkv", "*.mov"]:
            lista_videos.extend(c_path.glob(ext))
        lista_videos = sorted(list(set(lista_videos)))
        if not lista_videos:
            log.error(f"No se encontraron vídeos en: {args.carpeta_videos}")
            sys.exit(1)
    else:
        # Por defecto procesar todos los vídeos en grabaciones_m1
        c_path = CURRENT_DIR.parent / "grabaciones_m1"
        if c_path.exists():
            for ext in ["*.mp4", "*.avi", "*.mkv", "*.mov"]:
                lista_videos.extend(c_path.glob(ext))
            lista_videos = sorted(list(set(lista_videos)))

    if not lista_videos:
        log.error("No hay vídeos para procesar. Especifica --video o --carpeta-videos.")
        sys.exit(1)

    # Determinar ROIs
    roi_mano = parsear_roi(args.roi_mano)
    roi_robot = parsear_roi(args.roi_robot)

    if args.interactivo:
        if roi_mano is None:
            roi_mano = seleccionar_roi_interactivo(lista_videos[0], "MANO DEL OPERADOR")
        if roi_robot is None:
            roi_robot = seleccionar_roi_interactivo(lista_videos[0], "EFECTOR ROBOT")

    resultados = []
    for v in lista_videos:
        cond = args.condicion
        if "C1" in v.name:
            cond = "C1_ETHERNET_SIN_CARGA"
        elif "C2" in v.name:
            cond = "C2_ETHERNET_CLUMSY_CARGA_MEDIA"
        elif "C3" in v.name:
            cond = "C3_ETHERNET_CLUMSY_CARGA_ALTA"
        elif "C4" in v.name:
            cond = "C4_ETHERNET_CLUMSY_EXTRA"

        log.info(f"Analizando a 240 FPS: {v.name} ({cond})...")
        res = procesar_video_240fps(v, roi_mano, roi_robot, fps_override=args.fps)
        res["condicion"] = cond
        resultados.append(res)
        log.info(f" -> {v.name}: f_mano={res['f_mano']}, f_robot={res['f_robot']}, L_control={res['L_control_ms']} ms ({res['fps']} FPS)")

        # Guardar CSV individual (respeta --salida-csv si se indica una carpeta de salida distinta)
        destino_dir = Path(args.salida_csv) if args.salida_csv else RESULTADOS_DIR
        destino_dir.mkdir(parents=True, exist_ok=True)
        csv_indiv = destino_dir / f"latencia_m1_{cond}.csv"
        with open(csv_indiv, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["video", "f_mano", "f_robot", "fps", "L_control_ms", "condicion"])
            writer.writeheader()
            writer.writerow(res)

    # Guardar tabla resumen consolidada (misma carpeta de destino que los CSV individuales)
    destino_dir = Path(args.salida_csv) if args.salida_csv else RESULTADOS_DIR
    csv_resumen = destino_dir / "tabla_resumen_latencia_m1.csv"
    with open(csv_resumen, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["video", "f_mano", "f_robot", "fps", "L_control_ms", "condicion"])
        writer.writeheader()
        writer.writerows(resultados)

    log.info(f"Análisis M1 a 240 FPS finalizado con éxito.")
    log.info(f"Resultados guardados en: {RESULTADOS_DIR}")

if __name__ == "__main__":
    main()
