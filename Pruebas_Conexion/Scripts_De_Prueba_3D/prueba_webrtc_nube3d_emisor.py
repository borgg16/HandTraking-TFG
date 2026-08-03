import asyncio
import json
import logging
import time
import argparse
import os
import sys
import struct
import math

# Añadir ruta para importar configuración centralizada
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "PC-ROBOT", "Configuracion")))
import config as central_config

import cv2
import numpy as np
import websockets
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.sdp import candidate_from_sdp

# Configurar consola en Windows para UTF-8 y evitar errores de encoding
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EmisorNube] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# Intentar importar dependencias 3D
try:
    import pyrealsense2 as rs
    REALSENSE_AVAILABLE = True
except ImportError:
    REALSENSE_AVAILABLE = False
    log.warning("pyrealsense2 no disponible. Se enviará nube sintética.")

try:
    import DracoPy
    DRACO_AVAILABLE = True
except ImportError:
    DRACO_AVAILABLE = False
    log.error("DracoPy NO disponible. El script no funcionará sin DracoPy.")

# Parámetros del protocolo
CHUNK_SIZE = 16384  # 16 KiB
MAX_BUFFER = 524288  # 512 KiB backpressure limit

class RealSenseCapturer:
    def __init__(self):
        self.pipeline = rs.pipeline()
        self.config = rs.config()
        self.config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        self.config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        self.align = rs.align(rs.stream.color)
        self.profile = None
        self.is_started = False
        
    def start(self):
        try:
            self.profile = self.pipeline.start(self.config)
            device = self.profile.get_device()
            usb_type = device.get_info(rs.camera_info.usb_type_descriptor) if device.supports(rs.camera_info.usb_type_descriptor) else "Desconocido"
            log.info(f"Cámara RealSense iniciada. (USB Type: {usb_type})")
            self.is_started = True
            return True
        except Exception as e:
            log.error(f"Error iniciando cámara RealSense: {e}")
            return False
            
    def capture_frame(self):
        if not self.is_started:
            return None, None
        try:
            frames = self.pipeline.wait_for_frames()
            aligned_frames = self.align.process(frames)
            depth_frame = aligned_frames.get_depth_frame()
            color_frame = aligned_frames.get_color_frame()
            if not depth_frame or not color_frame:
                return None, None
                
            intrinsics = depth_frame.profile.as_video_stream_profile().intrinsics
            depth_image = np.asanyarray(depth_frame.get_data())
            color_image = np.asanyarray(color_frame.get_data())
            
            stride = 2
            depth_sub = depth_image[::stride, ::stride]
            color_sub = color_image[::stride, ::stride]
            h, w = depth_sub.shape
            
            u = np.arange(w) * stride
            v = np.arange(h) * stride
            uu, vv = np.meshgrid(u, v)
            
            depth_scale = self.profile.get_device().first_depth_sensor().get_depth_scale()
            z_metros = depth_sub * depth_scale
            
            mask = (z_metros >= 0.3) & (z_metros <= 1.5)
            x_coords = (uu - intrinsics.ppx) * z_metros / intrinsics.fx
            y_coords = -(vv - intrinsics.ppy) * z_metros / intrinsics.fy
            
            points = np.stack((x_coords[mask], y_coords[mask], z_metros[mask]), axis=-1).astype(np.float32)
            colors_rgb = cv2.cvtColor(color_sub, cv2.COLOR_BGR2RGB)
            colors = colors_rgb[mask].astype(np.uint8)
            
            max_pts = 60000
            if len(points) > max_pts:
                idx = np.random.choice(len(points), max_pts, replace=False)
                points = points[idx]
                colors = colors[idx]
                
            return points, colors
        except Exception as e:
            log.error(f"Error en captura RealSense: {e}")
            return None, None
            
    def stop(self):
        if self.is_started:
            try:
                self.pipeline.stop()
            except Exception:
                pass
            self.is_started = False
            log.info("Cámara RealSense detenida.")

def generar_nube_sintetica(t_ms):
    resolucion = 150  # ~22.5k puntos
    x = np.linspace(-0.5, 0.5, resolucion)
    y = np.linspace(-0.5, 0.5, resolucion)
    xx, yy = np.meshgrid(x, y)
    frecuencia = 2.0 * math.pi * (t_ms / 1000.0) * 0.5
    zz = 1.0 + 0.15 * np.sin(5.0 * np.sqrt(xx**2 + yy**2) - frecuencia)
    points = np.stack((xx.ravel(), yy.ravel(), zz.ravel()), axis=-1).astype(np.float32)
    r = ((xx.ravel() + 0.5) * 255).astype(np.uint8)
    g = ((yy.ravel() + 0.5) * 255).astype(np.uint8)
    b = ((zz.ravel() - 0.8) / 0.35 * 255).clip(0, 255).astype(np.uint8)
    colors = np.stack((r, g, b), axis=-1)
    return points, colors

def parsear_candidato_ice(candidate_str, sdp_mid, sdp_mline):
    candidato = candidate_from_sdp(candidate_str)
    candidato.sdpMid = sdp_mid
    candidato.sdpMLineIndex = sdp_mline
    return candidato

