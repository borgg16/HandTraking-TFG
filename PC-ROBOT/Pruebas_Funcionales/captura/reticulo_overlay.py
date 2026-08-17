#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lanzador de WebRTC con retículo de montaje activo (Fase P0.6).

Superpone una cruz de referencia verde y guías de mordazas/mesa sobre el vídeo
eye-in-hand para alinear la cámara respecto al efector final del robot.

Uso:
    python reticulo_overlay.py COM9 --ip 192.168.3.28
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

# Activar retículo de montaje
os.environ["MOSTRAR_RETICULO"] = "1"

if __name__ == "__main__":
    import safe8_WebRTC
    print("==========================================================")
    print(" [MODO MONTAJE P0.6] Reticulo de alineacion ACTIVO")
    print(" Cruz verde: centro de vision. Lineas amarillas: guias.")
    print(" Desactivar para sesiones de medicion reales.")
    print("==========================================================")
    safe8_WebRTC.main()
