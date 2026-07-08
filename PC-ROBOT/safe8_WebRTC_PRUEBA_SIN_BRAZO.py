import asyncio
import fractions
import json
import logging
import time
import argparse
from datetime import datetime   # necesario para el nombre de sesion en csv_export

import cv2
import numpy as np
import serial
import websockets
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription
)
from aiortc.mediastreams import MediaStreamTrack
from aiortc.sdp import candidate_from_sdp
from av import VideoFrame

# ===================== MOCKS =============================
class DummySerial:
    """
    Clase falsa para simular el comportamiento del puerto serie sin el brazo conectado.
    Implementa la misma interfaz que serial.Serial para que el resto del codigo
    no necesite saber si hay hardware real o no.
    """
    is_open = True
    def write(self, data):
        pass                        # absorbe el comando sin enviarlo a ningun hardware
    def readline(self):
        return b'{"status":"mock_ok"}\n'   # respuesta generica del firmware simulado
    def close(self):
        pass


# ===================== CONFIGURACIÓN =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Robot] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

TRACE_ENABLED = False # Activa para ver cada JSON enviado/recibido por consola

# Límites de seguridad para el brazo (en cm)
X_MIN, X_MAX = 5.0, 40.0
Y_MIN, Y_MAX = -40.0, 40.0
Z_MIN, Z_MAX = -10.0, 50.0

# Configuración de la pinza (ángulo t)
T_OPEN   = 0.5     # pinza completamente abierta
T_CLOSED = 1.4     # pinza cerrada (aprox. 80°)

