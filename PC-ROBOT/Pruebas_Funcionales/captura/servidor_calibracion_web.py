#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
servidor_calibracion_web.py — Servidor Web de Calibración Visual Eye-in-Hand (P0.6).

Abre un servidor web interactivo en http://localhost:5000 para calibrar la cámara
directamente desde el navegador (Chrome/Edge/Firefox) con controles interactivos.
"""

import argparse
import asyncio
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
from aiohttp import web

# Rutas
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
RESULTADOS_DIR = CURRENT_DIR.parent / "resultados"
CONFIG_DIR = PROJECT_ROOT / "Configuracion"

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
    format="%(asctime)s [WebCalib] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("web_calibracion")

# Límites del robot
X_MIN, X_MAX = 5.0, 40.0
Y_MIN, Y_MAX = -40.0, 40.0
Z_MIN, Z_MAX = -10.0, 50.0

T_OPEN   = 0.5   # Pinza abierta
T_CLOSED = 1.4   # Pinza cerrada

CAM_WIDTH, CAM_HEIGHT = 640, 480
CAM_FPS = 30

RETICULO_FRAC_MORDAZAS = 0.50  # 50%
RETICULO_FRAC_MESA     = 0.86  # 86%

# Estado global
robot_ser = None
pos_actual = [20.0, 0.0, 15.0]
pinza_abierta = True
reticulo_activo = True
nombre_postura = "Centro Medio (Z=15 cm)"
ultimo_frame_jpeg = None
cap = None
lock = asyncio.Lock()

POSTURAS = {
    "1": ("Centro Medio (Z=15 cm)", (20.0, 0.0, 15.0)),
    "2": ("Mesa Baja (Z=10 cm)",    (20.0, 0.0, 10.0)),
    "3": ("Reposo Alto (Z=20 cm)",   (20.0, 0.0, 20.0)),
    "4": ("Alcance Frontal",         (30.0, 0.0, 12.0)),
    "5": ("Lateral Izquierdo",       (20.0, -15.0, 12.0)),
    "6": ("Lateral Derecho",         (20.0, 15.0, 12.0)),
}

def clamp(v, vmin, vmax):
    return max(vmin, min(vmax, v))

def crear_conexion_serial(puerto, baudrate=115200):
    import serial
    try:
        log.info(f"Abriendo serial {puerto} @ {baudrate}...")
        ser = serial.Serial(puerto, baudrate, timeout=1)
        time.sleep(2)
        log.info("Serial conectado.")
        return ser
    except Exception as e:
        log.warning(f"Error serial: {e}. Modo sin hardware.")
        return None

def enviar_comando_serial(ser, data: dict):
    if ser is None or not ser.is_open:
        return
    json_str = json.dumps(data) + '\n'
    ser.write(json_str.encode('utf-8'))
    ser.readline()

def mover_a_posicion(ser, p_actual, p_destino, paso_cm=1.0, pausa=0.03, t_rad=T_OPEN):
    if ser is None:
        return list(p_destino)
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

    return list(p_destino)

def procesar_frame(frame, mostrar_reticulo):
    h, w = frame.shape[:2]
    if (w, h) != (CAM_WIDTH, CAM_HEIGHT):
        frame = cv2.resize(frame, (CAM_WIDTH, CAM_HEIGHT))
        h, w = CAM_HEIGHT, CAM_WIDTH

    if mostrar_reticulo:
        VERDE = (0, 255, 0)
        AMARILLO = (0, 255, 255)

        # Cruz central
        cv2.line(frame, (w // 2, 0), (w // 2, h), VERDE, 1)
        cv2.line(frame, (0, h // 2), (w, h // 2), VERDE, 1)
        cv2.circle(frame, (w // 2, h // 2), 5, VERDE, 1)

        # Guía mordazas (50%)
        y_mordazas = int(h * RETICULO_FRAC_MORDAZAS)
        cv2.line(frame, (0, y_mordazas), (w, y_mordazas), AMARILLO, 1)
        cv2.putText(frame, "PUNTAS MORDAZAS (50%)", (10, y_mordazas - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, AMARILLO, 1, cv2.LINE_AA)

        # Guía mesa (86%)
        y_mesa = int(h * RETICULO_FRAC_MESA)
        cv2.line(frame, (0, y_mesa), (w, y_mesa), AMARILLO, 1)
        cv2.putText(frame, "LINEA MESA / BASE (86%)", (10, y_mesa - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, AMARILLO, 1, cv2.LINE_AA)

    return frame

async def hilo_captura_camara(cam_index):
    global ultimo_frame_jpeg, cap, reticulo_activo
    log.info(f"Iniciando captura de cámara {cam_index}...")
    cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(cam_index)

    if not cap.isOpened():
        log.error(f"No se pudo abrir la cámara {cam_index}.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAM_FPS)

    while True:
        ret, frame = cap.read()
        if not ret:
            frame = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
            cv2.putText(frame, "CAMARA NO DISPONIBLE", (50, CAM_HEIGHT // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        frame_overlay = procesar_frame(frame.copy(), reticulo_activo)
        ret, jpeg = cv2.imencode('.jpg', frame_overlay, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            ultimo_frame_jpeg = jpeg.tobytes()

        await asyncio.sleep(0.03)

async def video_feed(request):
    response = web.StreamResponse(
        status=200,
        reason='OK',
        headers={
            'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
            'Cache-Control': 'no-cache',
            'Connection': 'close',
        }
    )
    await response.prepare(request)

    try:
        while True:
            if ultimo_frame_jpeg is not None:
                await response.write(
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + ultimo_frame_jpeg + b'\r\n'
                )
            await asyncio.sleep(0.033)
    except Exception:
        pass
    return response

async def handle_comando(request):
    global pos_actual, pinza_abierta, reticulo_activo, nombre_postura, robot_ser
    data = await request.json()
    accion = data.get("accion")

    if accion == "postura":
        clave = str(data.get("id"))
        if clave in POSTURAS:
            nombre_postura, destino = POSTURAS[clave]
            t_rad = T_OPEN if pinza_abierta else T_CLOSED
            pos_actual = mover_a_posicion(robot_ser, pos_actual, destino, t_rad=t_rad)
            log.info(f"Postura cambiada a: {nombre_postura} -> {pos_actual}")

    elif accion == "pinza":
        pinza_abierta = not pinza_abierta
        t_rad = T_OPEN if pinza_abierta else T_CLOSED
        if robot_ser:
            cmd = {
                "T": 1041,
                "x": int(pos_actual[0] * 10),
                "y": int(pos_actual[1] * 10),
                "z": int(pos_actual[2] * 10),
                "t": round(t_rad * 5, 1)
            }
            enviar_comando_serial(robot_ser, cmd)
        log.info(f"Pinza: {'ABIERTA' if pinza_abierta else 'CERRADA'}")

    elif accion == "reticulo":
        reticulo_activo = not reticulo_activo
        log.info(f"Retículo: {reticulo_activo}")

    elif accion == "foto":
        if ultimo_frame_jpeg is not None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = RESULTADOS_DIR / f"calibracion_web_{ts}.jpg"
            with open(save_path, "wb") as f:
                f.write(ultimo_frame_jpeg)
            log.info(f"Foto guardada en: {save_path}")
            return web.json_response({"status": "ok", "guardado": str(save_path.name)})

    return web.json_response({
        "status": "ok",
        "postura": nombre_postura,
        "x": pos_actual[0], "y": pos_actual[1], "z": pos_actual[2],
        "pinza": "ABIERTA" if pinza_abierta else "CERRADA",
        "reticulo": reticulo_activo
    })

HTML_INDEX = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Panel de Calibración Eye-in-Hand (P0.6)</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, sans-serif; }
        body { background-color: #121214; color: #e1e1e6; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; border-bottom: 1px solid #282830; padding-bottom: 15px; }
        h1 { font-size: 22px; color: #00d2ff; }
        .badge { background: #00e676; color: #121214; font-weight: bold; padding: 4px 10px; border-radius: 20px; font-size: 12px; }
        .grid { display: grid; grid-template-columns: 640px 1fr; gap: 24px; }
        .video-box { background: #000; border-radius: 12px; overflow: hidden; box-shadow: 0 8px 24px rgba(0,0,0,0.6); border: 1px solid #282830; }
        .video-box img { width: 100%; height: 480px; display: block; object-fit: contain; }
        .panel { display: flex; flex-direction: column; gap: 16px; }
        .card { background: #1a1a1e; border: 1px solid #282830; border-radius: 10px; padding: 16px; }
        .card h2 { font-size: 15px; color: #a8a8b3; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 12px; border-bottom: 1px solid #282830; padding-bottom: 6px; }
        .status-row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 14px; }
        .status-val { font-weight: bold; color: #00d2ff; }
        .guide-item { margin-bottom: 10px; font-size: 13px; line-height: 1.4; }
        .guide-item strong { color: #ffd600; }
        .btn-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        button { background: #282832; color: #f0f0f5; border: 1px solid #3e3e4a; border-radius: 8px; padding: 12px 10px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
        button:hover { background: #00d2ff; color: #121214; border-color: #00d2ff; }
        button.action-btn { background: #00e676; color: #121214; border-color: #00e676; }
        button.action-btn:hover { background: #00c853; }
        .toast { position: fixed; bottom: 20px; right: 20px; background: #00e676; color: #121214; font-weight: bold; padding: 12px 20px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); display: none; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🔬 Calibración Visual Eye-in-Hand (Fase P0.6)</h1>
            <span class="badge">EN DIRECTO</span>
        </header>
        
        <div class="grid">
            <div class="video-box">
                <img src="/video_feed" alt="Video Cámara">
            </div>

            <div class="panel">
                <div class="card">
                    <h2>Estado del Robot</h2>
                    <div class="status-row"><span>Postura:</span><span id="st-pos" class="status-val">Centro Medio (Z=15 cm)</span></div>
                    <div class="status-row"><span>Coordenadas:</span><span id="st-coord" class="status-val">X=20.0, Y=0.0, Z=15.0 cm</span></div>
                    <div class="status-row"><span>Pinza:</span><span id="st-pinza" class="status-val">ABIERTA</span></div>
                </div>

                <div class="card">
                    <h2>¿Qué debes comprobar?</h2>
                    <div class="guide-item"><strong>1. Cruz Verde:</strong> Centro óptico exacto del sensor.</div>
                    <div class="guide-item"><strong>2. Línea Amarilla Superior (50%):</strong> Las puntas de las mordazas deben quedar alineadas con esta línea en reposo.</div>
                    <div class="guide-item"><strong>3. Línea Amarilla Inferior (86%):</strong> Debe coincidir con la superficie de la mesa / base de los objetos.</div>
                </div>

                <div class="card">
                    <h2>Posturas de Prueba</h2>
                    <div class="btn-grid">
                        <button onclick="cmd('postura', 1)">[1] Centro (Z=15)</button>
                        <button onclick="cmd('postura', 2)">[2] Mesa (Z=10)</button>
                        <button onclick="cmd('postura', 3)">[3] Reposo (Z=20)</button>
                        <button onclick="cmd('postura', 4)">[4] Frontal (X=30)</button>
                        <button onclick="cmd('postura', 5)">[5] Lateral Izq</button>
                        <button onclick="cmd('postura', 6)">[6] Lateral Der</button>
                        <button class="action-btn" onclick="cmd('pinza', 0)">🔄 Abrir / Cerrar Pinza</button>
                        <button onclick="cmd('reticulo', 0)">👁️ Ocultar / Ver Guías</button>
                        <button class="action-btn" style="grid-column: span 2;" onclick="cmd('foto', 0)">📸 Guardar Foto de Referencia</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div id="toast" class="toast">Foto guardada con éxito</div>

    <script>
        async function cmd(accion, id) {
            try {
                const res = await fetch('/comando', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ accion: accion, id: id })
                });
                const data = await res.json();
                if (data.guardado) {
                    const t = document.getElementById('toast');
                    t.innerText = "📸 Foto guardada: " + data.guardado;
                    t.style.display = 'block';
                    setTimeout(() => t.style.display = 'none', 3000);
                } else if (data.status === "ok") {
                    document.getElementById('st-pos').innerText = data.postura;
                    document.getElementById('st-coord').innerText = `X=${data.x.toFixed(1)}, Y=${data.y.toFixed(1)}, Z=${data.z.toFixed(1)} cm`;
                    document.getElementById('st-pinza').innerText = data.pinza;
                }
            } catch (e) {
                console.error(e);
            }
        }
    </script>
</body>
</html>
"""

