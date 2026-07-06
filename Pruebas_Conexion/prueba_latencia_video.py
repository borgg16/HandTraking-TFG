"""
    Version reducida del script de safe8_webRTC.py para realizar las pruebas de video en distintas condiciones
    para ello hemos suprimido temporalmente la conexion con el brazo RoArm-M2 como el envio y recepcion de coordenadas respectivas del brazo

    Uso:
        python prueba_latencia_video.py --ip 192.168.1.124 --puerto 8080 --camara 0

    Dependencias:
        pip install aiortc opencv-python websockets av
"""
import asyncio
import json
import logging
import time
import argparse

import cv2
import numpy as np
import websockets
from fractions import Fraction
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.mediastreams import MediaStreamTrack
from aiortc.sdp import candidate_from_sdp
from av import VideoFrame

# Reloj RTP estándar para vídeo (90kHz) — usado para construir manualmente
# el pts/time_base de cada frame, ya que la versión instalada de aiortc
# no trae next_timestamp() incorporado en MediaStreamTrack (versiones
# antiguas de aiortc sí lo traían vía una clase VideoStreamTrack que
# ya no existe en la versión actual)
VIDEO_CLOCK_RATE = 90000
VIDEO_TIME_BASE = Fraction(1, VIDEO_CLOCK_RATE)

#--------------------------------------------------------
# CONFIGURACION
#--------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PruebaVideo] %(message)s",
    datefmt="%H:%M:%S"
)

log = logging.getLogger(__name__)

# Resolucion y FPS del stream - mismos valores que safe8_WebRTC.py (para tener las mismas condiciones)
CAM_WIDTH = 640
CAM_HEIGHT = 480
CAM_FPS = 30

