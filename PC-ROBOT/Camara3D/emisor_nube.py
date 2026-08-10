# emisor_nube.py — Bucle de emisión de la nube de puntos por el DataChannel "nube3d"
"""
Une las tres piezas del pipeline 3D y las bombea al DataChannel:

    GestorRealSense  ->  draco_encoder.comprimir  ->  nube_protocolo.trocear  ->  channel.send

La captura y la compresion se lanzan con run_in_executor para no bloquear el
event loop de aiortc: si se bloquea, se resiente el RTT del canal "comandos" que
mueve el brazo, que es justamente lo que no queremos (apartado 9 del plan).

Control de congestion: antes de gastar CPU en un frame se mira bufferedAmount del
canal. Si el buffer supera el limite, el frame se descarta entero — mas vale
perder un frame que acumular retraso en la nube y en el control.
"""
import asyncio
import csv
import logging
import os
import sys
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import draco_encoder
import nube_protocolo

log = logging.getLogger(__name__)

# Carpeta de resultados: PC-ROBOT/Camara3D -> raiz del repositorio
_RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CARPETA_RESULTADOS = os.path.join(_RAIZ, "Pruebas_Conexion", "Resultados_Nube3D")

CABECERA_CSV = ["frame_id", "n_puntos", "bytes_raw", "bytes_draco",
                "ratio_compresion", "encode_ms", "estado"]


