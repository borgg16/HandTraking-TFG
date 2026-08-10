# mock_unity_nube3d.py — Simulador de Unity para el pipeline de nube de puntos 3D
"""
Hace de gafas Quest sin gafas: abre los dos DataChannels que crea Unity
("comandos" y "nube3d"), manda la oferta SDP y se pone a recibir la nube.

Sirve para validar la fase F1/F3 en PC-PC antes de tocar el visor:
    - Reensambla los chunks e informa de perdidas.
    - Descomprime la trama Draco y comprueba que los puntos son coherentes.
    - Mide latencia, ancho de banda, fps y tiempo de decodificacion.
    - En paralelo inyecta coordenadas y pings por "comandos", que es la prueba
      de fuego del apartado 9: el RTT del control no debe dispararse por la nube.

Uso (con el robot corriendo safe8_WebRTC.py y el signaling_server.py arrancado):
    python mock_unity_nube3d.py
    python mock_unity_nube3d.py --sin-comandos      # solo nube, sin teleoperar

Nota sobre la latencia: t_captura viaja en la cabecera con el reloj del PC-ROBOT.
Si el simulador corre en esa misma maquina la medida es directa; si corre en otra,
la cifra incluye la desviacion entre relojes (Unity la corrige con el offset por RTT).
"""
import argparse
import asyncio
import json
import logging
import math
import os
import statistics
import sys
import time

import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Configuracion")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Camara3D")))
import config
import draco_encoder
import nube_protocolo

if sys.platform.startswith("win"):
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Mock Nube3D] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

URI_SIGNALING = f"ws://{config.SIGNALING_IP}:{config.SIGNALING_PORT}"


class EstadisticasNube:
    """Acumula lo que en las gafas mostraria el PanelControlVolumetrico."""

    def __init__(self):
        self.reensamblador = nube_protocolo.Reensamblador()
        self.bytes_ventana = 0
        self.frames_ventana = 0
        self.t_ventana = time.perf_counter()
        self.latencias = []
        self.decodes = []
        self.ultimo_n_puntos = 0
        self.ultimo_encode_ms = 0.0
        self.total_frames = 0

    def procesar_chunk(self, datos):
        self.bytes_ventana += len(datos)

        resultado = self.reensamblador.procesar(datos)
        if resultado is None:
            return

        cabecera, trama = resultado
        latencia_ms = nube_protocolo.ahora_ms() - cabecera.t_captura

        t0 = time.perf_counter()
        puntos, colores = draco_encoder.descomprimir(trama)
        decode_ms = (time.perf_counter() - t0) * 1000.0

        if puntos is None:
            log.warning(f"Frame {cabecera.frame_id}: la trama Draco no se pudo decodificar")
            return

        # Comprobacion de integridad: los puntos anunciados deben ser los recibidos
        if len(puntos) != cabecera.n_puntos:
            log.warning(f"Frame {cabecera.frame_id}: cabecera anuncia {cabecera.n_puntos} "
                        f"puntos y llegan {len(puntos)}")

        self.frames_ventana += 1
        self.total_frames += 1
        self.latencias.append(latencia_ms)
        self.decodes.append(decode_ms)
        self.ultimo_n_puntos = len(puntos)
        self.ultimo_encode_ms = cabecera.encode_ms

    def resumen(self):
        """Devuelve la linea de estado y reinicia la ventana. None si no toca aun."""
        transcurrido = time.perf_counter() - self.t_ventana
        if transcurrido < 5.0:
            return None

        fps = self.frames_ventana / transcurrido
        mbps = (self.bytes_ventana * 8) / (transcurrido * 1e6)
        lat = statistics.mean(self.latencias) if self.latencias else 0.0
        lat_p95 = (statistics.quantiles(self.latencias, n=20)[-1]
                   if len(self.latencias) >= 20 else lat)
        dec = statistics.mean(self.decodes) if self.decodes else 0.0
        r = self.reensamblador

        linea = (f"NUBE  {fps:4.1f} fps | {self.ultimo_n_puntos:6d} pts | "
                 f"lat {lat:5.0f} ms (p95 {lat_p95:5.0f}) | {mbps:5.1f} Mbps | "
                 f"enc {self.ultimo_encode_ms:4.1f} ms | dec {dec:4.1f} ms | "
                 f"frames {r.frames_completos} perdidos {r.frames_descartados}")

        self.bytes_ventana = 0
        self.frames_ventana = 0
        self.t_ventana = time.perf_counter()
        self.latencias.clear()
        self.decodes.clear()
        return linea


