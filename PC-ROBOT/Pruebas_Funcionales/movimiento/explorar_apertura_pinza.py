#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Exploracion INCREMENTAL del rango real de apertura de la pinza.

No mueve el brazo: se queda quieto en una posicion fija y comoda para
observar de cerca. Cada pulsacion de tecla da UN paso pequeno (no hay
auto-repeticion ni mantener pulsado), para poder parar en el primer
signo de resistencia.

IMPORTANTE - SEGURIDAD:
  - Empieza siempre en T_OPEN=0.5 (el limite "seguro" que ya usas).
  - Cada paso es pequeno (0.05 rad por defecto, ajustable a 0.02).
  - En cuanto notes resistencia, ruido de forzado, o que la pinza no
    se mueve ya al pulsar, PARA. No sigas pulsando para "ver si cede".
  - Si algo no encaja, vuelve con 'R' al valor seguro conocido (0.5)
    y sal con Q.

Controles:
    O        -> abrir un paso (t baja)
    C        -> cerrar un paso (t sube)
    +/-      -> ajustar tamano del paso (por defecto 0.05 rad)
    R        -> volver a T_OPEN=0.5 (posicion segura conocida)
    Q / Esc  -> salir e imprimir el resumen (minimo y maximo alcanzados)

Uso:
    python explorar_apertura_pinza.py --puerto COM9
"""
import argparse, json, logging, sys, time
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
log = logging.getLogger("explorar_apertura_pinza")

# Posicion fija (comoda para observar), no se mueve durante la prueba.
X_FIJO, Y_FIJO, Z_FIJO = 22.0, 0.0, 15.0

T_OPEN_CONOCIDO = 0.5   # limite "seguro" que ya usas en el resto de scripts
T_CLOSED_CONOCIDO = 1.4  # cerrado conocido, para referencia


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


def construir_comando(t_rad) -> dict:
    return {"T": 1041, "x": int(X_FIJO * 10), "y": int(Y_FIJO * 10), "z": int(Z_FIJO * 10), "t": round(t_rad * 5, 1)}


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
    parser = argparse.ArgumentParser(description="Exploracion incremental de apertura de la pinza")
    parser.add_argument("--puerto", type=str, default=DEFAULT_SERIAL_PORT)
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--paso", type=float, default=0.05, help="Paso de t en radianes (por defecto 0.05)")
    args = parser.parse_args()

    ser = crear_conexion_serial(args.puerto, args.baudrate)

    t_actual = T_OPEN_CONOCIDO
    paso = args.paso
    t_min_alcanzado = t_actual
    t_max_alcanzado = t_actual

    enviar_comando_serial(ser, construir_comando(t_actual))
    print("\n" + "=" * 60)
    print("PRUEBA DE APERTURA - lee esto antes de tocar nada:")
    print(" - Empiezas en el limite seguro conocido (t=0.5).")
    print(" - Cada tecla mueve UN paso pequeno, nada mas.")
    print(" - Para en la PRIMERA senal de resistencia o ruido raro.")
    print(" - 'R' te devuelve al valor seguro en cualquier momento.")
    print("=" * 60)
    print(f"\nt inicial = {t_actual:.3f} rad (T_OPEN conocido)")
    print("O=abrir un paso  C=cerrar un paso  +/-=paso  R=reset  Q=salir\n")

    while True:
        tecla = leer_tecla()
        if tecla is None:
            continue

        if tecla == "o":
            t_actual = round(t_actual - paso, 3)
        elif tecla == "c":
            t_actual = round(t_actual + paso, 3)
        elif tecla == "r":
            t_actual = T_OPEN_CONOCIDO
            print("-> vuelta al valor seguro conocido (0.5)")
        elif tecla == "+":
            paso = round(paso + 0.01, 3)
        elif tecla == "-":
            paso = max(0.01, round(paso - 0.01, 3))
        elif tecla in ("q", "\x1b"):
            break
        else:
            continue

        enviar_comando_serial(ser, construir_comando(t_actual))
        t_min_alcanzado = min(t_min_alcanzado, t_actual)
        t_max_alcanzado = max(t_max_alcanzado, t_actual)

        delta_desde_open = t_actual - T_OPEN_CONOCIDO
        print(f"\rt = {t_actual:.3f} rad  (paso={paso:.2f}, {delta_desde_open:+.3f} desde T_OPEN conocido)   ", end="", flush=True)

    print(f"\n\nResumen de la sesion:")
    print(f"  t minimo alcanzado (mas abierto): {t_min_alcanzado:.3f} rad  ({t_min_alcanzado - T_OPEN_CONOCIDO:+.3f} respecto a T_OPEN=0.5)")
    print(f"  t maximo alcanzado (mas cerrado): {t_max_alcanzado:.3f} rad  ({t_max_alcanzado - T_CLOSED_CONOCIDO:+.3f} respecto a T_CLOSED=1.4)")
    print("  Anota estos valores si vas a comentarlo con tu profesor.")

    # Volver al valor seguro conocido antes de salir
    enviar_comando_serial(ser, construir_comando(T_OPEN_CONOCIDO))
    ser.close()


if __name__ == "__main__":
    main()
