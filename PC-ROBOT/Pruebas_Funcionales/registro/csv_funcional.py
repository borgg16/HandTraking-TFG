#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Registro CSV Funcional para Teleoperación Robot (Fase P2).

Registra de forma exhaustiva, determinista y segura cada comando de teleoperación
procesado por el sistema, permitiendo el cálculo posterior de las métricas M1 a M4.

Columnas del CSV funcional:
  1.  t_unity_captura     - Timestamp de captura en Unity (ms epoch)
  2.  norm_x, norm_y, norm_z, g - Datos normalizados [0, 1]
  3.  t_unity_envio       - Timestamp de envío en Unity (ms epoch)
  4.  t_robot_recepcion   - Timestamp de llegada en Python (ms epoch)
  5.  x_cm, y_cm, z_cm    - Coordenadas físicas tras desnormalización y clamp
  6.  t_rad               - Ángulo de pinza en radianes
  7.  t_uart_escritura    - Timestamp previo al envío serie (ms epoch)
  8.  clamp_activo        - Booleano (True si el clamp recortó la coordenada)
  9.  rtt_ms              - Round Trip Time si está disponible (o vacío)
  10. perdida_pct         - Porcentaje de pérdida si está disponible (o vacío)
  11. id_intento          - Identificador del intento actual
  12. id_operador         - Identificador del sujeto/operador
  13. condicion_red       - Condición de red evaluada (ej: C1_WIFI_SIN_CARGA)
  14. nivel_objeto        - Nivel de dificultad / altura del objeto
"""

import csv
import datetime
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("csv_funcional")

CAMPOS_FUNCIONAL = [
    "t_unity_captura",
    "norm_x",
    "norm_y",
    "norm_z",
    "g",
    "t_unity_envio",
    "t_robot_recepcion",
    "x_cm",
    "y_cm",
    "z_cm",
    "t_rad",
    "t_uart_escritura",
    "clamp_activo",
    "rtt_ms",
    "perdida_pct",
    "id_intento",
    "id_operador",
    "condicion_red",
    "nivel_objeto"
]

CAMPOS_CALIBRACION = [
    "timestamp",
    "id_operador",
    "ext_x_pos",
    "ext_x_neg",
    "ext_y_pos",
    "ext_y_neg",
    "mano_dominante"
]

class RegistradorFuncional:
    """
    Gestor de persistencia de métricas funcionales comando a comando.
    Diseñado para ser importado e instanciado en safe8_WebRTC.py o scripts de test.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        if output_dir is None:
            # Por defecto: PC-ROBOT/Pruebas_Funcionales/resultados
            self.output_dir = Path(__file__).resolve().parents[1] / "resultados"
        else:
            self.output_dir = Path(output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._writer = None
        self.sesion_activa = False

        self.id_operador = "OP_DEFAULT"
        self.condicion_red = "C1_WIFI_SIN_CARGA"
        self.id_intento = 1
        self.nivel_objeto = "medio"

    def abrir_sesion(
        self,
        id_operador: str = "OP1",
        condicion_red: str = "C1_WIFI_SIN_CARGA",
        id_intento: int = 1,
        nivel_objeto: str = "medio",
        tag_sesion: Optional[str] = None
    ) -> Path:
        """
        Crea un nuevo fichero CSV para la sesión y escribe las cabeceras.
        """
        if self._file is not None:
            self.cerrar_sesion()

        self.id_operador = id_operador
        self.condicion_red = condicion_red
        self.id_intento = id_intento
        self.nivel_objeto = nivel_objeto

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        sufijo = f"_{tag_sesion}" if tag_sesion else ""
        nombre_csv = f"funcional_{self.condicion_red}_{self.id_operador}_{timestamp}{sufijo}.csv"
        csv_path = self.output_dir / nombre_csv

        self._file = open(csv_path, mode="w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CAMPOS_FUNCIONAL)
        self._writer.writeheader()
        self._file.flush()
        self._current_path = csv_path
        self._filas_escritas = 0
        self.sesion_activa = True

        log.info(f"Sesion funcional iniciada. Guardando en: {csv_path}")
        return csv_path

    def registrar_comando(self, **datos: Any):
        """
        Registra una fila en el CSV funcional con flush inmediato para evitar pérdida de datos.
        """
        if not self.sesion_activa or self._writer is None or self._file is None:
            return

        fila: Dict[str, Any] = {campo: "" for campo in CAMPOS_FUNCIONAL}

        # Asignar metadatos por defecto de la sesión
        fila["id_operador"] = self.id_operador
        fila["condicion_red"] = self.condicion_red
        fila["id_intento"] = self.id_intento
        fila["nivel_objeto"] = self.nivel_objeto

        # Sobrescribir con los datos explícitos del comando
        for k, v in datos.items():
            if k in fila:
                if isinstance(v, float):
                    fila[k] = f"{v:.4f}"
                else:
                    fila[k] = v

        self._writer.writerow(fila)
        self._file.flush()
        self._filas_escritas += 1

    def set_intento(self, id_intento: int):
        """Actualiza el ID del intento actual dentro de la misma sesión."""
        self.id_intento = id_intento

    def cerrar_sesion(self):
        """Cierra el archivo CSV de la sesión de manera segura y elimina archivos vacíos sin datos."""
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
                if self._filas_escritas == 0 and hasattr(self, "_current_path") and self._current_path and self._current_path.exists():
                    self._current_path.unlink()
                    log.info("Sesion funcional cerrada (archivo vacío sin comandos descartado).")
                else:
                    log.info(f"Sesion funcional cerrada correctamente ({self._filas_escritas} comandos registrados).")
            except Exception as e:
                log.error(f"Error al cerrar fichero funcional: {e}")
            finally:
                self._file = None
                self._writer = None
                self._current_path = None
                self._filas_escritas = 0
                self.sesion_activa = False

    def guardar_calibracion_operador(
        self,
        id_operador: str,
        ext_x_pos: float,
        ext_x_neg: float,
        ext_y_pos: float,
        ext_y_neg: float,
        mano_dominante: str = "derecha"
    ) -> Path:
        """
        Persiste los parámetros de calibración de 3 fases del operador en calibraciones_global.csv.
        """
        csv_calib = self.output_dir / "calibraciones_global.csv"
        existe = csv_calib.exists()

        with open(csv_calib, mode="a", newline="", encoding="utf-8") as f_cal:
            writer = csv.DictWriter(f_cal, fieldnames=CAMPOS_CALIBRACION)
            if not existe:
                writer.writeheader()

            writer.writerow({
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "id_operador": id_operador,
                "ext_x_pos": f"{ext_x_pos:.4f}",
                "ext_x_neg": f"{ext_x_neg:.4f}",
                "ext_y_pos": f"{ext_y_pos:.4f}",
                "ext_y_neg": f"{ext_y_neg:.4f}",
                "mano_dominante": mano_dominante
            })
            f_cal.flush()

        log.info(f"Calibracion de operador {id_operador} guardada en {csv_calib}")
        return csv_calib
