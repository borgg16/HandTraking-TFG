# draco_encoder.py — Compresión Draco de la nube de puntos
"""
Fina capa sobre DracoPy para dejar el resto del pipeline libre de detalles de la
libreria y poder medir el coste de compresion en un solo sitio.

Parametros por defecto (ver PLANIFICACION_CAMARA3D_DRACO.md, apartado 10):
    qp = 11    -> cuantizacion de posicion; el error resultante queda por debajo
                  del ruido de la propia RealSense.
    nivel = 1  -> prioriza velocidad de compresion sobre ratio, que es lo que
                  interesa en un lazo de teleoperacion.
"""
import logging
import time

log = logging.getLogger(__name__)

try:
    import DracoPy
    DRACO_DISPONIBLE = True
except ImportError:
    DRACO_DISPONIBLE = False
    DracoPy = None
    log.error("draco_encoder: DracoPy no esta instalado — la nube 3D no podra emitirse")


def comprimir(puntos, colores, qp=11, nivel=1):
    """
    Comprime la nube y devuelve (bytes_draco, encode_ms).

    Devuelve (b"", 0.0) si DracoPy no esta disponible o la nube viene vacia,
    para que el emisor pueda contabilizarlo como frame omitido sin excepciones.
    """
    if not DRACO_DISPONIBLE or puntos is None or len(puntos) == 0:
        return b"", 0.0

    t0 = time.perf_counter()
    datos = DracoPy.encode(
        puntos,
        colors=colores,
        quantization_bits=qp,
        compression_level=nivel,
    )
    encode_ms = (time.perf_counter() - t0) * 1000.0

    return datos, encode_ms


def descomprimir(datos):
    """
    Inverso de comprimir(). Solo lo usan el simulador y las pruebas de integridad:
    en produccion quien descomprime es Unity con com.unity.cloud.draco.
    """
    if not DRACO_DISPONIBLE or not datos:
        return None, None

    nube = DracoPy.decode(datos)
    colores = getattr(nube, "colors", None)
    return nube.points, colores


def bytes_sin_comprimir(puntos, colores):
    """Tamaño que ocuparia el frame en crudo (XYZ float32 + RGB uint8)."""
    if puntos is None:
        return 0
    total = puntos.nbytes
    if colores is not None:
        total += colores.nbytes
    return total