# Resolución y FPS de la cámara del brazo que se transmite a Unity
CAM_WIDTH = 640
CAM_HEIGHT = 480
CAM_FPS = 30

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
    #x_robot = X_MAX + norm_z *  (X_MIN - X_MAX)
    
    # norm_x= 0.5 -> centro -> Y del robot = 0
    # norm_x = 0 -> izquierda -> Y negativa
    # norm_x = 1 -> derecha -> Y positiva
    #y_robot = Y_MIN + norm_x * (Y_MAX - Y_MIN)
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
        
        # Configuramos resolucion y FPS en la camara
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, CAM_FPS)

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
        ret, frame_bgr = self.cap.read()
        if self._pts % 30 == 0:   # log cada segundo aprox
            log.info(f"CameraVideoTrack: frame {self._pts}, camara ok={ret}")
            
        if not ret:
            # Si la camara no responde, enviamos un frame negro para no romper el stream
            frame_bgr = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
            
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
    
    # Conexion serial al robot ----------------------------------------
    # En modo PRUEBA SIN BRAZO: si no hay hardware, activamos DummySerial
    # en lugar de abortar, para poder probar todo el stack WebRTC igualmente.
    ser = crear_conexion_serial(args.puerto, args.baudrate)
    if ser is None:
        log.warning("Puerto serie no detectado. ¡Activando MODO SIMULACIÓN sin hardware!")
        ser = DummySerial()  # En lugar de hacer return, usamos el brazo virtual
    
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
    log.info(f"Conectando al servidor de señalizacion en {uri} ...")
    
    pc = None
    try:
        async with websockets.connect(uri) as ws:
            log.info("Conectado. Esperando oferta SDP de Unity ...")
            
            #---- Configuracion de la PeerConnection ----
            # Mismo servidor STUN que se usa en Unity en ScriptWebRTC.cs
            config = RTCConfiguration(
                iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
            )
            pc = RTCPeerConnection(configuration=config)
            
            #---- DataChannel: Unity lo crea ("comandos"), Python lo recibe aquí ----
            # Es bidireccional: Unity envia coordenadas, python devuelve la posicion del brazo
            data_channel = None
            
            @pc.on("datachannel")
            def on_datachannel(channel):
                nonlocal data_channel
                data_channel = channel
                log.info(f"DataChannel '{channel.label}' establecido --- control activo.")

                @channel.on("message")
                def on_message(msg):
                    nonlocal last_send, ser

                    # 1. Parsear JSON — si falla, descartar
                    try:
                        data = json.loads(msg)
                    except (json.JSONDecodeError, ValueError) as e:
                        log.warning(f"Mensaje malformado: '{msg}' — {e}")
                        return

                    # 2. Discriminar por tipo ANTES de procesar coordenadas
                    tipo = data.get("type")

                    if tipo == "ping":
                        # Respondemos al ping de NetworkMetrics con un pong inmediato.
                        # El campo "seq" permite que Unity calcule el RTT por numero de secuencia.
                        channel.send(json.dumps({
                            "type": "pong",
                            "seq":  data.get("seq", 0),
                            "client_ts": data.get("client_ts"),
                            "server_ts": int(time.time() * 1000)
                        }))
                        return

                    if tipo == "csv_export":
                        # MetricsLogger pide guardar el CSV de la sesion en el PC del robot.
                        # Usamos datetime como fallback si Unity no manda nombre de sesion.
                        sesion   = data.get("sesion",
                                    datetime.now().strftime("%Y%m%d_%H%M%S"))

                        # Crear carpeta si no existe
                        import os
                        ruta_resultados = "Pruebas_Conexion/resultados" if os.path.exists("Pruebas_Conexion") else "resultados"
                        os.makedirs(ruta_resultados, exist_ok=True)

                        filename = f"{ruta_resultados}/red_{sesion}.csv"
                        with open(filename, "w", encoding="utf-8") as f:
                            f.write(data.get("data", ""))
                        log.info(f"[MetricsLogger] CSV guardado: {filename}")
                        return

                    # 3. Control de frecuencia: no saturamos el robot con más de args.freq Hz
                    #    Se aplica SOLO a los mensajes de coordenadas, no a ping/csv.
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
                        "t": round(t * 5, 1)   # el firmware espera t*5 redondeado a 1 decimal
                    }
                    enviar_comando_serial(ser, cmd)

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

            @pc.on("iceconnectionstatechange")
            async def on_ice_change():
                log.info(f"ICE estado: {pc.iceConnectionState}")
                if pc.iceConnectionState in ("failed", "closed"):
                    await pc.close()
                    
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
                    
                    # Establecemos la descripcion remota (la oferta que nos manda Unity)
                    desc = RTCSessionDescription(sdp=msg["sdp"], type="offer")
                    await pc.setRemoteDescription(desc)
                    
                    # El track de video se añade AQUI, tras setRemoteDescription,
                    # igual que en safe8. Añadirlo antes provocaría que aiortc
                    # incluya el track en el SDP local antes de conocer el remoto.
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
                        
                        if pc.remoteDescription is not None:
                            await pc.addIceCandidate(ice)
                        else:
                            # La oferta aun no ha llegado, guardamos para despues
                            candidatos_pendientes.append(ice)
                            
                    except Exception as e:
                        log.warning(f"Error procesando candidato ICE: {e}")
                
                else:
                    log.warning(f"Tipo de mensaje de señalizacion desconocido: '{tipo}'")

    except websockets.exceptions.ConnectionClosed:
        log.info("El servidor de señalizacion cerro la conexion")
    
    except OSError as e:
        log.error(f"No se pudo conectar al servidor de señalizacion en {uri}: {e}")
        
    finally:
        #---- Limpieza de recursos al salir ----
        if video_track is not None:
            video_track.detener()
        
        if ser and ser.is_open:
            ser.close()
            log.info("Puerto serial cerrado")
        
        #if pc is not None:
        #    try:
        #       await pc.close()
        #    except Exception:
        #       pass
        
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
    args = parser.parse_args()

    try:
        asyncio.run(ejecutar_webrtc(args))
    except KeyboardInterrupt:
        log.info("Detenido por el usuario (Ctrl+C).")

if __name__ == "__main__":
    main()