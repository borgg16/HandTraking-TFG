# config.py — Configuración centralizada para el PC del Robot

# Token secreto compartido para la autenticación de señalización WebRTC
SESSION_TOKEN = "TFG_Secret_Token_2026"

# Parámetros del servidor de señalización
SIGNALING_IP = "192.168.3.28"
SIGNALING_PORT = 8080

# Parámetros de comunicación del hardware del robot
DEFAULT_BAUDRATE = 115200
DEFAULT_CAMERA_INDEX = 0

# ---------------------------------------------------------------------------
# CONFIGURACIÓN CÁMARA 3D (REALSENSE + DRACO)
# Pipeline de nube de puntos: PC-ROBOT/Camara3D/*.py  ->  DataChannel "nube3d"
# Documentado en PLANIFICACION_CAMARA3D_DRACO.md (apartados 5 y 10)
# ---------------------------------------------------------------------------
NUBE_HABILITADA = True           # Se puede desactivar por CLI con --sin-nube3d

REALSENSE_RESOLUCION = (640, 480)
REALSENSE_FPS = 30
REALSENSE_RANGO_Z = (0.3, 1.5)   # Recorte de profundidad en metros
REALSENSE_STRIDE = 2             # Submuestreo por pasos (equivale a 320x240)
REALSENSE_SIMULAR_SIN_CAMARA = True  # Si no hay cámara, emite una nube sintética

NUBE_MAX_PUNTOS = 60000
NUBE_FPS_OBJETIVO = 10
DRACO_QP = 11                    # Cuantización de posición
DRACO_NIVEL_COMPRESION = 1       # 1 = prioriza velocidad frente a ratio

NUBE_CHANNEL_LABEL = "nube3d"
NUBE_CHUNK_BYTES = 16384         # Chunks de 16 KiB

# Backpressure. El SCTP de aiortc es Python puro y no drena mucho más de 1-2 MB/s:
# si se deja crecer la cola de la nube, los comandos del brazo salen por detrás y el
# RTT de control se va a segundos. Con 64 KiB como máximo se acota a ~1 frame de cola.
NUBE_BUFFER_MAX_BYTES = 65536        # 64 KiB en el canal de la nube
NUBE_BUFFER_CONTROL_BYTES = 16384    # 16 KiB en el canal "comandos" (tiene prioridad)

NUBE_REGISTRAR_CSV = True        # Guarda nube3d_robot_<sesion>.csv en Resultados_Nube3D
