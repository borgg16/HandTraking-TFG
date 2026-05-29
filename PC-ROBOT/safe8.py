import cv2
import mediapipe as mp
import math
import serial
import argparse
import time
import json
from collections import deque
import random

# ===================== CONFIGURACIÓN =====================

TRACE_ENABLED = False

# Distancia real entre nudillos índice y meñique (mídela en tu mano)
HAND_BASE_CM = 8.0       # cm  <-- AJUSTA ESTO
FOCAL_PX     = 800.0     # px  <-- AJUSTA ESTO CON CALIBRACIÓN

# Límites de seguridad para el brazo (en cm)
X_MIN, X_MAX = 5.0, 40.0
Y_MIN, Y_MAX = -40.0, 40.0
Z_MIN, Z_MAX = -10.0, 50.0

def transformXYZ(X_cm, Y_cm, Z_cm):
    X2_cm = (150 - Z_cm )
    Z2_cm = 10 - (Y_cm)
    Y2_cm = X_cm
    return X2_cm, Y2_cm, Z2_cm

# Configuración de la pinza (ángulo t)
T_OPEN   = 0.5     # pinza completamente abierta
T_CLOSED = 1.4     # pinza cerrada (aprox. 80°)

# Rangos para la normalización de la distancia índice–pulgar
MIN_TIP_RATIO = 0.3   # dedos muy juntos
MAX_TIP_RATIO = 0.8   # dedos muy separados

# ID de landmarks que usaremos
mp_hands = mp.solutions.hands
WRIST_LM      = mp_hands.HandLandmark.WRIST
INDEX_MCP_LM  = mp_hands.HandLandmark.INDEX_FINGER_MCP
PINKY_MCP_LM  = mp_hands.HandLandmark.PINKY_MCP
INDEX_TIP_LM  = mp_hands.HandLandmark.INDEX_FINGER_TIP
THUMB_TIP_LM  = mp_hands.HandLandmark.THUMB_TIP

# Para detectar dedos extendidos
THUMB_IP_LM   = mp_hands.HandLandmark.THUMB_IP
INDEX_PIP_LM  = mp_hands.HandLandmark.INDEX_FINGER_PIP
MIDDLE_PIP_LM = mp_hands.HandLandmark.MIDDLE_FINGER_PIP
RING_PIP_LM   = mp_hands.HandLandmark.RING_FINGER_PIP
PINKY_PIP_LM  = mp_hands.HandLandmark.PINKY_PIP


def clamp(v, vmin, vmax):
    return max(vmin, min(vmax, v))

#------ COMUNICACION SERIAL --------------------
def crear_conexion_serial(puerto, baudrate= 115200):
    """
    Abre la conexion con el robot por puerto serial
    
    puerto: 'COM3','COM4'...
    baudrate: velocidad de comunicacion. Por defecto RoArm M2 usa 115200.
    
    timeout=1: si no hay respuesta en 1 segundo, no se bloquea indefinidamente.
    """
    try:
        ser = serial.Serial(puerto, baudrate, timeout=1)
        time.sleep(2)
        #El sleep de 2 segundos es necesario porque algunos Arduinos/ESP32 se reinician
        #al conectarlo por puerto serie y necesitan un tiempo para volver a arrancar
        print(f"CONEXION SERIAL ABIERTA: {puerto} @ {baudrate} baud")
        return ser
    except serial.SerialException as e:
        print(f"ERROR ABRIENDO PUERTO SERIAL {puerto}: {e}")
        return None