#----------------------------------------------------------
# TRACK DEL VIDEO CON OVERLAY DEL TIMESTAMP
#----------------------------------------------------------
class VideoTrackConTimestamp(MediaStreamTrack):
    """
    Captura frames de la camara, les añade un timestamp visible
    (P:XXXXX), en la esquina superior IZQUIERDA y envia el mismo valor por el DataChannel
    como {"type":"frame_ts","t":...} para que Unity calcule automaticamente la latencia
    """

    kind = "video"

    def __init__(self, cap: cv2.VideoCapture):
        super().__init__()
        self.cap = cap
        self.datachannel = None  # se asigna desde fuera cuando unity abre el canal
        self._contador_frames = 0
        self._start = None       # momento de inicio del stream, para el pacing manual
        self._timestamp = 0      # pts acumulado en unidades de VIDEO_CLOCK_RATE

    async def _next_timestamp(self):
        """
        Reemplaza a self.next_timestamp(), que NO existe en la version
        instalada de aiortc (versiones antiguas si lo traian incorporado
        via una clase VideoStreamTrack que ya no existe). Calculamos el
        pts nosotros mismos y esperamos lo necesario para respetar CAM_FPS.
        """
        if self._start is None:
            self._start = time.time()
            self._timestamp = 0
        else:
            self._timestamp += int(VIDEO_CLOCK_RATE / CAM_FPS)
            tiempo_objetivo = self._start + (self._timestamp / VIDEO_CLOCK_RATE)
            espera = tiempo_objetivo - time.time()
            if espera > 0:
                await asyncio.sleep(espera)

        return self._timestamp, VIDEO_TIME_BASE

    async def recv(self) -> VideoFrame:
        loop = asyncio.get_event_loop()

        #---- Captura sin bloquear el el event loop ----
        ret, frame_bgr = await loop.run_in_executor(None, self.cap.read)

        if not ret:
            frame_bgr = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
            cv2.putText(
                frame_bgr,
                "CAMARA NO DISPONIBLE",
                (50, CAM_HEIGHT // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 0, 255),
                2,
            )

        #---- Timestamp COMPLETO en ms (epoch UTC) - para el calculo real de latencia ----
        ts_completo_ms = int(time.time() * 1000)

        #---- Version recortada a 5 digitos - SOLO para mostrarla en pantalla ----
        ts_display = ts_completo_ms % 100000

        #---- OVERLAY VISIBLE "P:XXXXX" esquina superior izquierda ----
        cv2.putText(
            frame_bgr,
            f"P:{ts_display:05d}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            2,
        )

        #---- Envio del timestamp COMPLETO por DataChannel (para el calculo de latencia) ----
        if self.datachannel is not None and self.datachannel.readyState == "open":
            self.datachannel.send(json.dumps({"type": "frame_ts", "t": ts_completo_ms}))

        self._contador_frames += 1

        if self._contador_frames % 30 == 0:
            log.info(f"Frames enviados: {self._contador_frames} (último P mostrado={ts_display:05d})")

        #---- Conversion a videoFrame para aiortc ----
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        pts, time_base = await self._next_timestamp()
        video_frame.pts = pts
        video_frame.time_base = time_base

        return video_frame


#---------------------------------------------------------------------------
# PARSEO DE CANDIDATOS ICE
#---------------------------------------------------------------------------
def parsear_candidato_ice(candidate_str, sdp_mid, sdp_mline):
    candidato = candidate_from_sdp(candidate_str)
    candidato.sdpMid = sdp_mid
    candidato.sdpMLineIndex = sdp_mline
    return candidato

#---------------------------------------------------------------------------
# BUCLE PRINCIPAL
#---------------------------------------------------------------------------
async def ejecutar_prueba(ip_signaling: str, puerto_signaling: int, indice_camara: int):
    uri = f"ws://{ip_signaling}:{puerto_signaling}/"
    log.info(f"Conectando al servidor de señalización en {uri}...")

    cap = cv2.VideoCapture(indice_camara)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAM_FPS)

    if not cap.isOpened():
        log.error(f"No se pudo abrir la cámara (índice {indice_camara}). Revisa la conexión.")
        return

    video_track = VideoTrackConTimestamp(cap)

    config = RTCConfiguration(iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")])
    pc = RTCPeerConnection(configuration=config)

    @pc.on("datachannel")
    def on_datachannel(channel):
        log.info(f"DataChannel recibido: {channel.label}")

        # Le damos al track acceso al canal para poder enviar frame_ts
        video_track.datachannel = channel

        @channel.on("message")
        def on_message(message):
            try:
                data = json.loads(message)
                tipo = data.get("type", "desconocido")
                if tipo == "ping":
                    channel.send(json.dumps({
                        "type": "pong",
                        "seq": data.get("seq", 0),
                        "client_ts": data.get("client_ts"),
                        "server_ts": int(time.time() * 1000)
                    }))
                    return
                elif tipo != "frame_ts":  # evitar loguear nuestro propio eco si lo hubiera
                    log.info(f"Mensaje recibido por DataChannel: tipo='{tipo}'")
            except json.JSONDecodeError:
                log.warning("Mensaje no-JSON recibido por DataChannel")

    try:
        async with websockets.connect(uri) as ws:
            log.info("Conectado al servidor de señalización. Esperando oferta de Unity...")

            async for mensaje in ws:
                msg = json.loads(mensaje)
                tipo = msg.get("type", "desconocido")

                if tipo == "offer":
                    log.info("Oferta SDP recibida de Unity")
                    desc = RTCSessionDescription(sdp=msg["sdp"], type="offer")
                    await pc.setRemoteDescription(desc)

                    # addTrack DESPUÉS de setRemoteDescription — evita el
                    # ValueError conocido de aiortc si se hace antes
                    pc.addTrack(video_track)

                    answer = await pc.createAnswer()
                    await pc.setLocalDescription(answer)

                    await ws.send(json.dumps({
                        "type": "answer",
                        "sdp": pc.localDescription.sdp
                    }))
                    log.info("Respuesta SDP enviada a Unity")

                elif tipo == "candidate":
                    if msg.get("candidate"):
                        candidato = parsear_candidato_ice(
                            msg["candidate"], msg.get("sdpMid"), msg.get("sdpMLineIndex")
                        )
                        await pc.addIceCandidate(candidato)

                else:
                    log.warning(f"Tipo de mensaje de señalización desconocido: {tipo}")

    except (websockets.exceptions.ConnectionClosed, OSError) as e:
        log.error(f"Conexión de señalización perdida: {e}")

    finally:
        log.info("Cerrando prueba de latencia de video...")
        if cap.isOpened():
            cap.release()
        try:
            await pc.close()
        except Exception as e:
            log.warning(f"Error cerrando PeerConnection: {e}")
        log.info("Prueba finalizada")


#-------------------------------------------------------------------------------
# PUNTO DE ENTRADA
#-------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Prueba aislada de latencia de video (sin brazo)")
    parser.add_argument("--ip", default="192.168.1.124", help="IP del servidor de señalización")
    parser.add_argument("--puerto", type=int, default=8080, help="Puerto del servidor de señalización")
    parser.add_argument("--camara", type=int, default=0, help="Índice de la cámara (0 = por defecto)")
    args = parser.parse_args()

    try:
        asyncio.run(ejecutar_prueba(args.ip, args.puerto, args.camara))
    except KeyboardInterrupt:
        log.info("Prueba detenida por el usuario (Ctrl+C)")


if __name__ == "__main__":
    main()