async def inyectar_comandos(canal, rtts, periodo=0.05):
    """
    Simula el envio de coordenadas de la mano y mide el RTT del canal de control.
    Es la referencia para comprobar que la nube no degrada la teleoperacion.
    """
    t0 = time.perf_counter()
    seq = 0
    ultimo_ping = 0.0

    while canal.readyState == "open":
        t = time.perf_counter() - t0

        # Trayectoria suave dentro del rango normalizado, como haria la mano
        import math
        canal.send(json.dumps({
            "x": round(0.5 + 0.3 * math.sin(t * 0.7), 3),
            "y": round(0.5 + 0.2 * math.cos(t * 0.5), 3),
            "z": round(0.5 + 0.3 * math.sin(t * 0.3), 3),
            "g": round(0.5 + 0.5 * math.sin(t * 1.1), 3),
        }))

        if t - ultimo_ping >= 2.0:
            ultimo_ping = t
            seq += 1
            rtts["pendientes"][seq] = time.perf_counter()
            canal.send(json.dumps({
                "type": "ping",
                "seq": seq,
                "client_ts": nube_protocolo.ahora_ms(),
            }))

        await asyncio.sleep(periodo)


async def correr_mock(args):
    pc = RTCPeerConnection()

    canal_comandos = pc.createDataChannel("comandos")
    canal_nube = pc.createDataChannel(config.NUBE_CHANNEL_LABEL)
    log.info(f"DataChannels creados: 'comandos' y '{config.NUBE_CHANNEL_LABEL}'")

    stats = EstadisticasNube()
    rtts = {"pendientes": {}, "medidos": []}

    @canal_nube.on("message")
    def on_nube(mensaje):
        if isinstance(mensaje, bytes):
            stats.procesar_chunk(mensaje)

    @canal_comandos.on("message")
    def on_comandos(mensaje):
        try:
            data = json.loads(mensaje)
        except (json.JSONDecodeError, ValueError):
            return

        if data.get("type") == "pong":
            seq = data.get("seq")
            t_envio = rtts["pendientes"].pop(seq, None)
            if t_envio is not None:
                rtts["medidos"].append((time.perf_counter() - t_envio) * 1000.0)

    @pc.on("track")
    def on_track(track):
        log.info(f"Recibiendo tambien el vídeo 2D del brazo ({track.kind})")

    async with websockets.connect(URI_SIGNALING) as ws:
        await ws.send(json.dumps({"type": "auth", "token": config.SESSION_TOKEN}))
        log.info("Autenticado en el servidor de señalización. Enviando oferta...")

        # Igual que Unity: pedimos el vídeo en modo solo recepción
        pc.addTransceiver("video", direction="recvonly")
        oferta = await pc.createOffer()
        await pc.setLocalDescription(oferta)
        await ws.send(json.dumps({"type": "offer", "sdp": pc.localDescription.sdp}))

        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "answer":
                await pc.setRemoteDescription(
                    RTCSessionDescription(sdp=msg["sdp"], type="answer"))
                log.info("Answer recibido — conexión P2P establecida")
                break

        while canal_nube.readyState != "open":
            await asyncio.sleep(0.1)
        log.info("Canal de nube abierto. Recibiendo... (Ctrl+C para salir)")

        tarea_comandos = None
        if args.comandos:
            tarea_comandos = asyncio.create_task(inyectar_comandos(canal_comandos, rtts))

        try:
            while pc.connectionState not in ("failed", "closed"):
                await asyncio.sleep(1.0)

                linea = stats.resumen()
                if linea is None:
                    continue

                log.info(linea)
                if rtts["medidos"]:
                    media = statistics.mean(rtts["medidos"])
                    log.info(f"CONTROL  RTT medio {media:5.1f} ms sobre "
                             f"{len(rtts['medidos'])} pings")
                    rtts["medidos"].clear()

        finally:
            if tarea_comandos is not None:
                tarea_comandos.cancel()
            log.info(f"Total de frames de nube completos: {stats.total_frames} "
                     f"(descartados {stats.reensamblador.frames_descartados})")
            await pc.close()


def main():
    parser = argparse.ArgumentParser(
        description="Simulador de Unity para la nube de puntos 3D (fases F1/F3)")
    parser.add_argument("--sin-comandos", dest="comandos", action="store_false",
                        help="No inyecta coordenadas ni pings por el canal de control")
    parser.set_defaults(comandos=True)
    args = parser.parse_args()

    if not draco_encoder.DRACO_DISPONIBLE:
        log.error("DracoPy no está instalado: no se puede descomprimir la nube recibida")
        return

    try:
        asyncio.run(correr_mock(args))
    except KeyboardInterrupt:
        log.info("Simulador detenido por el usuario (Ctrl+C)")


if __name__ == "__main__":
    main()