def enviar_comando_serial(ser,data):
    """
    Envia un diccionario JSON al robot por puerto serial.
    
    Añadimos '\n' al final porque el firmware del robot usa el salto de línea
    como delimitador de mensaje, sabe que el comando está completo cuando
    recibe '\n', igual que una terminal de comandos.
    
    encode('utf-8'): convierte el string a bytes, que es lo que el puerto
    serial puede transmitir (los puertos serial trabajan con bytes, no strings).
    """
    try:
        json_str = json.dumps(data) + '\n'
        ser.write(json_str.encode('utf-8'))

        if TRACE_ENABLED:
            print(f"SERIAL SEND: {json_str.strip()}")

        # readline() espera hasta recibir '\n' o hasta que pase el timeout.
        # Si el robot no responde, simplemente devuelve b'' sin bloquear.
        respuesta = ser.readline().decode('utf-8', errors='ignore').strip()
        if respuesta and TRACE_ENABLED:
            print(f"SERIAL RECV: {respuesta}")

        return respuesta

    except serial.SerialException as e:
        print(f"[SERIAL] Error enviando comando: {e}")
        return None



def calcular_xyz_cm(hand_landmarks, image_shape):
    """Calcula X, Y, Z en cm a partir de:
    - base de la mano (nudillos índice-meñique)
    - modelo de cámara pinhole
    """
    h, w, _ = image_shape
    cx, cy = w / 2.0, h / 2.0

    wrist     = hand_landmarks.landmark[WRIST_LM]
    index_mcp = hand_landmarks.landmark[INDEX_MCP_LM]
    pinky_mcp = hand_landmarks.landmark[PINKY_MCP_LM]

    p_wrist = (wrist.x * w, wrist.y * h)
    p_index = (index_mcp.x * w, index_mcp.y * h)
    p_pinky = (pinky_mcp.x * w, pinky_mcp.y * h)

    base_px = math.dist(p_index, p_pinky)

    if base_px <= 0:
        return None, None, None, (p_wrist, p_index, p_pinky), base_px

    # Profundidad aproximada Z en cm
    Z_cm = (FOCAL_PX * HAND_BASE_CM) / base_px

    # Tomamos como punto de referencia la muñeca
    u, v = p_wrist

    # Conversión a X, Y en cm (respecto al centro de la imagen)
    X_cm = (u - cx) * Z_cm / FOCAL_PX
    Y_cm = (v - cy) * Z_cm / FOCAL_PX

    return X_cm, Y_cm, Z_cm, (p_wrist, p_index, p_pinky), base_px


def calcular_angulo_pinza(hand_landmarks, image_shape, base_px):
    """Calcula el ángulo t de la pinza en función de la distancia
    entre punta de índice y punta de pulgar, normalizada por base_px.
    Devuelve t en radianes.
    """
    h, w, _ = image_shape

    index_tip = hand_landmarks.landmark[INDEX_TIP_LM]
    thumb_tip = hand_landmarks.landmark[THUMB_TIP_LM]

    p_index_tip = (index_tip.x * w, index_tip.y * h)
    p_thumb_tip = (thumb_tip.x * w, thumb_tip.y * h)

    tip_dist_px = math.dist(p_index_tip, p_thumb_tip)

    if base_px <= 0:
        return None, tip_dist_px

    # Distancia relativa normalizada por el tamaño de la mano
    ratio = tip_dist_px / base_px

    # Normalización a [0, 1]
    norm = (ratio - MIN_TIP_RATIO) / (MAX_TIP_RATIO - MIN_TIP_RATIO)
    norm = clamp(norm, 0.0, 1.0)

    # mapeo: dedos juntos  -> pinza cerrada
    #        dedos abiertos -> pinza abierta
    t = T_CLOSED + (T_OPEN - T_CLOSED) * norm

    return t, ratio


# ===================== GESTOS MANO IZQUIERDA =====================