async def bucle_transmision_nube(channel, capturer, use_simulation):
    log.info("Iniciando bucle de transmisión de nube 3D...")
    frame_id = 0
    loop = asyncio.get_event_loop()
    
    try:
        while channel.readyState == "open":
            t_start = time.perf_counter()
            
            # Backpressure
            if channel.bufferedAmount > MAX_BUFFER:
                log.warning(f"Buffer lleno ({channel.bufferedAmount} bytes). Omitiendo frame.")
                await asyncio.sleep(0.05)
                continue
                
            # 1. Captura
            if use_simulation:
                t_ms = int(time.time() * 1000)
                points, colors = generar_nube_sintetica(t_ms)
                await asyncio.sleep(0.03)  # Simular lectura
            else:
                points, colors = await loop.run_in_executor(None, capturer.capture_frame)
                if points is None:
                    await asyncio.sleep(0.01)
                    continue
                    
            n_points = len(points)
            if n_points == 0:
                continue
                
            t_captura = int(time.time() * 1000)
            
            # 2. Compresión Draco
            t_enc_start = time.perf_counter()
            draco_bytes = await loop.run_in_executor(
                None,
                lambda: DracoPy.encode(
                    points,
                    colors=colors,
                    quantization_bits=11,
                    compression_level=1
                )
            )
            encode_ms = (time.perf_counter() - t_enc_start) * 1000
            
            # 3. Envío en chunks
            total_bytes = len(draco_bytes)
            n_chunks = math.ceil(total_bytes / CHUNK_SIZE)
            
            for chunk_idx in range(n_chunks):
                start_offset = chunk_idx * CHUNK_SIZE
                end_offset = min(start_offset + CHUNK_SIZE, total_bytes)
                chunk_data = draco_bytes[start_offset:end_offset]
                
                # Cabecera de 26 bytes: struct.pack("<HBBIHHQIH")
                header = struct.pack(
                    "<HBBIHHQIH",
                    0x4E33,                # magic
                    1,                     # version
                    0,                     # flags
                    frame_id,              # frame_id
                    chunk_idx,             # chunk_idx
                    n_chunks,              # n_chunks
                    t_captura,             # t_captura
                    n_points,              # n_puntos
                    int(encode_ms * 10)    # encode_ms_x10
                )
                
                # Enviar cabecera + datos
                channel.send(header + chunk_data)
                
            frame_id += 1
            if frame_id % 30 == 0:
                log.info(f"Frame {frame_id:04d} enviado | Puntos: {n_points} | Chunks: {n_chunks} | Draco: {total_bytes/1024:.1f} KB | Enc={encode_ms:.1f}ms")
                
            # Limitar a ~10 fps nominales
            espera = max(0, 0.1 - (time.perf_counter() - t_start))
            await asyncio.sleep(espera)
            
    except Exception as e:
        log.error(f"Error en bucle de transmisión: {e}")

async def ejecutar_emisor(ip_signaling, puerto_signaling):
    uri = f"ws://{ip_signaling}:{puerto_signaling}/"
    log.info(f"Conectando a señalización en {uri}...")
    
    capturer = None
    use_simulation = True
    
    if REALSENSE_AVAILABLE:
        capturer = RealSenseCapturer()
        if capturer.start():
            use_simulation = False
            
    if use_simulation:
        log.info("Modo simulación activo. Generando nube sintética...")
        
    config = RTCConfiguration(iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")])
    pc = RTCPeerConnection(configuration=config)
    
    @pc.on("datachannel")
    def on_datachannel(channel):
        log.info(f"DataChannel recibido: {channel.label}")
        if channel.label == "nube3d":
            asyncio.create_task(bucle_transmision_nube(channel, capturer, use_simulation))
            
    try:
        async with websockets.connect(uri) as ws:
            auth_msg = {
                "type": "auth",
                "token": central_config.SESSION_TOKEN
            }
            await ws.send(json.dumps(auth_msg))
            log.info("Conectado y autenticado. Esperando oferta de Unity...")
            
            async for mensaje in ws:
                msg = json.loads(mensaje)
                tipo = msg.get("type", "desconocido")
                
                if tipo == "offer":
                    log.info("Oferta SDP recibida de Unity")
                    desc = RTCSessionDescription(sdp=msg["sdp"], type="offer")
                    await pc.setRemoteDescription(desc)
                    
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
                        
    except Exception as e:
        log.error(f"Error en bucle de señalización: {e}")
    finally:
        log.info("Cerrando emisor...")
        if capturer:
            capturer.stop()
        await pc.close()
        log.info("Emisor finalizado.")

def main():
    parser = argparse.ArgumentParser(description="Emisor de nube de puntos 3D comprimida con Draco")
    parser.add_argument("--ip", default="192.168.1.124", help="IP del servidor de señalización")
    parser.add_argument("--puerto", type=int, default=8080, help="Puerto del servidor de señalización")
    args = parser.parse_args()
    
    try:
        asyncio.run(ejecutar_emisor(args.ip, args.puerto))
    except KeyboardInterrupt:
        log.info("Emisor detenido por el usuario (Ctrl+C)")

if __name__ == "__main__":
    main()
