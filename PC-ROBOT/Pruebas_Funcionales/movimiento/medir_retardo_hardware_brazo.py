#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
medir_retardo_hardware_brazo.py — Medición de Retardo de Actuación Hardware del Brazo Robótico.

Diseñado para medir con precisión el retardo puro de hardware (PC -> Serie UART -> ESP32 -> Servomotores)
sin la sobrecarga de WebRTC ni Unity:
 1. Sitúa el brazo en una posición inicial de referencia.
 2. Espera a que el operador pulse la tecla INTRO (o Espacio).
 3. En el instante exacto de la pulsación, envía de forma inmediata un comando de movimiento en escalón
    (salto directo y perceptible en el eje seleccionado) y registra la marca de tiempo de alta resolución.
 4. Permite grabar a cámara lenta (ej. 240 FPS) enfocando la mano pulsando el INTRO y el brazo robótico
    para analizar la diferencia fotograma a fotograma con el script de análisis de latencia.

Uso:
    python PC-ROBOT/Pruebas_Funcionales/movimiento/medir_retardo_hardware_brazo.py --puerto COM9
    python PC-ROBOT/Pruebas_Funcionales/movimiento/medir_retardo_hardware_brazo.py --puerto COM9 --eje y --amplitud 10
    python PC-ROBOT/Pruebas_Funcionales/movimiento/medir_retardo_hardware_brazo.py --puerto COM9 --audio-beep