def obtener_dedos_extendidos(hand_landmarks, image_shape, handed_label):
    """
    Devuelve un diccionario con qué dedos están extendidos.
    handed_label: 'Left' o 'Right'
    """
    h, w, _ = image_shape

    lm = hand_landmarks.landmark

    # Coordenadas en píxeles
    def p(idx):
        return lm[idx].x * w, lm[idx].y * h

    thumb_tip_x, thumb_tip_y = p(THUMB_TIP_LM)
    thumb_ip_x,  thumb_ip_y  = p(THUMB_IP_LM)

    index_tip_x, index_tip_y = p(INDEX_TIP_LM)
    index_pip_x, index_pip_y = p(INDEX_PIP_LM)

    middle_tip_x, middle_tip_y = p(mp_hands.HandLandmark.MIDDLE_FINGER_TIP)
    middle_pip_x, middle_pip_y = p(MIDDLE_PIP_LM)

    ring_tip_x, ring_tip_y = p(mp_hands.HandLandmark.RING_FINGER_TIP)
    ring_pip_x, ring_pip_y = p(RING_PIP_LM)

    pinky_tip_x, pinky_tip_y = p(mp_hands.HandLandmark.PINKY_TIP)
    pinky_pip_x, pinky_pip_y = p(PINKY_PIP_LM)

    # Para índice, corazón, anular y meñique:
    # dedo extendido si la punta está POR ENCIMA (menor y) que la articulación PIP
    index_extended  = index_tip_y  < index_pip_y
    middle_extended = middle_tip_y < middle_pip_y
    ring_extended   = ring_tip_y   < ring_pip_y
    pinky_extended  = pinky_tip_y  < pinky_pip_y

    # Para el pulgar usamos la coordenada X.
    # Si la mano es izquierda, el pulgar extendido suele ir hacia la derecha (x mayor).
    # Si la mano es derecha, hacia la izquierda (x menor).
    if handed_label == "Left":
        thumb_extended = thumb_tip_x > thumb_ip_x
    else:
        thumb_extended = thumb_tip_x < thumb_ip_x

    return {
        "thumb": thumb_extended,
        "index": index_extended,
        "middle": middle_extended,
        "ring": ring_extended,
        "pinky": pinky_extended,
    }


def detectar_gesto_mano_izquierda(hand_landmarks, image_shape, handed_label="Left"):
    """
    Detecta el gesto de la mano izquierda según:
      - PUÑO
      - OK (solo pulgar)
      - 1 (solo índice)
      - 2 (índice + corazón)
      - 3 (índice + corazón + anular)
      - 4 (índice + corazón + anular + meñique)
    Devuelve un string con el nombre del gesto, o None si no coincide.
    """
    dedos = obtener_dedos_extendidos(hand_landmarks, image_shape, handed_label)

    thumb  = dedos["thumb"]
    index  = dedos["index"]
    middle = dedos["middle"]
    ring   = dedos["ring"]
    pinky  = dedos["pinky"]

    # Puño: todos cerrados
    if not thumb and not index and not middle and not ring and not pinky:
        return "PUÑO"

    # OK: solo pulgar extendido
    if thumb and not index and not middle and not ring and not pinky:
        return "OK"

    # 1 dedo: solo índice
    if not thumb and index and not middle and not ring and not pinky:
        return "1"

    # 2 dedos: índice + corazón
    if (not thumb and index and middle and
        not ring and not pinky):
        return "2"

    # 3 dedos: índice + corazón + anular
    if (not thumb and index and middle and ring and
        not pinky):
        return "3"

    # 4 dedos: índice + corazón + anular + meñique
    if (not thumb and index and middle and ring and pinky):
        return "4"

    return None


# ===================== MAIN =====================

def main():
    parser = argparse.ArgumentParser(description="Control del RoArm M2 con mano (Mediapipe + HTTP)")
    parser.add_argument("puerto", type=str, help="Puerto serial del robot. Ejemplo: COM3")
    parser.add_argument("--baudrate", type=int, default=115200, help="Velocidad del puerto serial (default: 115200)")
    parser.add_argument("--camera", type=int, default=0, help="Índice de cámara (0 por defecto)")
    parser.add_argument("--freq", type=float, default=50.0,
                        help="Frecuencia máxima de envío de comandos (Hz)")
    args = parser.parse_args()

    cam_index = args.camera
    max_hz = args.freq
    min_dt = 1.0 / max_hz if max_hz > 0 else 0.0
    
    #Abrimos la conexion serial
    ser = crear_conexion_serial(args.puerto, args.baudrate)
    if ser is None:
        return #Si conexion serial falla no podemos seguir


