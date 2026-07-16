# test_websocket.py — ejecutar en el PC-VR
import asyncio
import websockets
import json

async def test():
    uri = "ws://192.168.3.27:8080"
    print(f"Conectando a {uri}...")
    try:
        async with websockets.connect(uri) as ws:
            print("✅ Conexión WebSocket establecida")
            
            # Enviar mensaje de autenticación
            auth_msg = {
                "type": "auth",
                "token": "TFG_Secret_Token_2026"
            }
            await ws.send(json.dumps(auth_msg))
            print("Enviado token de autenticación")
            
            await ws.send('{"type":"test"}')
            print("Mensaje de test enviado")
    except Exception as e:
        print(f"❌ Error: {e}")

asyncio.run(test())