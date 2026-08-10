# nube_protocolo.py — Protocolo binario del DataChannel "nube3d"
"""
Empaquetado y desempaquetado de la nube de puntos comprimida con Draco.

Cada frame se trocea en chunks de 16 KiB y cada chunk viaja precedido de una
cabecera binaria de 26 bytes en little-endian (ver PLANIFICACION_CAMARA3D_DRACO.md,
apartado 5). El lado Unity que la lee es Assets/Scripts/Scripts_Nube3D/NubeReceiver.cs.

    struct.pack("<HBBIHHQIH")
      magic          (2 B)  0x4E33 = "N3"
      version        (1 B)
      flags          (1 B)  bit 0 = el robot ha caido al fallback de video 2D
      frame_id       (4 B)  autoincremental
      chunk_idx      (2 B)  indice del chunk dentro del frame (0-indexed)
      n_chunks       (2 B)  numero total de chunks del frame
      t_captura      (8 B)  timestamp de captura en ms Unix (metrica G2G)
      n_puntos       (4 B)  puntos totales del frame
      encode_ms_x10  (2 B)  tiempo de compresion Draco en ms x10

Se corta el chunk por payload y no por tamaño total: cada mensaje SCTP mide
CABECERA_BYTES + hasta CHUNK_BYTES, muy por debajo de los 64 KiB que anuncia aiortc.
"""
import struct
import time
from collections import namedtuple

MAGIC = 0x4E33
VERSION = 1

FORMATO_CABECERA = "<HBBIHHQIH"
CABECERA_BYTES = struct.calcsize(FORMATO_CABECERA)   # 26

FLAG_FALLBACK_2D = 0x01

# Limites de los campos de la cabecera (para no desbordar al empaquetar)
MAX_U16 = 0xFFFF
MAX_U32 = 0xFFFFFFFF

Cabecera = namedtuple(
    "Cabecera",
    "magic version flags frame_id chunk_idx n_chunks t_captura n_puntos encode_ms"
)


def ahora_ms():
    """Timestamp Unix en milisegundos, el mismo reloj que usa Unity para la latencia."""
    return int(time.time() * 1000)


def construir_cabecera(frame_id, chunk_idx, n_chunks, t_captura_ms,
                       n_puntos, encode_ms, flags=0):
    """Devuelve los 26 bytes de cabecera de un chunk."""
    return struct.pack(
        FORMATO_CABECERA,
        MAGIC,
        VERSION,
        flags & 0xFF,
        frame_id & MAX_U32,
        chunk_idx & MAX_U16,
        n_chunks & MAX_U16,
        t_captura_ms & 0xFFFFFFFFFFFFFFFF,
        min(int(n_puntos), MAX_U32),
        min(int(round(encode_ms * 10)), MAX_U16),
    )


def trocear(datos, frame_id, t_captura_ms, n_puntos, encode_ms,
            chunk_bytes=16384, flags=0):
    """
    Parte la trama Draco en mensajes listos para enviar por el DataChannel.

    Devuelve una lista de bytes (cabecera + payload). Si la trama esta vacia
    devuelve una lista vacia: no tiene sentido anunciar un frame sin puntos.
    """
    total = len(datos)
    if total == 0:
        return []

    n_chunks = (total + chunk_bytes - 1) // chunk_bytes
    if n_chunks > MAX_U16:
        raise ValueError(
            f"La trama de {total} bytes necesita {n_chunks} chunks y el protocolo "
            f"solo admite {MAX_U16}. Sube chunk_bytes o baja NUBE_MAX_PUNTOS."
        )

    mensajes = []
    for idx in range(n_chunks):
        inicio = idx * chunk_bytes
        fin = min(inicio + chunk_bytes, total)
        cabecera = construir_cabecera(frame_id, idx, n_chunks, t_captura_ms,
                                      n_puntos, encode_ms, flags)
        mensajes.append(cabecera + datos[inicio:fin])

    return mensajes


def leer_cabecera(chunk):
    """
    Devuelve la Cabecera de un chunk recibido, o None si no pertenece al protocolo.
    encode_ms se devuelve ya dividido entre 10 (en milisegundos reales).
    """
    if chunk is None or len(chunk) < CABECERA_BYTES:
        return None

    campos = struct.unpack(FORMATO_CABECERA, chunk[:CABECERA_BYTES])
    if campos[0] != MAGIC:
        return None

    return Cabecera(
        magic=campos[0],
        version=campos[1],
        flags=campos[2],
        frame_id=campos[3],
        chunk_idx=campos[4],
        n_chunks=campos[5],
        t_captura=campos[6],
        n_puntos=campos[7],
        encode_ms=campos[8] / 10.0,
    )


class Reensamblador:
    """
    Reensambla los chunks de un frame. Misma logica que NubeReceiver.cs, aqui
    la usan el simulador mock_unity_nube3d.py y las pruebas de integridad.

    Uso:
        r = Reensamblador()
        completo = r.procesar(chunk)          # -> (Cabecera, bytes) o None
    """

    def __init__(self, ms_descarte=250):
        self.ms_descarte = ms_descarte
        self.frame_activo = -1
        self.chunks = []
        self.recibidos = 0
        self.esperados = 0
        self.cabecera = None
        self.t_inicio = 0.0

        # Contadores de calidad
        self.frames_completos = 0
        self.frames_descartados = 0
        self.chunks_descartados = 0

    def procesar(self, chunk):
        cab = leer_cabecera(chunk)
        if cab is None:
            return None

        # Chunk de un frame ya superado
        if cab.frame_id < self.frame_activo:
            self.chunks_descartados += 1
            return None

        if cab.frame_id != self.frame_activo:
            if self.esperados and self.recibidos < self.esperados:
                self.frames_descartados += 1
                self.chunks_descartados += self.esperados - self.recibidos

            self.frame_activo = cab.frame_id
            self.chunks = [None] * cab.n_chunks
            self.recibidos = 0
            self.esperados = cab.n_chunks
            self.cabecera = cab
            self.t_inicio = time.perf_counter()

        # Timeout de reensamblado: el frame llego a medias y se ha hecho viejo
        if (time.perf_counter() - self.t_inicio) * 1000 > self.ms_descarte:
            self.frames_descartados += 1
            self.chunks_descartados += self.esperados - self.recibidos
            self.frame_activo = -1
            self.esperados = 0
            return None

        if cab.chunk_idx >= self.esperados or self.chunks[cab.chunk_idx] is not None:
            self.chunks_descartados += 1
            return None

        self.chunks[cab.chunk_idx] = chunk[CABECERA_BYTES:]
        self.recibidos += 1

        if self.recibidos != self.esperados:
            return None

        trama = b"".join(self.chunks)
        self.frames_completos += 1
        self.esperados = 0
        return self.cabecera, trama
