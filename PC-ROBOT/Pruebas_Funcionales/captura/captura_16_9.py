#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lanzador de WebRTC con captura en 16:9 nativo y salida 640x360.

Activa la captura nativa 1280x720 del sensor RealSense D415 (FOV 69°x42°)
y reescala a 640x360 para el stream WebRTC.

Uso:
    python captura_16_9.py COM9 --ip 192.168.3.28
"""

import os
import sys
from pathlib import Path

# Asegurar que los módulos del proyecto se puedan importar
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
CONTROL_DIR = PROJECT_ROOT / "Control_Brazo"

if str(CONTROL_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROL_DIR))

# Activar modo 16:9
os.environ["MODO_16_9"] = "1"

if __name__ == "__main__":
    import safe8_WebRTC
    print("==========================================================")
    print(" [MODO 16:9] Captura nativa 1280x720 -> Salida 640x360")
    print(" NOTA: No mezclar con metricas obtenidas en modo 4:3.")
    print("==========================================================")
    safe8_WebRTC.main()