"""

import argparse
import csv
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

# Configurar rutas y módulos del proyecto
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parents[1]
CONFIG_DIR = PROJECT_ROOT / "Configuracion"
RESULTADOS_DIR = CURRENT_DIR.parent / "resultados" / "M1" / "retardo_hardware"

if str(CONFIG_DIR) not in sys.path:
    sys.path.insert(0, str(CONFIG_DIR))

try:
    import config as central_config
    DEFAULT_BAUDRATE = getattr(central_config, "DEFAULT_BAUDRATE", 115200)
    DEFAULT_SERIAL_PORT = getattr(central_config, "DEFAULT_SERIAL_PORT", "COM9")
except ImportError:
    DEFAULT_BAUDRATE = 115200
    DEFAULT_SERIAL_PORT = "COM9"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("retardo_hardware")

# Límites de seguridad del robot (cm)
X_MIN, X_MAX = 5.0, 40.0
Y_MIN, Y_MAX = -40.0, 40.0
Z_MIN, Z_MAX = -10.0, 50.0

T_OPEN = 0.35
T_CLOSED = 1.40


def clamp(v, vmin, vmax):
    return max(vmin, min(vmax, v))


def emitir_beep():
    """Emite un pitido corto si estamos en Windows para servir de sincronización por audio en el vídeo."""
    try:
        if sys.platform == "win32":
            import winsound
            winsound.Beep(1200, 70)
    except Exception:
        pass


def crear_conexion_serial(puerto: str, baudrate: int = 115200):
    import serial
    try:
        log.info(f"Conectando al brazo robótico en {puerto} a {baudrate} baudios...")
        ser = serial.Serial(puerto, baudrate, timeout=0.1, write_timeout=0.1)
        time.sleep(2.0)
        log.info("Conexión serie establecida correctamente.")
        return ser
    except Exception as e:
        log.error(f"Error al abrir el puerto {puerto}: {e}")
        return None


def enviar_comando_directo(ser, x_cm: float, y_cm: float, z_cm: float, t_rad: float = T_OPEN) -> dict:
    """Envía un comando de posición directa en escalón (sin interpolación previa en Python)."""
    cx = clamp(x_cm, X_MIN, X_MAX)
    cy = clamp(y_cm, Y_MIN, Y_MAX)
    cz = clamp(z_cm, Z_MIN, Z_MAX)
    
    cmd = {
        "T": 1041,
        "x": int(cx * 10),
        "y": int(cy * 10),
        "z": int(cz * 10),
        "t": round(t_rad * 5, 1)
    }
    
    if ser is not None and ser.is_open:
        json_bytes = (json.dumps(cmd) + "\n").encode("utf-8")
        ser.write(json_bytes)
        ser.flush()
    return cmd


def main():
    parser = argparse.ArgumentParser(
        description="Medición de retardo de actuación de hardware del brazo robótico por pulsación de INTRO."
    )
    parser.add_argument("--puerto", type=str, default=DEFAULT_SERIAL_PORT,
                        help=f"Puerto serie del robot (default: {DEFAULT_SERIAL_PORT})")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE,
                        help=f"Velocidad de comunicación serie (default: {DEFAULT_BAUDRATE})")
    parser.add_argument("--eje", type=str, choices=["y", "z", "x", "diagonal"], default="y",
                        help="Eje de movimiento para el escalón detectable (default: y)")
    parser.add_argument("--amplitud", type=float, default=12.0,
                        help="Amplitud del desplazamiento en cm (default: 12.0 cm)")
    parser.add_argument("--x-base", type=float, default=20.0,
                        help="Coordenada X base en cm (default: 20.0)")
    parser.add_argument("--y-base", type=float, default=0.0,
                        help="Coordenada Y base en cm (default: 0.0)")
    parser.add_argument("--z-base", type=float, default=15.0,
                        help="Coordenada Z base en cm (default: 15.0)")
    parser.add_argument("--audio-beep", action="store_true", default=False,
                        help="Emitir un pitido de audio en el momento de la pulsación para sincronización auditiva")
    
    args = parser.parse_args()

    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp_sesion = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTADOS_DIR / f"registro_retardo_hardware_{timestamp_sesion}.csv"

    # Definir las dos posturas A y B según el eje seleccionado
    x0, y0, z0 = args.x_base, args.y_base, args.z_base
    amp = args.amplitud

    if args.eje == "y":
        pos_a = (x0, y0 - amp / 2.0, z0)
        pos_b = (x0, y0 + amp / 2.0, z0)
    elif args.eje == "z":
        pos_a = (x0, y0, z0 - amp / 2.0)
        pos_b = (x0, y0, z0 + amp / 2.0)
    elif args.eje == "x":
        pos_a = (x0 - amp / 2.0, y0, z0)
        pos_b = (x0 + amp / 2.0, y0, z0)
    else:  # diagonal
        pos_a = (x0, y0 - amp / 2.0, z0 - amp / 2.0)
        pos_b = (x0, y0 + amp / 2.0, z0 + amp / 2.0)

    log.info("=" * 70)
    log.info("  PROTOCOLO DE MEDICIÓN DE RETARDO HARDWARE (CÁMARA LENTA)")
    log.info("=" * 70)
    log.info(f"Eje de salto: {args.eje.upper()} | Amplitud: {amp} cm")
    log.info(f"Postura A: ({pos_a[0]:.1f}, {pos_a[1]:.1f}, {pos_a[2]:.1f}) cm")
    log.info(f"Postura B: ({pos_b[0]:.1f}, {pos_b[1]:.1f}, {pos_b[2]:.1f}) cm")
    log.info(f"Archivo de registro CSV: {csv_path}")
    log.info("=" * 70)

    ser = crear_conexion_serial(args.puerto, args.baudrate)
    if ser is None:
        log.error("No se pudo iniciar la conexión serie. Revisa el puerto y la alimentación del brazo.")
        sys.exit(1)

    # Posicionar inicialmente en Postura A
    log.info(f"Moviendo inicialmente a Postura A: {pos_a}...")
    enviar_comando_directo(ser, pos_a[0], pos_a[1], pos_a[2], T_OPEN)
    time.sleep(2.0)
    log.info("Brazo listo y estabilizado en posición inicial.")

    registros = []
    estado_actual = "A"  # Alternará entre "A" y "B"
    ensayo_num = 0

    print("\n" + "#" * 70)
    print(" INSTRUCCIONES:")
    print(" 1. Inicia la grabación a 240 FPS enfocando tu mano (sobre INTRO) y el brazo.")
    print(" 2. Pulsa [INTRO] cada vez que desees disparar un ensayo de movimiento.")
    print(" 3. Escribe 'r' + [INTRO] para recolocar el brazo sin registrar ensayo.")
    print(" 4. Escribe 'q' + [INTRO] para finalizar la prueba y salir.")
    print("#" * 70 + "\n")

    try:
        while True:
            siguiente_estado = "B" if estado_actual == "A" else "A"
            pos_destino = pos_b if siguiente_estado == "B" else pos_a
            
            prompt_str = f"[Ensayo #{ensayo_num + 1}] Pulsa [INTRO] para mover hacia Postura {siguiente_estado} (o 'q' para salir): "
            user_input = input(prompt_str).strip().lower()

            t_pulsacion_perf = time.perf_counter()
            t_pulsacion_iso = datetime.datetime.now().isoformat()

            if user_input == 'q':
                log.info("Finalizando sesión de ensayos a petición del usuario.")
                break

            if user_input == 'r':
                log.info(f"Recolocando a Postura A: {pos_a}...")
                enviar_comando_directo(ser, pos_a[0], pos_a[1], pos_a[2], T_OPEN)
                estado_actual = "A"
                time.sleep(1.5)
                continue

            # Ejecutar disparo instantáneo
            ensayo_num += 1
            cmd_enviado = enviar_comando_directo(ser, pos_destino[0], pos_destino[1], pos_destino[2], T_OPEN)
            
            if args.audio_beep:
                emitir_beep()

            log.info(f">>> [DISPARO #{ensayo_num}] Comando enviado instantáneamente a las {datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} -> Destino: Postura {siguiente_estado} {pos_destino}")

            # Guardar en registro
            registro_item = {
                "ensayo_num": ensayo_num,
                "timestamp_iso": t_pulsacion_iso,
                "perf_counter_s": round(t_pulsacion_perf, 6),
                "estado_origen": estado_actual,
                "estado_destino": siguiente_estado,
                "eje": args.eje,
                "amplitud_cm": amp,
                "x_target": pos_destino[0],
                "y_target": pos_destino[1],
                "z_target": pos_destino[2],
                "cmd_json": json.dumps(cmd_enviado)
            }
            registros.append(registro_item)
            estado_actual = siguiente_estado

            # Pequeña pausa de estabilización antes del siguiente prompt
            time.sleep(0.5)

    except KeyboardInterrupt:
        log.info("\nInterrupción por teclado detectada.")
    finally:
        # Guardar CSV si hubo ensayos
        if registros:
            campos = list(registros[0].keys())
            with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=campos)
                writer.writeheader()
                writer.writerows(registros)
            log.info(f"Registro de {len(registros)} ensayos guardado en: {csv_path}")

        # Retornar a posición de reposo segura
        if ser is not None and ser.is_open:
            log.info("Regresando el brazo a posición de reposo segura (20, 0, 20)...")
            enviar_comando_directo(ser, 20.0, 0.0, 20.0, T_OPEN)
            time.sleep(1.5)
            ser.close()
            log.info("Puerto serie cerrado con éxito.")

    log.info("Prueba finalizada.")


if __name__ == "__main__":
    main()
