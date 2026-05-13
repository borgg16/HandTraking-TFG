import asyncio
import websockets
import json
import logging

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
HOST = "0.0.0.0"
#Ponerlo todo a 0.0.0.0 significa que acepta conexiones desde cualquier IP de la red
#Si solo queremos aceptar  conexiones locales(mismo PC), usamos "127.0.0.1"

PORT = 8080
#Es un puerto arbitrario que debera coincidir con el configurado en Unity en (WebRTCManager.puertoSignaling)
#Lo normal es usar el 8080 para WebRTC

#--------------------------------------
#GESTION DE CLIENTES
#--------------------------------------

#Usaremos un set para guardar todos los clientes conectados actualmente.
#Con set evitamos duplicados automaticamente
clients : set = set()

async def handler(websocket):
    """
    Se ejecuta una vez por cada cliente que se conecta.
    Añade el cliente al set, reenvía sus mensajes al resto,
    y lo elimina cuando se desconecta.
    """
    #Identificamos al cliente por su direccion IP y puerto
    client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    clients.add(websocket)
    log.info(f"Cliente conectado: {client_id} (total: {len(clients)})")
    
    try:
        async for message in websocket:
            #Parseamos el JSON para poder logear el tipo de mensaje
            #Sin necesidad de logear el SDP completo
            try:
                data = json.loads(message)
                msg_type = data.get("type","desconocido")
                log.info(f"{client_id} -> todos: tipo='{msg_type}'")
            except json.JSONDecodeError:
                log.warning(f"Mensaje no-JSON recibido de {client_id}")
            
            #Reenviamos el mensaje a TODOS los demas clientes conectados.
            #"clients - {websocket}" excluye directamente al emisor del conjunto
            #En nuestro caso hay dos clientes (Gafas(Proyecto Unity) y el Robot)
            #Asi que cada mensaje llega exactamente al otro extremo
            destinatarios = clients - {websocket}
            if destinatarios:
                #websockets.gather envia a multiples clientes en paralelo
                await asyncio.gather(
                    *[dest.send(message) for dest in destinatarios],
                    return_exceptions=True #Si el cliente se desconecta no falla
                )
            else:
                log.warning(f"No hay destinatarios para el mensaje de {client_id}")
    
    except websockets.exceptions.ConnectionClosed as e:
        log.info(f"Cliente deconectado normalmente: {client_id} (codigo de error: {e.code})")

    except Exception as e:
        log.error(f"Error con cliente {client_id}: {e}")
    
    finally:
        #Siempre eliminamos el cliente del set, aunque haya habido error.
        #Sin esto, el set creceria indefinidamente con referencias muertas
        clients.discard(websocket)
        log.info(f"Cliente eliminado: {client_id} (total: {len(clients)})")

#--------------------------------------------------------------------------
# INICIAMOS EL SERVIDOR
#--------------------------------------------------------------------------

async def main():
    log.info(f"Iniciando servidor de señalizacion  en ws://{HOST}:{PORT}")
    log.info("Esperando conexiones de Unity y el Robot...")
    
    #websockets.serve crea el servidor WebSocket y llama a handler()
    #por cada nueva conexion entrante
    #El servidor corre indefinidamente hasta Ctrl+C
    async with websockets.serve(handler,HOST,PORT):
        log.info(f"--- SERVIDOR LISTO EN ws://{HOST}:{PORT}")
        await asyncio.Future() #Esta es la funcion que espera indefinidamente hasta Ctrl+C

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Servidor detenido por el usuario (Ctrl+C)")