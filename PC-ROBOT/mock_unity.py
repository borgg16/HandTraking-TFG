import asyncio
import json
import logging
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Mock Unity] %(message)s")
log = logging.getLogger(__name__)

URI_SIGNALING = f"ws://{config.SIGNALING_IP}:{config.SIGNALING_PORT}"

async def correr_mock_unity():
    # 1. Creamos la conexión WebRTC del lado de Unity
    pc = RTCPeerConnection()
    
    # Unity es el que abre el DataChannel ("comandos")
    channel = pc.createDataChannel("comandos")
    log.info("DataChannel 'comandos' creado localmente.")

    # Evento para recibir el feedback del brazo
    @channel.on("message")
    def on_message(message):
        log.info(f"🔄 FEEDBACK RECIBIDO DESDE EL ROBOT: {message}")

    # Evento para comprobar si el stream de vídeo del brazo llega bien
    @pc.on("track")
    def on_track(track):
        log.info(f"🎥 ¡ÉXITO! Recibiendo stream de vídeo del brazo robot ({track.kind})")

    async with websockets.connect(URI_SIGNALING) as ws:
        # Enviar mensaje de autenticación
        auth_msg = {
            "type": "auth",
            "token": config.SESSION_TOKEN
        }
        await ws.send(json.dumps(auth_msg))
        log.info("Conectado y Autenticado al servidor de señalización. Iniciando handshake...")

        # 3. Crear Oferta SDP (Simulando lo que hace Unity al arrancar)
        # Añadimos un transceptor de vídeo en modo lectura para avisar al robot que queremos su cámara
        pc.addTransceiver("video", direction="recvonly")
        oferta = await pc.createOffer()
        await pc.setLocalDescription(oferta)

        # Enviamos la oferta a través del servidor
        await ws.send(json.dumps({
            "type": "offer",
            "sdp": pc.localDescription.sdp
        }))
        log.info("Oferta SDP enviada al robot. Esperando respuesta (answer)...")

        # 4. Esperar la respuesta (Answer) del robot
        async for raw_msg in ws:
            msg = json.loads(raw_msg)
            if msg.get("type") == "answer":
                log.info("Respuesta SDP (answer) recibida del robot. Estableciendo canal WebRTC...")
                answer = RTCSessionDescription(sdp=msg["sdp"], type="answer")
                await pc.setRemoteDescription(answer)
                break # Rompemos el bucle de señalización, la conexión WebRTC ya se gestiona directa

        # 5. BATERÍA DE PRUEBAS: Inyección de coordenadas simulando tracking de manos
        log.info("Esperando a que el canal de datos esté completamente abierto...")
        while channel.readyState != "open":
            await asyncio.sleep(0.1)
        
        log.info("🚀 CANAL ABIERTO. Iniciando inyección de pruebas de posición...")

        # Lista de test cases (Coordenadas normalizadas enviadas por las gafas XR)
        # Semántica: {"x": lateral, "y": altura, "z": profundidad, "g": pinza}
        pruebas = [
            {"desc": "Postura Neutra (Centro)", "data": {"x": 0.5, "y": 0.5, "z": 0.0, "g": 1.0}},
            {"desc": "Extensión Máxima al frente", "data": {"x": 0.5, "y": 0.5, "z": 1.0, "g": 1.0}},
            {"desc": "Movimiento Izquierda y Cerrar Pinza", "data": {"x": 0.0, "y": 0.5, "z": 0.5, "g": 0.0}},
            {"desc": "Movimiento Derecha y Altura Máxima", "data": {"x": 1.0, "y": 1.0, "z": 0.2, "g": 0.5}},
            {"desc": "Límite Crítico (Forzar desborde fuera de rango)", "data": {"x": 2.5, "y": -1.5, "z": 3.0, "g": 1.0}}
        ]

        for i, test in enumerate(pruebas, 1):
            log.info(f"--- TEST {i}: {test['desc']} ---")
            payload = json.dumps(test["data"])
            log.info(f"Enviando desde Unity: {payload}")
            channel.send(payload)
            
            # Dejamos margen para que el robot procese, calcule transformXYZ y devuelva el feedback
            await asyncio.sleep(2.0)

        log.info("Batería de pruebas completada con éxito. Cerrando sesión de simulación...")
        await pc.close()

if __name__ == "__main__":
    try:
        asyncio.run(correr_mock_unity())
    except KeyboardInterrupt:
        log.info("Simulador de Unity detenido.")