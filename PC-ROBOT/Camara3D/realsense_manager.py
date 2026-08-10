# realsense_manager.py — Captura y deproyección de la nube de puntos
"""
Envuelve la Intel RealSense (pyrealsense2) y entrega, por cada frame, los arrays
que espera el compresor Draco:

    puntos  -> float32 (N, 3) en metros, ejes ya en convenio Unity (Y hacia arriba)
    colores -> uint8   (N, 3) RGB

Etapas (ver PLANIFICACION_CAMARA3D_DRACO.md, apartado 4):
    1. Captura color + profundidad alineadas.
    2. Stride y recorte por rango de Z.
    3. Deproyeccion vectorizada con las mallas (u-cx)/fx precalculadas en el arranque.
    4. Submuestreo aleatorio hasta max_puntos.

Si no hay camara (o pyrealsense2 no esta disponible) el gestor cae en modo
simulacion y genera una nube sintetica animada, para poder probar toda la cadena
de red sin hardware. Es el mismo comportamiento que ya tenian los scripts de
prueba de la fase F0/F1.
"""
import logging
import math
import time

import numpy as np

log = logging.getLogger(__name__)

try:
    import pyrealsense2 as rs
    REALSENSE_DISPONIBLE = True
except ImportError:
    REALSENSE_DISPONIBLE = False
    rs = None

try:
    import cv2
    CV2_DISPONIBLE = True
except ImportError:
    CV2_DISPONIBLE = False
    cv2 = None

# Resolucion degradada cuando la camara esta en un puerto USB 2.x
RESOLUCION_USB2 = (424, 240)


