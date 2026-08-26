#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calibración interactiva de z_mesa (P0.4) y comprobación del sentido de +Y.

Controles:
    O        -> abrir pinza (para meter/sacar el rotulador)
    C        -> cerrar pinza (sujeta el rotulador)
    W / S    -> subir / bajar Z (paso configurable, default 0.5 cm)
    A / D    -> mover Y- / Y+ (para ver hacia qué lado se mueve el brazo)
    R / F    -> mover X- / X+
    +/-      -> aumentar / reducir el paso
    Q / Esc  -> salir e imprimir la posición final

Uso:
    python calibrar_zmesa_y_ejes.py --puerto COM9
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
CONFIG_DIR = PROJECT_ROOT / "Configuracion"
if str(CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR))

try:
    import config as central_config
    DEFAULT_BAUDRATE = getattr(central_config, "DEFAULT_BAUDRATE", 115200)
    DEFAULT_SERIAL_PORT = getattr(central_config, "DEFAULT_SERIAL_PORT", "COM9")
except ImportError:
    DEFAULT_BAUDRATE = 115200
    DEFAULT_SERIAL_PORT = "COM9"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("calibrar_zmesa_y_ejes")

X_MIN, X_MAX = 5.0, 40.0
Y_MIN, Y_MAX = -40.0, 40.0
Z_MIN, Z_MAX = -10.0, 50.0
T_OPEN, T_CLOSED = 0.5, 1.4


def clamp(v, vmin, vmax):
    return max(vmin, min(vmax, v))


def crear_conexion_serial(puerto, baudrate=115200):
    import serial
    log.info(f"Abriendo puerto serie {puerto} a {baudrate} baudios...")
    ser = serial.Serial(puerto, baudrate, timeout=1)
    time.sleep(2)
    log.info("Conexion serie establecida.")
    return ser


def enviar_comando_serial(ser, data: dict) -> str:
    json_str = json.dumps(data) + "\n"
    ser.write(json_str.encode("utf-8"))
    return ser.readline().decode("utf-8", errors="ignore").strip()


def construir_comando(x_cm, y_cm, z_cm, t_rad) -> dict:
    cx = clamp(x_cm, X_MIN, X_MAX)
    cy = clamp(y_cm, Y_MIN, Y_MAX)
    cz = clamp(z_cm, Z_MIN, Z_MAX)
    return {"T": 1041, "x": int(cx * 10), "y": int(cy * 10), "z": int(cz * 10), "t": round(t_rad * 5, 1)}


def leer_tecla():
    import msvcrt
    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):
        msvcrt.getch()
        return None
    try:
        return ch.decode("utf-8").lower()
    except UnicodeDecodeError:
        return None


def main():
    parser = argparse.ArgumentParser(description="Calibracion interactiva de z_mesa y sentido de +Y")
    parser.add_argument("--puerto", type=str, default=DEFAULT_SERIAL_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--x", type=float, default=22.0, help="X inicial en cm")
    parser.add_argument("--y", type=float, default=0.0, help="Y inicial en cm")
    parser.add_argument("--z", type=float, default=15.0, help="Z inicial en cm (por encima del papel)")
    parser.add_argument("--paso", type=float, default=0.5, help="Paso de movimiento en cm")
    args = parser.parse_args()

    ser = crear_conexion_serial(args.puerto, args.baudrate)

    x, y, z = args.x, args.y, args.z
    paso = args.paso
    t_rad = T_OPEN
    pinza = "ABIERTA"

    cmd = construir_comando(x, y, z, t_rad)
    enviar_comando_serial(ser, cmd)
    print(f"\nPosicion inicial X={x:.1f} Y={y:.1f} Z={z:.1f}  Pinza={pinza}  Paso={paso:.1f}cm")
    print("O=abrir C=cerrar  W/S=Z+/-  A/D=Y-/Y+  R/F=X-/X+  +/-=paso  Q/Esc=salir\n")

    while True:
        tecla = leer_tecla()
        if tecla is None:
            continue

        if tecla == "o":
            t_rad, pinza = T_OPEN, "ABIERTA"
        elif tecla == "c":
            t_rad, pinza = T_CLOSED, "CERRADA"
        elif tecla == "w":
            z += paso
        elif tecla == "s":
            z -= paso
        elif tecla == "a":
            y -= paso
        elif tecla == "d":
            y += paso
        elif tecla == "r":
            x -= paso
        elif tecla == "f":
            x += paso
        elif tecla == "+":
            paso = round(paso + 0.1, 2)
        elif tecla == "-":
            paso = max(0.1, round(paso - 0.1, 2))
        elif tecla in ("q", "\x1b"):
            break
        else:
            continue

        cmd = construir_comando(x, y, z, t_rad)
        enviar_comando_serial(ser, cmd)
        print(f"\rX={x:6.1f}  Y={y:6.1f}  Z={z:6.1f}  Pinza={pinza:8s}  Paso={paso:.1f}cm   ", end="", flush=True)

    print(f"\n\nPosicion final: X={x:.2f}  Y={y:.2f}  Z={z:.2f}")
    print("Si el roturador ya tocaba el papel, Z es tu z_mesa.")
    ser.close()


if __name__ == "__main__":
    main()
