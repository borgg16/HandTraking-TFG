"""
conftest.py - Preparacion del entorno de tests para PC-ROBOT.

Los tests se ejecutan con el venv del proyecto activado (donde estan
instaladas cv2, pyserial, websockets, aiortc y av), por lo que
'import safe8_WebRTC' funciona directamente, sin stubs.

Lo unico necesario aqui es anadir PC-ROBOT/Control_Brazo a sys.path
(ruta relativa a ESTE fichero, no al directorio desde el que se lance
pytest) para poder importar safe8_WebRTC. El propio safe8_WebRTC anade
por su cuenta Configuracion/ para resolver su 'import config'.
"""
import os
import sys

CONTROL_BRAZO_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "Control_Brazo")
)
if CONTROL_BRAZO_DIR not in sys.path:
    sys.path.insert(0, CONTROL_BRAZO_DIR)
