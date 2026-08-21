import asyncio
import fractions
import json
import logging
import math
import os
import re
import time
import argparse
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import serial
import websockets
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Configuracion")))
import config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from Pruebas_Funcionales.registro.csv_funcional import RegistradorFuncional
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription
)
from aiortc.mediastreams import MediaStreamTrack
from aiortc.sdp import candidate_from_sdp
from av import VideoFrame

# ===================== CONFIGURACIÓN =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Robot] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

TRACE_ENABLED = False # Activa para ver cada JSON enviado/recibido por consola

# Reconexión automática del WebSocket de señalización (problema 5.7):
# backoff exponencial entre intentos: 1s, 2s, 4s... con este tope máximo
BACKOFF_INICIAL_S = 1.0
BACKOFF_MAXIMO_S = 30.0

# Límites de seguridad para el brazo (en cm)
X_MIN, X_MAX = 5.0, 40.0
Y_MIN, Y_MAX = -40.0, 40.0
Z_MIN, Z_MAX = -10.0, 50.0

# Configuración de la pinza (ángulo t)
T_OPEN   = 0.5     # pinza completamente abierta
T_CLOSED = 1.4     # pinza cerrada (aprox. 80°)

# Resolución y FPS de la cámara del brazo que se transmite a Unity.
# Por defecto 640x480 (4:3): es el formato con el que se han realizado el resto
# de pruebas de vídeo del TFG (glass-to-glass, análisis de red), así los
# resultados de las pruebas funcionales son comparables con los ya medidos.
# El modo 16:9 (captura nativa 1280x720 -> salida 640x360 reescalada, para
# aprovechar el FOV completo del sensor) queda disponible pero DESACTIVADO por
# defecto; se activa con la variable de entorno MODO_16_9=1
# (ver Pruebas_Funcionales/captura/captura_16_9.py).
MODO_16_9 = os.environ.get("MODO_16_9", "0") == "1"

if MODO_16_9:
    CAM_WIDTH, CAM_HEIGHT = 640, 360            # resolución de salida al stream (16:9)
    CAPTURA_WIDTH, CAPTURA_HEIGHT = 1280, 720   # captura nativa del sensor
else:
    CAM_WIDTH, CAM_HEIGHT = 640, 480            # resolución de salida al stream (4:3)
    CAPTURA_WIDTH, CAPTURA_HEIGHT = CAM_WIDTH, CAM_HEIGHT
CAM_FPS = 30

# Overlay de montaje (fase P0.6): cruz de referencia sobre el vídeo eye-in-hand
# para apuntar la cámara con precisión (vertical central entre las mordazas).
# Solo para el montaje físico; debe estar DESACTIVADO durante las pruebas reales.
# Se activa con la variable de entorno MOSTRAR_RETICULO=1
# (ver Pruebas_Funcionales/captura/reticulo_overlay.py).
MOSTRAR_RETICULO = os.environ.get("MOSTRAR_RETICULO", "0") == "1"

# Filas guía del retículo como FRACCIÓN de la altura del frame, para que valgan
# con cualquier resolución. Encuadre de referencia del TFG (definido en 640x360):
#   puntas de las mordazas -> fila 180 px = 50% de la altura (en 640x480: fila 240)
#   base del objeto / línea de mesa -> fila 310 px = 86% de la altura (en 640x480: fila 413)
RETICULO_FRAC_MORDAZAS = 0.50
RETICULO_FRAC_MESA = 0.86

# =============== UTILIDADES =========================
def clamp(v, vmin, vmax):
    return max(vmin, min(vmax, v))

