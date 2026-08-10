"""
Tests unitarios de las funciones puras clamp() y desnormalizar()
de safe8_WebRTC.py (control del brazo RoArm-M2 via WebRTC).

Problema 5.12 del TFG: no habia tests automaticos de las funciones mas
faciles de aislar. Estos tests cubren el comportamiento normal, los casos
limite y el comportamiento fuera de rango, sin necesitar hardware ni red
(los imports pesados se sustituyen por dobles en conftest.py).

NOTA (hallazgo documentado, NO corregido): el docstring de desnormalizar()
dice "norm_x=0 -> izquierda -> Y negativa / norm_x=1 -> derecha -> Y positiva",
pero la formula activa produce lo contrario. test_eje_x_signo verifica el
comportamiento REAL del codigo (test de caracterizacion), no el documentado.
"""
import math

try:
    import pytest
except ImportError:
    class Approx:
        def __init__(self, val, abs_tol=1e-5):
            self.val = val
            self.abs_tol = abs_tol
        def __eq__(self, other):
            return math.isclose(self.val, float(other), abs_tol=self.abs_tol)
        def __repr__(self):
            return f"approx({self.val})"

    class Parametrize:
        def __call__(self, names, values):
            def decorator(func):
                def wrapper(instance, *args, **kwargs):
                    arg_names = [n.strip() for n in names.split(",")]
                    for row in values:
                        row_dict = dict(zip(arg_names, row))
                        func(instance, **row_dict)
                return wrapper
            return decorator

    class PytestFallback:
        def approx(self, val, rel=None, abs=1e-5):
            return Approx(val, abs_tol=abs if abs is not None else 1e-5)
        class mark:
            parametrize = Parametrize()

    pytest = PytestFallback()

import os
import sys
from unittest.mock import MagicMock

class DummyMediaStreamTrack:
    kind = "video"

for mod in ["serial", "cv2", "aiortc", "aiortc.mediastreams", "aiortc.contrib", "aiortc.contrib.media", "aiortc.sdp", "websockets", "websockets.exceptions", "av"]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            m = MagicMock()
            if mod == "aiortc.mediastreams":
                m.MediaStreamTrack = DummyMediaStreamTrack
            sys.modules[mod] = m

_control_brazo_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "Control_Brazo")
)
if _control_brazo_dir not in sys.path:
    sys.path.insert(0, _control_brazo_dir)

from safe8_WebRTC import (
    clamp,
    desnormalizar,
    X_MIN, X_MAX,
    Y_MIN, Y_MAX,
    Z_MIN, Z_MAX,
    T_OPEN, T_CLOSED,
)


import unittest

# ------------------------------------------------------------------ clamp ---
class TestClamp(unittest.TestCase):
    """clamp(v, vmin, vmax) = max(vmin, min(vmax, v))"""

    @pytest.mark.parametrize("v, vmin, vmax, esperado", [
        # Comportamiento normal: valor dentro de rango se devuelve tal cual
        (5, 0, 10, 5),
        (0.5, 0.0, 1.0, 0.5),   # uso real: clamp del gripper dentro de desnormalizar
        # Casos limite: exactamente en los bordes
        (0, 0, 10, 0),
        (10, 0, 10, 10),
        (0.0, 0.0, 1.0, 0.0),
        (1.0, 0.0, 1.0, 1.0),
        # Fuera de rango: se satura al limite correspondiente
        (-5, 0, 10, 0),
        (15, 0, 10, 10),
        (-0.1, 0.0, 1.0, 0.0),
        (1.1, 0.0, 1.0, 1.0),
    ])
    def test_rangos(self, v, vmin, vmax, esperado):
        self.assertEqual(clamp(v, vmin, vmax), esperado)