class EmisorNube3D:
    """
    Uso:
        emisor = EmisorNube3D(channel, gestor)
        tarea = asyncio.create_task(emisor.bucle())
        ...
        emisor.detener()
        await tarea
    """

    def __init__(self, canal, gestor, qp=11, nivel=1, fps_objetivo=10,
                 chunk_bytes=16384, buffer_max=65536, registrar_csv=False,
                 sesion=None, canal_control=None, buffer_control=16384):
        self.canal = canal
        self.gestor = gestor
        self.qp = qp
        self.nivel = nivel
        self.fps_objetivo = max(1, fps_objetivo)
        self.chunk_bytes = chunk_bytes
        self.buffer_max = buffer_max

        # La nube y los comandos comparten la asociacion SCTP: si dejamos crecer la
        # cola de la nube, los comandos del brazo salen por detras y el RTT de control
        # se dispara. Vigilamos tambien el canal de control para cortar antes.
        self.canal_control = canal_control
        self.buffer_control = buffer_control

        self.frame_id = 0
        self.frames_enviados = 0
        self.frames_omitidos = 0
        self.bytes_totales = 0
        self.fps_real = 0.0

        self._parar = False
        self._csv_fichero = None
        self._csv_writer = None

        if registrar_csv:
            self._abrir_csv(sesion or datetime.now().strftime("%Y%m%d_%H%M%S"))

    # ------------------------------------------------------------------- CSV
    def _abrir_csv(self, sesion):
        try:
            os.makedirs(CARPETA_RESULTADOS, exist_ok=True)
            ruta = os.path.join(CARPETA_RESULTADOS, f"nube3d_robot_{sesion}.csv")
            self._csv_fichero = open(ruta, "w", newline="", encoding="utf-8")
            self._csv_writer = csv.writer(self._csv_fichero)
            self._csv_writer.writerow(CABECERA_CSV)
            log.info(f"EmisorNube3D: registrando estadisticas en {ruta}")
        except OSError as e:
            log.warning(f"EmisorNube3D: no se pudo abrir el CSV de estadisticas — {e}")
            self._csv_fichero = None
            self._csv_writer = None

    def _fila_csv(self, n_puntos, bytes_raw, bytes_draco, encode_ms, estado):
        if self._csv_writer is None:
            return
        ratio = (bytes_raw / bytes_draco) if bytes_draco else 0.0
        self._csv_writer.writerow([
            self.frame_id, n_puntos, bytes_raw, bytes_draco,
            f"{ratio:.2f}", f"{encode_ms:.2f}", estado,
        ])
        if self.frames_enviados % 30 == 0:
            self._csv_fichero.flush()

    # ------------------------------------------------------------------ bucle
    async def bucle(self):
        loop = asyncio.get_event_loop()
        periodo = 1.0 / self.fps_objetivo

        log.info(f"EmisorNube3D: arrancando a {self.fps_objetivo} fps objetivo "
                 f"(qp={self.qp}, nivel={self.nivel}, chunks de {self.chunk_bytes} B)")

        t_ventana = time.perf_counter()
        frames_ventana = 0
        bytes_ventana = 0

        try:
            while not self._parar and self.canal.readyState == "open":
                t_frame = time.perf_counter()

                # 1. Backpressure: si hay cola pendiente, ni capturamos.
                #    Prioridad absoluta al canal de control del brazo.
                cola_nube = self.canal.bufferedAmount
                cola_control = (self.canal_control.bufferedAmount
                                if self.canal_control is not None else 0)

                if cola_nube > self.buffer_max or cola_control > self.buffer_control:
                    self.frames_omitidos += 1
                    self._fila_csv(0, 0, 0, 0.0,
                                   "omitido_control" if cola_control > self.buffer_control
                                   else "omitido_buffer")
                    await asyncio.sleep(periodo / 2)
                    continue

                # 2. Captura (bloqueante -> executor)
                puntos, colores = await loop.run_in_executor(None, self.gestor.capturar)
                if puntos is None or len(puntos) == 0:
                    self.frames_omitidos += 1
                    self._fila_csv(0, 0, 0, 0.0, "vacio")
                    await asyncio.sleep(0.01)
                    continue

                t_captura = nube_protocolo.ahora_ms()
                n_puntos = len(puntos)

                # 3. Compresion Draco (bloqueante -> executor)
                datos, encode_ms = await loop.run_in_executor(
                    None, draco_encoder.comprimir, puntos, colores, self.qp, self.nivel)

                if not datos:
                    self.frames_omitidos += 1
                    self._fila_csv(n_puntos, 0, 0, encode_ms, "error_draco")
                    await asyncio.sleep(periodo)
                    continue

                # 4. Troceado y envio
                mensajes = nube_protocolo.trocear(
                    datos, self.frame_id, t_captura, n_puntos, encode_ms,
                    chunk_bytes=self.chunk_bytes)

                for mensaje in mensajes:
                    if self.canal.readyState != "open":
                        break
                    self.canal.send(mensaje)
                    self.bytes_totales += len(mensaje)
                    bytes_ventana += len(mensaje)

                bytes_raw = draco_encoder.bytes_sin_comprimir(puntos, colores)
                self._fila_csv(n_puntos, bytes_raw, len(datos), encode_ms, "enviado")

                self.frame_id = (self.frame_id + 1) % nube_protocolo.MAX_U32
                self.frames_enviados += 1
                frames_ventana += 1

                # 5. Metricas de consola cada 5 s
                transcurrido = time.perf_counter() - t_ventana
                if transcurrido >= 5.0:
                    self.fps_real = frames_ventana / transcurrido
                    mbps = (bytes_ventana * 8) / (transcurrido * 1e6)
                    log.info(f"Nube3D: {self.fps_real:.1f} fps | {n_puntos} pts | "
                             f"{len(datos)/1024:.1f} KB/frame | {mbps:.1f} Mbps | "
                             f"enc={encode_ms:.1f} ms | omitidos={self.frames_omitidos}")
                    t_ventana = time.perf_counter()
                    frames_ventana = 0
                    bytes_ventana = 0

                # 6. Cadencia objetivo
                await asyncio.sleep(max(0.0, periodo - (time.perf_counter() - t_frame)))

        except asyncio.CancelledError:
            log.info("EmisorNube3D: bucle cancelado")
            raise
        except Exception as e:
            log.error(f"EmisorNube3D: error en el bucle de emision — {e}")
        finally:
            self.cerrar()
            log.info(f"EmisorNube3D: detenido tras {self.frames_enviados} frames "
                     f"({self.frames_omitidos} omitidos)")

    # -------------------------------------------------------------- apagado
    def detener(self):
        self._parar = True

    def cerrar(self):
        if self._csv_fichero is not None:
            try:
                self._csv_fichero.flush()
                self._csv_fichero.close()
            except OSError:
                pass
            self._csv_fichero = None
            self._csv_writer = None