#---- CAMARA -------------------------------------------------
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        print("❌ No se pudo abrir la cámara")
        ser.close()
        return

    width  = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    print("Resolución actual:", width, "x", height)

    #cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    #cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FOCAL_PX/2)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FOCAL_PX/4)

#---- MEDIAPIPE -----------------------------------------------
    # Ahora permitimos hasta 2 manos
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.9,
        min_tracking_confidence=0.8
    )
    mp_draw = mp.solutions.drawing_utils

#---- VARIABLES DE CONTROL -----------------------------------

    last_send_time = 0.0
    max_interval_total = 0.0              # <<< máximo intervalo global
    comandos = deque()                    # <<< guarda tiempos de envío (último segundo)

    print("✅ Empezando. Pulsa 'q' para salir.")

    # Para que el cuadro se mantenga entre frames
    rect_pos = None  # (x, y, w, h)

    texto3 = ""
    numComandos = 0

#---- BUCLE PRINCIPAL ---------------------------------------

    while True:
        startTime= time.time()
        print("0.{0}".format(time.time()-startTime))
        ret, frame = cap.read()
        print("1.{0}".format(time.time()-startTime))
        if not ret:
            print("No se pudo leer la cámara")
            break
        print("2.{0}".format(time.time()-startTime))
      
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        print("3.{0}".format(time.time()-startTime))
        
        # Procesar solo 1 de cada 2 frames (cámbialo a 3 si quieres aún más rápido)
        #if frame_idx % 2 == 0:
        #    last_result = hands.process(frame_rgb)

        #frame_idx += 1
        #result = last_result  # reutilizamos el último resultado válido
        result = hands.process(frame_rgb)
        
        print("4.{0}".format(time.time()-startTime))
        h, w, _ = frame.shape

        # Dibujar rectángulo si existe
        if rect_pos is not None:
            rx, ry, rw, rh = rect_pos
            cv2.rectangle(frame, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)

        if result.multi_hand_landmarks:
            # Emparejamos landmarks con handedness (izquierda/derecha)
            for hand_landmarks, handedness in zip(result.multi_hand_landmarks,
                                                  result.multi_handedness):
                label = handedness.classification[0].label  # "Left" o "Right"
                #swap if mirror camera
                label = "Left" if (label=="Right") else "Right"
                print(label)

                # Dibuja la mano
                mp_draw.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

                # =========== MANO DERECHA: CONTROL ROBOT ===========
                if label == "Right":
                    X_cm, Y_cm, Z_cm, (p_wrist, p_index, p_pinky), base_px = \
                        calcular_xyz_cm(hand_landmarks, frame.shape)

                    if X_cm is not None:
                        X2_cm, Y2_cm, Z2_cm = transformXYZ(X_cm, Y_cm, Z_cm)

                        # Calcular ángulo de la pinza según índice–pulgar
                        t_angle, tip_ratio = calcular_angulo_pinza(
                            hand_landmarks, frame.shape, base_px
                        )

                        # Limitar a la zona segura
                        X_safe = clamp(X2_cm, X_MIN, X_MAX)
                        Y_safe = clamp(Y2_cm, Y_MIN, Y_MAX)
                        Z_safe = clamp(Z2_cm, Z_MIN, Z_MAX)

                        # Texto en pantalla XYZ
                        texto1 = (
                            f"R(X)={int(X_cm*10)}/{int(X_safe*10)}mm  "
                            f"Y={int(Y_cm*10)}/{int(Y_safe*10)}mm  "
                            f"Z={int(Z_cm*10)}/{int(Z_safe*10)}mm"
                        )
                        cv2.putText(frame, texto1, (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

                        # Texto pinza
                        if t_angle is not None:
                            texto2 = f"Right ratio={tip_ratio:.2f}  t={t_angle:.2f} rad"
                            cv2.putText(frame, texto2, (10, 55),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                        # Enviar comando al robot limitado en frecuencia
                        now = time.time()
                        if now - last_send_time >= min_dt:
  # <<< calcular intervalo desde el último comando
                            prev_send_time = last_send_time
                            last_send_time = now
                            if prev_send_time > 0.0:
                                intervalo = now - prev_send_time
                                if intervalo > max_interval_total:
                                    max_interval_total = intervalo
                            cmd = {
                                "T": 1041,
                                "x": int(X_safe * 10),
                                "y": int(Y_safe * 10),
                                "z": int(Z_safe * 10),
                                "t": int(t_angle * 5) if t_angle is not None else 0.0
                            }
                            
                            print("5.{0}".format(time.time()-startTime))   
                            resp = enviar_comando_serial(ser, cmd)

                            if resp is not None and TRACE_ENABLED:
                                print(f"SEND (Right): {cmd}  RECV: {resp}")
                            last_receive_time = now

                            comandos.append((last_send_time, last_receive_time))

                            
                            # limpiar comandos más antiguos de 1 segundo
                            if int(comandos[0][1]) < int(comandos[len(comandos)-1][1]):
                                print("first/last command timestamp:",
                                      int(comandos[0][1]),
                                      int(comandos[len(comandos)-1][1]))

                                numComandos = len(comandos)
                                print("Comandos enviados en el último segundo:", numComandos)
                                while comandos and len(comandos) > 0:
                                    comandos.popleft()

  							# <<< calcular max intervalo en el último segundo
                            if len(comandos) >= 2:
                                max_interval_last_sec = 0.0
                                for i in range(1, len(comandos)):
                                    dt = comandos[i][1] - comandos[i - 1][1]
                                    if dt > max_interval_last_sec:
                                        max_interval_last_sec = dt
                            else:
                                max_interval_last_sec = 0.0

                            #texto2=print("Comandos últimos 1s:", len(comandos),
                            #      "| Max intervalo último 1s: {:.3f} s".format(max_interval_last_sec),
                            #      "| Max intervalo total: {:.3f} s".format(max_interval_total))
                            
                            texto3 = (
                                f"Cmds 1s: {numComandos}  "
                                f"Max1s: {max_interval_last_sec:.3f}s  "
                                f"MaxTot: {max_interval_total:.3f}s"
                            )
 


                # =========== MANO IZQUIERDA: SOLO GESTOS ===========
                elif label == "Left":
                    gesto = detectar_gesto_mano_izquierda(hand_landmarks, frame.shape, "Left")

                    # Posición aproximada para escribir el texto (muñeca)
                    wrist = hand_landmarks.landmark[WRIST_LM]
                    wx, wy = int(wrist.x * w), int(wrist.y * h)

                    if gesto is not None:
                        texto_gesto = f"Left: {gesto}"
                    else:
                        texto_gesto = "Left: gesto desconocido"

                    cv2.putText(frame, texto_gesto, (wx - 40, wy - 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

                    # Si quieres, aquí puedes mapear cada gesto a alguna acción
                    # (por ahora solo mostramos por pantalla y en consola)
                    print("Gesto mano izquierda:", texto_gesto)


        cv2.putText(frame, texto3, (10, 75),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        
        print("6.{0}".format(time.time()-startTime))
        cv2.imshow("Hand -> Robot", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break

        
        print("7.{0}".format(time.time()-startTime))
        # Si se pulsa 'r', generar nueva posición aleatoria
        if key == ord('r'):
            h, w, _ = frame.shape

            # Tamaño del rectángulo = 1/16 del área total
            rect_w = w // 16
            rect_h = h // 16

            # Aseguramos que el rectángulo cabe dentro de la imagen
            max_x = w - rect_w
            max_y = h - rect_h

            x = random.randint(0, max_x)
            y = random.randint(0, max_y)

            rect_pos = (x, y, rect_w, rect_h)
            print(f"Nuevo rectángulo en x={x}, y={y}, w={rect_w}, h={rect_h}")
        
        print("8.{0}".format(time.time()-startTime))

    cap.release()
    cv2.destroyAllWindows()

    # AÑADIDO: cerramos el puerto serial limpiamente al salir
    if ser and ser.is_open:
        ser.close()
        print("Puerto serial cerrado")


if __name__ == "__main__":
    main()