class GestorRealSense:
    """
    Uso tipico:
        gestor = GestorRealSense()
        gestor.iniciar()                 # True = camara fisica, False = simulacion
        puntos, colores = gestor.capturar()
        gestor.detener()

    capturar() es bloqueante (espera al frame de la camara), asi que desde el
    bucle asincrono hay que llamarla con loop.run_in_executor().
    """

    def __init__(self, resolucion=(640, 480), fps=30, rango_z=(0.3, 1.5),
                 stride=2, max_puntos=60000, permitir_simulacion=True):
        self.resolucion = resolucion
        self.fps = fps
        self.rango_z = rango_z
        self.stride = max(1, int(stride))
        self.max_puntos = max_puntos
        self.permitir_simulacion = permitir_simulacion

        self.simulando = False
        self.iniciado = False
        self.tipo_usb = "desconocido"

        self._pipeline = None
        self._config = None
        self._align = None
        self._profile = None
        self._escala_profundidad = 1.0

        # Mallas de deproyeccion precalculadas: x = malla_x * z, y = malla_y * z
        self._malla_x = None
        self._malla_y = None

        self._rng = np.random.default_rng()

    # ------------------------------------------------------------------ inicio
    def iniciar(self):
        """Arranca la camara. Devuelve True si hay camara fisica, False si simula."""
        if self.iniciado:
            return not self.simulando

        if REALSENSE_DISPONIBLE and CV2_DISPONIBLE and self._iniciar_camara():
            self.iniciado = True
            self.simulando = False
            return True

        if not self.permitir_simulacion:
            raise RuntimeError("No hay camara RealSense disponible y la simulacion esta desactivada")

        motivo = "pyrealsense2/cv2 no disponibles" if not (REALSENSE_DISPONIBLE and CV2_DISPONIBLE) \
                 else "no se pudo abrir la camara"
        log.warning(f"GestorRealSense: {motivo} — se emitira una nube sintetica")
        self.iniciado = True
        self.simulando = True
        return False

    def _iniciar_camara(self):
        try:
            # pipeline.start() tarda ~15 s en rendirse si no hay camara enchufada,
            # asi que preguntamos primero al contexto, que responde al instante.
            if len(rs.context().query_devices()) == 0:
                log.warning("GestorRealSense: no hay ninguna camara RealSense conectada")
                return False

            self._pipeline = rs.pipeline()
            self._config = rs.config()

            ancho, alto = self.resolucion
            self._config.enable_stream(rs.stream.depth, ancho, alto, rs.format.z16, self.fps)
            self._config.enable_stream(rs.stream.color, ancho, alto, rs.format.bgr8, self.fps)

            self._align = rs.align(rs.stream.color)
            self._profile = self._pipeline.start(self._config)

            dispositivo = self._profile.get_device()
            if dispositivo.supports(rs.camera_info.usb_type_descriptor):
                self.tipo_usb = dispositivo.get_info(rs.camera_info.usb_type_descriptor)

            # Riesgo conocido: en USB 2.x el SDK no sostiene 640x480@30 (ver apartado 9)
            if self.tipo_usb.startswith("2") and self.resolucion != RESOLUCION_USB2:
                log.warning(f"GestorRealSense: camara en USB {self.tipo_usb} — "
                            f"degradando a {RESOLUCION_USB2[0]}x{RESOLUCION_USB2[1]}")
                self._pipeline.stop()
                self.resolucion = RESOLUCION_USB2
                self._config = rs.config()
                self._config.enable_stream(rs.stream.depth, RESOLUCION_USB2[0], RESOLUCION_USB2[1],
                                           rs.format.z16, self.fps)
                self._config.enable_stream(rs.stream.color, RESOLUCION_USB2[0], RESOLUCION_USB2[1],
                                           rs.format.bgr8, self.fps)
                self._profile = self._pipeline.start(self._config)

            self._escala_profundidad = (self._profile.get_device()
                                        .first_depth_sensor().get_depth_scale())
            self._preparar_mallas()

            log.info(f"GestorRealSense: camara iniciada {self.resolucion[0]}x{self.resolucion[1]}"
                     f"@{self.fps} (USB {self.tipo_usb}, escala {self._escala_profundidad})")
            return True

        except Exception as e:
            log.error(f"GestorRealSense: error iniciando la camara — {e}")
            try:
                if self._pipeline is not None:
                    self._pipeline.stop()
            except Exception:
                pass
            self._pipeline = None
            return False

    def _preparar_mallas(self):
        """
        Precalcula (u-cx)/fx y -(v-cy)/fy sobre la rejilla submuestreada.
        Asi la deproyeccion de cada frame se queda en dos multiplicaciones vectoriales.
        El signo negativo de Y convierte el eje de imagen (hacia abajo) al de Unity.
        """
        intr = (self._profile.get_stream(rs.stream.color)
                .as_video_stream_profile().intrinsics)

        u = np.arange(0, intr.width, self.stride, dtype=np.float32)
        v = np.arange(0, intr.height, self.stride, dtype=np.float32)
        uu, vv = np.meshgrid(u, v)

        self._malla_x = ((uu - intr.ppx) / intr.fx).astype(np.float32)
        self._malla_y = (-(vv - intr.ppy) / intr.fy).astype(np.float32)

    # ---------------------------------------------------------------- captura
    def capturar(self):
        """Devuelve (puntos, colores) o (None, None) si el frame no es utilizable."""
        if not self.iniciado:
            return None, None
        if self.simulando:
            return self._capturar_sintetica()
        return self._capturar_camara()

    def _capturar_camara(self):
        try:
            frames = self._pipeline.wait_for_frames()
            alineados = self._align.process(frames)

            frame_z = alineados.get_depth_frame()
            frame_color = alineados.get_color_frame()
            if not frame_z or not frame_color:
                return None, None

            profundidad = np.asanyarray(frame_z.get_data())[::self.stride, ::self.stride]
            color = np.asanyarray(frame_color.get_data())[::self.stride, ::self.stride]

            z = profundidad * self._escala_profundidad
            z_min, z_max = self.rango_z
            mascara = (z >= z_min) & (z <= z_max)

            if not mascara.any():
                return None, None

            z_validos = z[mascara].astype(np.float32)
            puntos = np.stack((self._malla_x[mascara] * z_validos,
                               self._malla_y[mascara] * z_validos,
                               z_validos), axis=-1)

            # La RealSense entrega BGR y Unity espera RGB
            colores = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)[mascara].astype(np.uint8)

            return self._submuestrear(puntos, colores)

        except Exception as e:
            log.error(f"GestorRealSense: error capturando frame — {e}")
            return None, None

    def _capturar_sintetica(self):
        """Superficie senoidal animada dentro del mismo rango de Z que la camara real."""
        resolucion = 150   # ~22.5k puntos, suficiente para cargar la red
        eje = np.linspace(-0.5, 0.5, resolucion, dtype=np.float32)
        xx, yy = np.meshgrid(eje, eje)

        fase = 2.0 * math.pi * (time.time() % 4.0) * 0.5
        zz = 1.0 + 0.15 * np.sin(5.0 * np.sqrt(xx ** 2 + yy ** 2) - fase)

        puntos = np.stack((xx.ravel(), yy.ravel(), zz.ravel()), axis=-1).astype(np.float32)

        r = ((xx.ravel() + 0.5) * 255).astype(np.uint8)
        g = ((yy.ravel() + 0.5) * 255).astype(np.uint8)
        b = (((zz.ravel() - 0.8) / 0.35) * 255).clip(0, 255).astype(np.uint8)
        colores = np.stack((r, g, b), axis=-1)

        # Imitamos la cadencia de la camara para no saturar la CPU en modo simulacion
        time.sleep(1.0 / max(self.fps, 1))

        return self._submuestrear(puntos, colores)

    def _submuestrear(self, puntos, colores):
        """Recorta la nube a max_puntos con un muestreo aleatorio sin reemplazo."""
        n = len(puntos)
        if n == 0:
            return None, None
        if n <= self.max_puntos:
            return puntos, colores

        idx = self._rng.choice(n, self.max_puntos, replace=False)
        return puntos[idx], colores[idx]

    # ------------------------------------------------------------------- fin
    def detener(self):
        if not self.iniciado:
            return
        if self._pipeline is not None:
            try:
                self._pipeline.stop()
            except Exception:
                pass
            self._pipeline = None
        self.iniciado = False
        log.info("GestorRealSense: capturador detenido")
