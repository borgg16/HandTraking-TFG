# test_websocket.py — ejecutar en el PC-VR
import asyncio
import websockets

async def test():
    uri = "ws://192.168.1.124:8080"
    print(f"Conectando a {uri}...")
    try:
        async with websockets.connect(uri) as ws:
            print("✅ Conexión WebSocket establecida")
            await ws.send('{"type":"test"}')
            print("Mensaje enviado")
    except Exception as e:
        print(f"❌ Error: {e}")

asyncio.run(test())