# ----------------------------------------------------------- desnormalizar ---
class TestDesnormalizar(unittest.TestCase):
    """
    desnormalizar(norm_x, norm_y, norm_z, gripper)
        -> (x_robot, y_robot, z_robot, t)

    Mapeos activos en produccion:
        x_robot = X_MIN + norm_z * (X_MAX - X_MIN)      # [5, 40] cm
        y_robot = Y_MAX + norm_x * (Y_MIN - Y_MAX)      # ver test_eje_x_signo
        z_robot = Z_MIN + norm_y * (Z_MAX - Z_MIN)      # [-10, 50] cm
        t       = T_CLOSED + (T_OPEN - T_CLOSED) * clamp(gripper, 0, 1)
    """

    def test_postura_neutra(self):
        """norm=(0.5, 0.5, 0.0): brazo recogido, centrado lateral, altura media."""
        x, y, z, _t = desnormalizar(0.5, 0.5, 0.0, 1.0)
        assert x == pytest.approx(X_MIN)    # norm_z = 0 -> brazo recogido
        assert y == pytest.approx(0.0)      # norm_x = 0.5 -> centro lateral
        assert z == pytest.approx(20.0)     # norm_y = 0.5 -> mitad de [-10, 50]

    def test_eje_z_a_x(self):
        """norm_z controla la extension frontal (X del robot)."""
        x_recogido, *_ = desnormalizar(0.5, 0.5, 0.0, 1.0)
        x_estirado, *_ = desnormalizar(0.5, 0.5, 1.0, 1.0)
        assert x_recogido == pytest.approx(X_MIN)
        assert x_estirado == pytest.approx(X_MAX)

    def test_eje_y_a_z(self):
        """norm_y controla la altura (Z del robot): mano arriba -> Z positiva."""
        *_, z_abajo, _t = desnormalizar(0.5, 0.0, 0.0, 1.0)
        *_, z_arriba, _t = desnormalizar(0.5, 1.0, 0.0, 1.0)
        assert z_abajo == pytest.approx(Z_MIN)
        assert z_arriba == pytest.approx(Z_MAX)

    def test_eje_x_signo(self):
        """
        CARACTERIZACION (discrepancia docstring/codigo, NO corregida):
        el docstring dice 'norm_x=0 -> izquierda -> Y negativa' y
        'norm_x=1 -> derecha -> Y positiva', pero la formula activa
        (y_robot = Y_MAX + norm_x * (Y_MIN - Y_MAX)) produce lo contrario.
        Este test verifica el comportamiento REAL del codigo tal como esta.
        """
        _x, y_norm_x_0, *_ = desnormalizar(0.0, 0.5, 0.0, 1.0)
        _x, y_norm_x_1, *_ = desnormalizar(1.0, 0.5, 0.0, 1.0)
        assert y_norm_x_0 == pytest.approx(Y_MAX)   # +40 (positivo), no negativo
        assert y_norm_x_1 == pytest.approx(Y_MIN)   # -40 (negativo), no positivo

    def test_gripper_extremos(self):
        """gripper 0 -> pinza cerrada (T_CLOSED); 1 -> abierta (T_OPEN)."""
        *_, t_cerrada = desnormalizar(0.5, 0.5, 0.0, 0.0)
        *_, t_abierta = desnormalizar(0.5, 0.5, 0.0, 1.0)
        assert t_cerrada == pytest.approx(T_CLOSED)
        assert t_abierta == pytest.approx(T_OPEN)

    @pytest.mark.parametrize("gripper_fuera, gripper_equiv", [
        (-0.3, 0.0),   # por debajo de 0 -> clampa a 0 (cerrada)
        (1.5, 1.0),    # por encima de 1 -> clampa a 1 (abierta)
    ])
    def test_gripper_fuera_de_rango_se_clampa(self, gripper_fuera, gripper_equiv):
        """El gripper si se limita internamente a [0, 1] via clamp()."""
        *_, t_fuera = desnormalizar(0.5, 0.5, 0.0, gripper_fuera)
        *_, t_equiv = desnormalizar(0.5, 0.5, 0.0, gripper_equiv)
        assert t_fuera == pytest.approx(t_equiv)

    def test_coordenadas_espaciales_no_se_clampan(self):
        """
        CARACTERIZACION: desnormalizar() NO limita norm_x/norm_y/norm_z.
        Con norm_z=1.5 (fuera de [0,1]) x_robot sale de [X_MIN, X_MAX]:
        5 + 1.5 * 35 = 57.5 > 40. El clamp de seguridad final ocurre en el
        llamador (on_message), fuera de esta funcion pura.
        """
        x, *_ = desnormalizar(0.5, 0.5, 1.5, 1.0)
        assert x == pytest.approx(57.5)
        assert x > X_MAX