async def index(request):
    return web.Response(text=HTML_INDEX, content_type='text/html')

async def main_async():
    global robot_ser, pos_actual
    parser = argparse.ArgumentParser(description="Servidor Web de Calibración Eye-in-Hand")
    parser.add_argument("--puerto", type=str, default="COM9", help="Puerto serie (default: COM9)")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE, help="Baudrate (default: 115200)")
    parser.add_argument("--camera", type=int, default=DEFAULT_CAMERA_INDEX, help="Cámara (default: 0)")
    parser.add_argument("--web-port", type=int, default=5000, help="Puerto web (default: 5000)")
    args = parser.parse_args()

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    robot_ser = crear_conexion_serial(args.puerto, args.baudrate)
    if robot_ser:
        pos_actual = mover_a_posicion(robot_ser, (20.0, 0.0, 20.0), (20.0, 0.0, 15.0), t_rad=T_OPEN)

    # Iniciar tarea de captura de vídeo en segundo plano
    asyncio.create_task(hilo_captura_camara(args.camera))

    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/video_feed', video_feed)
    app.router.add_post('/comando', handle_comando)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', args.web_port)
    await site.start()

    log.info("==================================================================")
    log.info(f" Panel Web de Calibración ACTIVO en: http://localhost:{args.web_port}")
    log.info(" Abre ese enlace en tu navegador (Chrome/Edge/Firefox).")
    log.info("==================================================================")

    try:
        await asyncio.Future() # Correr indefinidamente
    finally:
        if cap:
            cap.release()
        if robot_ser:
            mover_a_posicion(robot_ser, pos_actual, (20.0, 0.0, 20.0), t_rad=T_OPEN)
            robot_ser.close()

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        log.info("Servidor web detenido.")