def desnormalizar(norm_x, norm_y, norm_z, gripper):
    """
    Convierte el vector normalizado [0,1] recibido de Unity
    a coordenadas físicas en centímetros para el brazo robot.

    Semántica (ver PDF Normalizacion_Coordenadas del TFG):
        norm_x = 0.5  -> centro lateral    (postura neutra)
        norm_y = 0.5  -> altura neutra     (postura neutra)
        norm_z = 0.0  -> brazo recogido    (postura neutra)
        norm_z = 1.0  -> brazo estirado al máximo hacia el frente
        gripper= 0.0  -> pinza cerrada  (pellizco activo en Unity)
        gripper= 1.0  -> pinza abierta
    """
    # norm_z = 0 -> brazo recogido -> X del robot pequeño
    # norm_z = 1 -> brazo estirado -> X del robot grande
    x_robot = X_MIN + norm_z *  (X_MAX - X_MIN)

    # norm_x = 0.5 -> centro -> Y del robot = 0
    # norm_x = 0 -> izquierda -> Y positiva (Y_MAX)
    # norm_x = 1 -> derecha -> Y negativa (Y_MIN)
    y_robot = Y_MAX + norm_x * (Y_MIN - Y_MAX)

    # norm_y = 0.5 -> altura neutra -> Z del robot medio
    # norm_y = 1 -> mano arriba -> Z positiva
    # norm_y = 0 -> mano abajo -> Z negativa
    z_robot = Z_MIN + norm_y * (Z_MAX - Z_MIN)

    t = T_CLOSED + (T_OPEN - T_CLOSED) * clamp(gripper, 0.0, 1.0)

    return x_robot, y_robot, z_robot, t


#------ COMUNICACION SERIAL --------------------
def crear_conexion_serial(puerto, baudrate=115200):
    """
    Abre la conexion con el robot por puerto serial

    puerto: 'COM3','COM4'...
    baudrate: velocidad de comunicacion. Por defecto RoArm M2 usa 115200.

    timeout=1: si no hay respuesta en 1 segundo, no se bloquea indefinidamente.
    """
    try:
        ser = serial.Serial(puerto, baudrate, timeout=1)
        time.sleep(2)
        # El sleep de 2 segundos es necesario porque algunos Arduinos/ESP32 se reinician
        # al conectarlo por puerto serie y necesitan un tiempo para volver a arrancar
        print(f"CONEXION SERIAL ABIERTA: {puerto} @ {baudrate} baud")
        return ser
    except serial.SerialException as e:
        print(f"ERROR ABRIENDO PUERTO SERIAL {puerto}: {e}")
        return None

def enviar_comando_serial(ser, data):
    """
    Envia un diccionario JSON al robot por puerto serial.

    Añadimos '\n' al final porque el firmware del robot usa el salto de línea
    como delimitador de mensaje, sabe que el comando está completo cuando
    recibe '\n', igual que una terminal de comandos.

    encode('utf-8'): convierte el string a bytes, que es lo que el puerto
    serial puede transmitir (los puertos serial trabajan con bytes, no strings).
    """
    try:
        json_str = json.dumps(data) + '\n'
        ser.write(json_str.encode('utf-8'))

        if TRACE_ENABLED:
            print(f"SERIAL SEND: {json_str.strip()}")

        # readline() espera hasta recibir '\n' o hasta que pase el timeout.
        # Si el robot no responde, simplemente devuelve b'' sin bloquear.
        respuesta = ser.readline().decode('utf-8', errors='ignore').strip()
        if respuesta and TRACE_ENABLED:
            print(f"SERIAL RECV: {respuesta}")

        return respuesta

    except serial.SerialException as e:
        print(f"[SERIAL] Error enviando comando: {e}")
        return None

