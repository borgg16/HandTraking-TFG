import asyncio
from aiohttp import web, WSMsgType
import json
import logging
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Configuracion")))
import config

#Configuramos logging para ver que esta pasando sin tener que pasar por debugger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Signaling] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

#---------------------------------------
#CONFIGURACION
#---------------------------------------
HOST = config.SIGNALING_IP
PORT = config.SIGNALING_PORT
#Es un puerto arbitrario que debera coincidir con el configurado en Unity en (WebRTCManager.puertoSignaling)
#Lo normal es usar el 8080 para WebRTC

#--------------------------------------
#GESTION DE CLIENTES
#--------------------------------------

#Usaremos un set para guardar todos los clientes conectados actualmente.
#Con set evitamos duplicados automaticamente
clientes = set()

async def handler(request):
    """
    Se ejecuta una vez por cada cliente que se conecta.
    aiohttp llama a esta funcion automaticamente cuando llega una nueva conexion HTTP
    con cabecera de upgrade a WebSocket
    
    El flujo es el siguiente:
        1. Preparamos el WebSocket (Completando el handshake HTTP->WebSocket)
        2. Añadimos el cliente al set
        3. Esperamos mensajes en el bucle
        4. Cada mensaje lo reenviamos a todos los clientes (menos a mi mismo)
        5. Al desconectarse lo eliminamos del set    
    """
    # PREPARAR EL WEBSOCKET ----------------------------------------------
    ws = web.WebSocketResponse()
    #web.WebSocketResponse() es el objeto WebSocket de aiohttp
    #cuando Unity hace ConnectAsync(), llega aqui como una peticion HTTP
    #con cabecera "Upgrade: websocket". aiohttp la convierte automaticamente
    #en un WebSocket, que es lo que Unity espera
    
    await ws.prepare(request)
    #prepare() completa el handshake HTTP->WebSocket respondiendo con el codigo
    # 101 Switching protocols. Unity reconoce esta respuesta y da por establecida
    #la conexion WebSocket.
    #Sin este paso Unity no puede completar el ConnectAsync()
    
    cliente_id = f"{request.remote}"
    
    # AUTENTICACIÓN -----------------------------------------------------
    try:
        # Esperamos el primer mensaje, que debe ser el token de autenticación
        primer_msg = await ws.receive(timeout=5.0)
    except asyncio.TimeoutError:
        log.warning(f"Conexión rechazada por timeout de autenticación: {cliente_id}")
        await ws.close(code=4001, message=b"auth_timeout")
        return ws

    if primer_msg.type != WSMsgType.TEXT:
        log.warning(f"Conexión rechazada: el primer mensaje no es de tipo texto: {cliente_id}")
        await ws.close(code=4001, message=b"unauthorized")
        return ws

    try:
        auth_data = json.loads(primer_msg.data)
    except Exception:
        auth_data = {}

    if auth_data.get("type") != "auth" or auth_data.get("token") != config.SESSION_TOKEN:
        log.warning(f"Conexión rechazada: token de autenticación inválido o ausente de {cliente_id}")
        await ws.close(code=4001, message=b"unauthorized")
        return ws

    # LIMITACIÓN DE CLIENTES CONECTADOS ----------------------------------
    if len(clientes) >= 2:
        log.warning(f"Conexión rechazada: sala llena (máximo 2 clientes): {cliente_id}")
        await ws.close(code=4002, message=b"session_full")
        return ws

    # REGISTRAMOS EL CLIENTE ----------------------------------------------
    clientes.add(ws)
    log.info(f"Cliente Conectado y Autenticado: {cliente_id} (total: {len(clientes)})")
    
    # BUCLE DE RECEPCION DE MENSAJES --------------------------------------
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                #Mensaje de texto recibido, parseamos el JSON
                #Los mensajes de señalizacion son: "offer", "answer", "candidate"
                try:
                    data = json.loads(msg.data)
                    tipo = data.get("type","desconocido")
                    log.info(f"{cliente_id} -> tipo: '{tipo}'")
                except json.JSONDecodeError:
                    log.warning(f"Mensaje no-JSON recibido del cliente: {cliente_id}")
                # REENVIAMOS EL MENSAJE A TODOS LOS DEMAS
                destinatarios = [c for c in clientes if c is not ws]
                
                if destinatarios:
                    #Enviamos el mensaje tal cual al destinatario
                    for dest in destinatarios:
                        await dest.send_str(msg.data)
                else:
                    #Si no hay destinatarios, el otro extremo aun no se conecto
                    log.warning(f"No hay destinatarios, {cliente_id} esta SOLO")
            
            elif msg.type == WSMsgType.ERROR:
                #Error en el WebSocket del cliente
                log.error(f"Error WebSocket de {cliente_id}: {ws.exception()}")
                
            elif msg.type == WSMsgType.CLOSE:
                #Cliente cerro la conexion limpiamente
                log.info(f"Cliente cerro la conexion: {cliente_id}")
    
    except Exception as e:
        log.error(f"Error inesperado con {cliente_id} : {e}")
        
    finally:
        #LIMPIAMOS AL DESCONECTARSE DEL SERVER
        clientes.discard(ws) #Elimina del set sin lanzar error
        log.info(f"Cliente eliminado: {cliente_id} (total: {len(clientes)})")

    return ws


#--------------------------------------------------------------------------
# INICIAMOS EL SERVIDOR
#--------------------------------------------------------------------------

async def main():
    # Creamos la aplicacion de aiohttp ------------------------------------
    app = web.Application()
    
    # Registramos la ruta "/" ---------------------------------------------
    app.router.add_get("/",handler)
    #Cuando Unity hace ConnectAsync("ws://IP:8080"), internamente
    #hace una peticion GET a "ws://IP:8080/" con cabecera Upgrade: webSocket
    #Esta linea le dice a aiohttp que cuando llegue un GET a '/', llama a handler()
    
    # Configuramos el Runner ----------------------------------------------
    runner = web.AppRunner(app) #Gestiona el "ciclo de vida" del server
    await runner.setup()
    
    # Creamos el sitio TCP -------------------------------------------------
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    
    log.info(f"Iniciando servidor de señalizacion  en ws://{HOST}:{PORT}")
    log.info("Esperando conexiones de Unity y el Robot...")
    
    # Esperamos indefinidamente -------------------------------------------
    await asyncio.Future()
    

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Servidor detenido por el usuario (Ctrl+C)")