# ==================== VIDEO TRACK ===================
def dibujar_reticulo(frame_bgr):
    """
    Dibuja sobre un frame BGR el overlay de montaje de la cámara (fase P0.6):

      - Cruz verde centrada (vertical en x = w//2, horizontal en y = h//2), 1 px.
      - Líneas horizontales amarillas en las filas guía: puntas de las mordazas
        (RETICULO_FRAC_MORDAZAS) y línea de mesa (RETICULO_FRAC_MESA).

    Se usan las dimensiones REALES del frame (frame.shape) y no las constantes
    CAM_WIDTH/CAM_HEIGHT, porque cv2.VideoCapture.set() es solo una petición al
    driver: si la cámara negocia otra resolución, el retículo sigue centrado.
    """
    h, w = frame_bgr.shape[:2]
    VERDE = (0, 255, 0)       # cruz central
    AMARILLO = (0, 255, 255)  # filas guía (no confundir con la cruz)

    cv2.line(frame_bgr, (w // 2, 0), (w // 2, h), VERDE, 1)
    cv2.line(frame_bgr, (0, h // 2), (w, h // 2), VERDE, 1)

    y_mordazas = int(h * RETICULO_FRAC_MORDAZAS)
    y_mesa = int(h * RETICULO_FRAC_MESA)
    cv2.line(frame_bgr, (0, y_mordazas), (w, y_mordazas), AMARILLO, 1)
    cv2.line(frame_bgr, (0, y_mesa), (w, y_mesa), AMARILLO, 1)
    return frame_bgr

class CameraVideoTrack(MediaStreamTrack):
    """
    Track de vídeo que captura desde la cámara USB conectada al PC del robot
    y lo transmite a Unity a través del canal de vídeo WebRTC.
    Unity recibe este stream en peerConnection.OnTrack → imagenVideo.texture.
    """
    kind = "video"

    def __init__(self, cam_index=0):
        super().__init__()
        self.cap = cv2.VideoCapture(cam_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir la camara con indice {cam_index}")

        # Configuramos resolucion y FPS en la camara.
        # OJO: cap.set() es solo una PETICION al driver; verificamos lo concedido.
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURA_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, CAM_FPS)

        real_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        real_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (real_w, real_h) != (CAPTURA_WIDTH, CAPTURA_HEIGHT):
            log.warning(
                f"La camara no concedio {CAPTURA_WIDTH}x{CAPTURA_HEIGHT}: "
                f"esta capturando a {real_w}x{real_h}"
            )
        if MODO_16_9:
            log.info(f"Modo 16:9 activo: captura {CAPTURA_WIDTH}x{CAPTURA_HEIGHT} "
                     f"-> salida {CAM_WIDTH}x{CAM_HEIGHT}")
        if MOSTRAR_RETICULO:
            log.info("Reticulo de montaje ACTIVO (solo para P0.6; "
                     "desactivar en pruebas reales)")

        self._pts = 0
        self._time_base = fractions.Fraction(1, CAM_FPS)
        self._next_time = time.time()

    async def recv(self):
        """
        Llamado por aiortc cada vez que necesita un nuevo frame de vídeo.
        asyncio.sleep regula la cadencia para no superar CAM_FPS.
        Capturamos el frame, lo convertimos de BGR (OpenCV) a RGB (WebRTC/av)
        y lo empaquetamos en un VideoFrame con el timestamp correcto.
        """
        # Regulamos la cadencia de frames: dormimos lo justo para respetar los FPS
        ahora = time.time()
        espera = self._next_time - ahora
        if espera > 0:
            await asyncio.sleep(espera)

        self._next_time = time.time() + 1.0 / CAM_FPS

        # Capturamos el frame de la camara del brazo
        #ret, frame_bgr = self.cap.read()
        #if self._pts % 30 == 0:   # log cada segundo aprox
        #    log.info(f"CameraVideoTrack: frame {self._pts}, camara ok={ret}")
        #ASI QUE ERA COMO ESTABA, BLOQUEABA EL EVENT LOOP

        loop = asyncio.get_event_loop()
        ret, frame_bgr = await loop.run_in_executor(None, self.cap.read)

        if not ret:
            # Si la camara no responde, enviamos un frame negro para no romper el stream
            frame_bgr = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
            cv2.putText(frame_bgr, "CAMARA NO DISPONIBLE", (50, CAM_HEIGHT // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,0,255), 2)
        else:
            # Si capturamos en 16:9 nativo (1280x720) y la salida es 640x360, reescalamos
            if MODO_16_9 and (frame_bgr.shape[1], frame_bgr.shape[0]) != (CAM_WIDTH, CAM_HEIGHT):
                frame_bgr = cv2.resize(frame_bgr, (CAM_WIDTH, CAM_HEIGHT), interpolation=cv2.INTER_AREA)

            # Overlay de retículo para calibración y montaje en fase P0.6
            if MOSTRAR_RETICULO:
                frame_bgr = dibujar_reticulo(frame_bgr)

        # OpenCV trabaja en BGR; av/WebRTC espera RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Empaquetamos en VideoFrame de av con timestamp de presentacion (pts)
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = self._pts
        video_frame.time_base = self._time_base
        self._pts += 1

        return video_frame

    def detener(self):
        """Libera la camara al cerrar la sesion"""
        if self.cap.isOpened():
            self.cap.release()
        super().stop()

# =================== WEBRTC =====================
async def ejecutar_webrtc(args):
    """
    Bucle principal de WebRTC. Se conecta al servidor de señalización
    (signaling_server.py) y gestiona toda la comunicación con Unity:

        1. Conecta al servidor de señalización vía WebSocket
        2. Espera la oferta SDP de Unity (Unity actúa como caller/offerente)
        3. Configura la PeerConnection, añade el track de vídeo de la cámara
        4. Crea la respuesta SDP (answer) con ICE gathering completo (vanilla ICE)
        5. Intercambia candidatos ICE de Unity
        6. Recibe coordenadas normalizadas por el DataChannel → serial al robot
        7. Envía feedback de posición comandada a Unity por el mismo DataChannel
    """

    # Conexion serial al robot----------------------
    ser = crear_conexion_serial(args.puerto, args.baudrate)
    if ser is None:
        log.error("Imposible continuar sin conexión serial al robot")
        return

    # Registro funcional M1-M4 (Fase P2): se abre sesión cuando el DataChannel
    # queda establecido con Unity y se cierra al terminar ejecutar_webrtc()
    # (bloque finally), tanto si la sesión acaba bien como por error/Ctrl+C.
    # Se organiza en subcarpetas según la métrica (ej. resultados/M1/csv_grabaciones, resultados/M2/csv_grabaciones...)
    ruta_salida = Path(__file__).resolve().parents[1] / "Pruebas_Funcionales" / "resultados" / args.metrica / "csv_grabaciones"
    registrador = RegistradorFuncional(output_dir=ruta_salida)

    min_dt = 1.0 / args.freq if args.freq > 0 else 0.0
    last_send = 0.0

    #---- Track de vídeo: cámara del brazo -> Unity ----
    # Lo creamos fuera del bloque websockets para poder llamar a detener() en el finally
    try:
        video_track = CameraVideoTrack(args.camera)
    except RuntimeError as e:
        log.error(e)
        ser.close()
        return

    uri = f"ws://{args.ip}:{args.puerto_webrtc}"

    pc = None
    #---- Bucle de reintento con backoff exponencial (problema 5.7) ----
    # La conexion serial y la camara se abren UNA sola vez (arriba) y se cierran
    # solo en la salida definitiva (finally). El bucle reintenta UNICAMENTE la
    # conexion de red: ws nuevo -> reautenticacion -> esperar oferta nueva
    # (la oferta nueva recrea pc y video_track por el flujo ya correcto de
    # "oferta nueva = pc nueva", Incidencia 3). OJO: no capturamos
    # asyncio.CancelledError (es BaseException, no Exception): si la
    # tragaramos, Ctrl+C durante el sleep del backoff dejaria de propagarse
    # a main() y romperia el cierre limpio.
    intento = 0
    delay = BACKOFF_INICIAL_S
    try:
        while True:
            intento += 1
            log.info(f"Conectando al servidor de señalizacion en {uri} (intento {intento}/{args.max_reintentos}) ...")
            try:
                async with websockets.connect(uri) as ws:
                    # Enviar mensaje de autenticación inmediatamente
                    auth_msg = {
                        "type": "auth",
                        "token": config.SESSION_TOKEN
                    }
                    await ws.send(json.dumps(auth_msg))

                    # Sesion arrancada: reseteamos el backoff para que
                    # --max-reintentos sea un presupuesto por RACHA de fallos
                    # consecutivos y no de por vida del proceso. Cada sesion
                    # que llega hasta aqui "olvida" los fallos anteriores,
                    # igual que en Unity cada llamada nueva a
                    # ConectarSignaling() empieza con el contador a cero.
                    intento = 0
                    delay = BACKOFF_INICIAL_S

                    log.info("Autenticado. Esperando oferta SDP de Unity ...")

                    #---- Configuracion de la PeerConnection ----
                    # Mismo servidor STUN que se usa en Unity en ScriptWebRTC.cs
                    rtc_config = RTCConfiguration(
                        iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
                    )
                    #---- DataChannel: Unity lo crea ("comandos"), Python lo recibe aquí ----
                    # Es bidireccional: Unity envia coordenadas, python devuelve la posicion del brazo
                    # on_datachannel se define UNA sola vez y se re-registra en cada PC nueva
                    # (ver bloque "offer"): no depende de la PC concreta, solo de 'ser'/'channel'.
                    data_channel = None

                    def on_datachannel(channel):
                        nonlocal data_channel
                        data_channel = channel
                        log.info(f"DataChannel '{channel.label}' establecido --- control activo.")

                        # Nueva sesión de registro funcional cada vez que se abre el
                        # DataChannel (una reconexión de las gafas = una sesión nueva,
                        # igual que se recrea la PeerConnection en el bloque "offer")
                        registrador.abrir_sesion(
                            id_operador=args.operador,
                            condicion_red=args.condicion,
                            id_intento=args.intento
                        )

                        @channel.on("message")
                        def on_message(msg):
                            nonlocal last_send, ser

                            # t_robot_recepcion (registro funcional M1-M4): se toma
                            # aquí, nada más entrar, para que sea lo más fiel posible
                            # al instante real de llegada al bucle asyncio.
                            t_robot_recepcion = time.time() * 1000.0

                            # 1. Parsear JSON — si falla, descartar
                            try:
                                data = json.loads(msg)
                            except (json.JSONDecodeError, ValueError) as e:
                                log.warning(f"Mensaje malformado: '{msg}' — {e}")
                                return

                            # 2. Discriminar por tipo ANTES de procesar coordenadas
                            tipo = data.get("type")

                            if tipo == "ping":
                                channel.send(json.dumps({
                                    "type": "pong",
                                    "seq":  data.get("seq", 0),
                                    "client_ts": data.get("client_ts"),
                                    "server_ts": int(time.time() * 1000)
                                }))
                                return

                            if tipo == "csv_export":
                                sesion_raw = data.get("sesion", datetime.now().strftime("%Y%m%d_%H%M%S"))
                                sesion = os.path.basename(str(sesion_raw))
                                if not re.match(r'^[a-zA-Z0-9_-]+$', sesion):
                                    log.warning(f"Sesión no válida en csv_export: '{sesion_raw}'")
                                    return

                                ruta_resultados = "Pruebas_Conexion/Resultados_Robot" if os.path.exists("Pruebas_Conexion") else "resultados"
                                os.makedirs(ruta_resultados, exist_ok=True)

                                base_dir = os.path.realpath(ruta_resultados)
                                filename = os.path.realpath(os.path.join(ruta_resultados, f"red_{sesion}.csv"))
                                if not (filename == base_dir or filename.startswith(base_dir + os.sep)):
                                    log.warning(f"Intento de path traversal detectado en csv_export: '{sesion_raw}'")
                                    return

                                with open(filename, "w", encoding="utf-8") as f:
                                    f.write(data.get("data", ""))
                                log.info(f"[MetricsLogger] CSV guardado: {filename}")
                                return

                            # 3. Control de frecuencia
                            now = time.time()
                            if now - last_send < min_dt:
                                return
                            last_send = now

                            # 4. Coordenadas de control (protocolo existente)
                            try:
                                norm_x  = float(data.get("x", 0.5))
                                norm_y  = float(data.get("y", 0.5))
                                norm_z  = float(data.get("z", 0.0))
                                gripper = float(data.get("g", 1.0))
                            except ValueError as e:
                                log.warning(f"Valores malformados: {e}")
                                return

                            if not (math.isfinite(norm_x) and math.isfinite(norm_y) and
                                    math.isfinite(norm_z) and math.isfinite(gripper)):
                                log.warning(f"Coordenadas no finitas recibidas: x={norm_x}, y={norm_y}, z={norm_z}, g={gripper}")
                                return

                            # 5. Desnormalizar y enviar al robot
                            x_cm, y_cm, z_cm, t = desnormalizar(
                                norm_x, norm_y, norm_z, gripper)
                            x_safe = clamp(x_cm, X_MIN, X_MAX)
                            y_safe = clamp(y_cm, Y_MIN, Y_MAX)
                            z_safe = clamp(z_cm, Z_MIN, Z_MAX)

                            cmd = {
                                "T": 1041,
                                "x": int(x_safe * 10),
                                "y": int(y_safe * 10),
                                "z": int(z_safe * 10),
                                "t": round(t * 5, 1)
                            }
                            enviar_comando_serial(ser, cmd)
                            t_uart_escritura = time.time() * 1000.0

                            # Registro funcional M1-M4 (Fase P2): una fila por cada
                            # comando efectivamente enviado por UART. clamp_activo
                            # compara la coordenada antes y después de clamp(), no
                            # el propio valor "seguro" contra los límites.
                            registrador.registrar_comando(
                                norm_x=norm_x, norm_y=norm_y, norm_z=norm_z, g=gripper,
                                t_robot_recepcion=t_robot_recepcion,
                                x_cm=x_safe, y_cm=y_safe, z_cm=z_safe, t_rad=t,
                                t_uart_escritura=t_uart_escritura,
                                clamp_activo=(x_cm != x_safe or y_cm != y_safe or z_cm != z_safe)
                            )

                            if TRACE_ENABLED:
                                log.debug(
                                    f"norm({norm_x:.2f},{norm_y:.2f},{norm_z:.2f})"
                                    f" g={gripper:.2f} → {cmd}"
                                )

                            # 6. Feedback a Unity
                            if channel.readyState == "open":
                                channel.send(json.dumps({
                                    "x": round(norm_x, 3),
                                    "y": round(norm_y, 3),
                                    "z": round(norm_z, 3)
                                }))

                    # El handler de iceconnectionstatechange se registra DENTRO del bloque
                    # "offer", capturando por valor la PC concreta a la que pertenece, para
                    # que una PC vieja al fallar no cierre por error la PC de una reconexion.

                    # Lista de candidatos ICE que llegan antes de recibir la oferta.
                    # Los guardamos y los añadimos en orden correcto una vez que
                    # setRemoteDescription() haya sido llamado.
                    candidatos_pendientes = []

                    #---- Bucle de Señalizacion: procesamos mensajes del servidor ----
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            log.warning(f"Mensaje de señalizacion no-JSON ignorado: {raw[:80]}")
                            continue

                        tipo = msg.get("type", "")

                        #---- Oferta SDP de Unity ----
                        if tipo == "offer":
                            log.info("Oferta SDP recibida de Unity. Procesando...")

                            # --- Reconexion de las gafas: cada oferta = sesion nueva ---
                            # Una RTCPeerConnection de aiortc NO se puede reutilizar una vez
                            # cerrada: setRemoteDescription lanzaria InvalidStateError
                            # ("Cannot handle offer in signaling state closed") y Unity veria
                            # fallar su SetRemoteDescription. Por eso, si habia una PC de una
                            # sesion previa, la cerramos y recreamos la PC y el track de video
                            # (un track ya detenido no vuelve a emitir frames).
                            if pc is not None:
                                log.info("Nueva oferta: recreando PeerConnection y track de video")
                                await pc.close()
                                video_track.detener()
                                video_track = CameraVideoTrack(args.camera)

                            pc = RTCPeerConnection(configuration=rtc_config)
                            pc.on("datachannel", on_datachannel)

                            @pc.on("iceconnectionstatechange")
                            async def on_ice_change(_pc=pc):
                                # _pc=pc fija POR VALOR la PC de esta sesion.
                                log.info(f"ICE estado: {_pc.iceConnectionState}")
                                if _pc.iceConnectionState == "failed":
                                    await _pc.close()
                                    # NUEVO (5.7): cerramos tambien el WebSocket de
                                    # señalizacion. Esto fuerza el fin de la sesion
                                    # y el bucle de reintento exterior reconecta todo
                                    # (ws nuevo -> reauth -> esperar oferta nueva),
                                    # reutilizando el flujo ya correcto "oferta nueva
                                    # = pc nueva" sin mensajes de señalizacion nuevos.
                                    await ws.close()

                            # Establecemos la descripcion remota (la oferta que nos manda Unity)
                            desc = RTCSessionDescription(sdp=msg["sdp"], type="offer")
                            await pc.setRemoteDescription(desc)

                            pc.addTrack(video_track)
                            log.info("Video track añadido a la PeerConnection")

                            # Ahora si podemos añadir los candidatos que llegaron antes que la oferta
                            for candidato in candidatos_pendientes:
                                await pc.addIceCandidate(candidato)
                            candidatos_pendientes.clear()

                            # Creamos nuestra respuesta (answer)
                            answer = await pc.createAnswer()
                            await pc.setLocalDescription(answer)

                            # Esperamos a que aiortc termine de recopilar todos nuestros candidatos ICE
                            # (enfoque "vanilla ICE": los mandamos todos incluidos en el SDP del answer,
                            #  más simple que el trickle ICE porque no necesita mensajes extra).
                            while pc.iceGatheringState != "complete":
                                await asyncio.sleep(0.05)

                            # Enviamos el answer con todos nuestros candidatos incluidos en el SDP
                            await ws.send(json.dumps({
                                "type": "answer",
                                "sdp": pc.localDescription.sdp
                            }))
                            log.info(f"SDP del answer contiene video: {'m=video' in pc.localDescription.sdp}")

                            for linea in pc.localDescription.sdp.split("\r\n"):
                                if linea.startswith("a=rtpmap") or linea.startswith("m=video"):
                                    log.info(f"SDP codec: {linea}")

                            log.info("Answer enviado a Unity -- aguardando establecimiento ICE...")

                        #---- Candidatos ICE de Unity (trickle ICE) ----
                        elif tipo == "candidate":
                            candidate_str = msg.get("candidate", "")
                            if not candidate_str:
                                continue
                            try:
                                # aiortc espera la cadena SDP sin el prefijo "candidate:"
                                sdp_line = (
                                    candidate_str[len("candidate:"):]
                                    if candidate_str.startswith("candidate:")
                                    else candidate_str
                                )
                                ice = candidate_from_sdp(sdp_line)
                                ice.sdpMid = msg.get("sdpMid", "0")
                                ice.sdpMLineIndex = msg.get("sdpMLineIndex", 0)

                                if pc is not None and pc.remoteDescription is not None:
                                    await pc.addIceCandidate(ice)
                                else:
                                    # La oferta aun no ha llegado (pc todavia None), guardamos
                                    # para añadirlos justo despues de setRemoteDescription.
                                    candidatos_pendientes.append(ice)

                            except Exception as e:
                                log.warning(f"Error procesando candidato ICE: {e}")

                        else:
                            log.warning(f"Tipo de mensaje de señalizacion desconocido: '{tipo}'")

            except websockets.exceptions.ConnectionClosed:
                log.info("El servidor de señalizacion cerro la conexion")

            except OSError as e:
                log.error(f"No se pudo conectar al servidor de señalizacion en {uri}: {e}")

            # La sesion termino (cierre del servidor, ICE failed que cerro el ws,
            # o fallo de conexion). Si quedan intentos, esperamos con backoff y
            # reintentamos la conexion completa; si no, salimos y el finally
            # exterior limpia los recursos.
            if intento >= args.max_reintentos:
                log.error(f"Agotados los {args.max_reintentos} intentos de conexion. Saliendo.")
                break

            log.warning(f"Reintento {intento + 1}/{args.max_reintentos} en {delay:.0f}s...")
            await asyncio.sleep(delay)
            # Backoff exponencial con tope
            delay = min(delay * 2, BACKOFF_MAXIMO_S)

    finally:
        #---- Limpieza de recursos al salir ----
        registrador.cerrar_sesion()

        if video_track is not None:
            video_track.detener()

        if ser and ser.is_open:
            ser.close()
            log.info("Puerto serial cerrado")

        # Cerramos la PeerConnection si quedo alguna abierta (habilitado en 5.7):
        # necesario para no fugarse recursos entre reintentos y en la salida.
        if pc is not None:
            try:
                await pc.close()
            except Exception:
                pass

        video_track = None

        log.info("Sesion WebRTC finalizada")

# ===================== MAIN =====================
def main():
    parser = argparse.ArgumentParser(
        description="Control del RoArm M2 mediante WebRTC desde Unity XR"
    )
    parser.add_argument(
        "puerto",
        type=str,
        help="Puerto serial del robot. Ej: COM3 (Windows)"
    )
    parser.add_argument(
        "--baudrate", type=int, default=115200,
        help="Velocidad del puerto serial (default: 115200)"
    )
    parser.add_argument(
        "--camera", type=int, default=0,
        help="Índice de la cámara del brazo a transmitir a Unity (default: 0)"
    )
    parser.add_argument(
        "--ip", type=str, default="192.168.1.124",
        help="IP del PC donde corre signaling_server.py (default: 192.168.1.124)"
    )
    parser.add_argument(
        "--puerto-webrtc", type=int, default=8080,
        help="Puerto del servidor de señalización (default: 8080)"
    )
    parser.add_argument(
        "--freq", type=float, default=50.0,
        help="Frecuencia máxima de envío de comandos al robot en Hz (default: 50)"
    )
    parser.add_argument(
        "--max-reintentos", type=int, default=8,
        help="Número máximo de intentos de reconexión del WebSocket de señalización (default: 8)"
    )
    parser.add_argument(
        "--operador", type=str, default="OP1",
        help="Identificador del operador para el registro funcional M1-M4 (default: OP1)"
    )
    parser.add_argument(
        "--condicion", type=str, default="C1_ETHERNET_SIN_CARGA",
        help="Condición de red evaluada para el registro funcional (siempre Ethernet + Clumsy, nunca Wi-Fi "
             "real), ej. C1_ETHERNET_SIN_CARGA, C2_ETHERNET_CLUMSY_CARGA_MEDIA, C3_ETHERNET_CLUMSY_CARGA_ALTA, "
             "C4_ETHERNET_CLUMSY_EXTRA (default: C1_ETHERNET_SIN_CARGA)"
    )
    parser.add_argument(
        "--intento", type=int, default=1,
        help="Número de intento dentro de la condición actual, para las pruebas funcionales M1-M4 (default: 1)"
    )
    parser.add_argument(
        "--metrica", type=str, default="M1",
        help="Subcarpeta de la métrica en evaluación, ej. M1, M2, M3, M4 (default: M1)"
    )
    args = parser.parse_args()

    try:
        asyncio.run(ejecutar_webrtc(args))
    except KeyboardInterrupt:
        log.info("Detenido por el usuario (Ctrl+C).")

if __name__ == "__main__":
    main()
