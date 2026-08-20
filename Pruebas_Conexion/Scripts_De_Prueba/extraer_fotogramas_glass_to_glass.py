"""
Extraccion de fotogramas para la validacion glass-to-glass manual (TFG, S9.7).

Para cada video de la grabacion de pantalla del Quest 2 (overlays P/U en verde,
P = timestamp de captura del robot mod 100000, U = timestamp de recepcion en
Unity mod 100000):

  1. Se muestrean N_SAMPLES instantes distribuidos a lo largo del video
     (evita el 5% inicial/final, donde el hand/controlador tapa a veces
     la pantalla al empezar/parar la grabacion).
  2. En cada instante se extrae un fotograma con ffmpeg.
  3. Se detecta la region de pixeles verdes de P (mitad izquierda del
     fotograma) y de U (mitad derecha) por separado, restringiendo la
     busqueda a la banda mas alta de pixeles verdes de cada mitad (los
     digitos P:/U: estan siempre por encima del reloj de referencia
     grande, que en algunos videos tambien se renderiza en verde y
     contaminaria la deteccion si no se restringe la banda).
  4. Se recorta, se pasa a blanco y negro invertido (mascara verde, no
     umbral de luminancia) y se escala x6 para facilitar la lectura
     visual posterior de los digitos (no se usa OCR: un pase de prueba
     con Tesseract --psm 7 confundio digitos incluso en recortes limpios;
     la transcripcion final se hizo a ojo sobre estos recortes, con
     verificacion cruzada de consistencia interna entre muestras cercanas
     de la misma sesion).

Requiere: ffmpeg/ffprobe en el PATH, numpy, Pillow.
"""

import os
import subprocess
import numpy as np
from PIL import Image

N_SAMPLES = 18          # fotogramas objetivo por video
MARGIN = 0.05           # se evita el primer y el ultimo 5% del video
GREEN_BAND_PX = 42      # alto de la banda superior de pixeles verdes que se conserva


def duration(video_path: str) -> float:
    """Duracion del video en segundos, via ffprobe."""
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ]).decode().strip()
    return float(out)


def extract_frame(video_path: str, t_seconds: float, out_png: str) -> None:
    """Extrae un unico fotograma en el instante t_seconds con ffmpeg."""
    subprocess.run([
        "ffmpeg", "-y", "-ss", f"{t_seconds:.2f}", "-i", video_path,
        "-frames:v", "1", out_png, "-loglevel", "error",
    ], check=False)


def find_green_regions(img_path: str, save_prefix: str):
    """
    Detecta y recorta las regiones P (mitad izquierda) y U (mitad derecha)
    de un fotograma, a partir de la mascara de pixeles verdes.

    Devuelve (ruta_P, ruta_U); None en el lado que no se detecta.
    """
    im = Image.open(img_path).convert("RGB")
    arr = np.array(im)
    h, w, _ = arr.shape
    R, G, B = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)

    # mascara de "verde real" (overlay), no un simple umbral de brillo:
    # exige que el canal G domine claramente sobre R y B
    green_mask = (G > 105) & (G > R + 30) & (G > B + 30)

    ys, xs = np.where(green_mask)
    if len(xs) == 0:
        return None, None

    mid = w // 2

    def mask_crop(side_selector, tag):
        xs_s, ys_s = xs[side_selector], ys[side_selector]
        if len(xs_s) < 5:
            return None

        # banda mas alta de pixeles verdes de este lado: P:/U: siempre
        # aparecen por encima del reloj de referencia grande, que en
        # algunos videos tambien es verde y si no se restringe la banda
        # se cuela dentro del mismo recorte
        y_top = ys_s.min()
        band = ys_s <= y_top + GREEN_BAND_PX
        xs_, ys_ = xs_s[band], ys_s[band]
        if len(xs_) < 5:
            return None

        x0, x1 = xs_.min(), xs_.max()
        y0, y1 = ys_.min(), ys_.max()
        pad = 5
        x0, x1 = max(0, x0 - pad), min(w, x1 + pad)
        y0, y1 = max(0, y0 - pad), min(h, y1 + pad)

        sub_mask = green_mask[y0:y1, x0:x1]
        bw = (sub_mask * 255).astype(np.uint8)
        bw_img = Image.fromarray(bw).resize(
            (sub_mask.shape[1] * 6, sub_mask.shape[0] * 6), Image.LANCZOS
        )

        # binarizado + inversion (fondo blanco, digitos en negro) + margen
        a2 = (np.array(bw_img) > 80).astype(np.uint8) * 255
        inv = 255 - a2
        canvas = np.full((inv.shape[0] + 40, inv.shape[1] + 40), 255, dtype=np.uint8)
        canvas[20:20 + inv.shape[0], 20:20 + inv.shape[1]] = inv

        out_path = f"{save_prefix}_{tag}.png"
        Image.fromarray(canvas).save(out_path)
        return out_path

    p_path = mask_crop(xs < mid, "P")
    u_path = mask_crop(xs >= mid, "U")
    return p_path, u_path


def extract_video(video_path: str, out_dir: str, n_samples: int = N_SAMPLES):
    """
    Extrae n_samples fotogramas equiespaciados de un video y guarda los
    recortes P/U de cada uno en out_dir. Idempotente: si el par P/U de un
    fotograma ya existe, no lo vuelve a generar (permite reanudar tras un
    corte o ampliar la muestra en una pasada posterior).
    """
    os.makedirs(out_dir, exist_ok=True)
    dur = duration(video_path)
    fracs = [MARGIN + i * ((1 - 2 * MARGIN) / (n_samples - 1)) for i in range(n_samples)]

    rows = []
    for i, frac in enumerate(fracs, start=1):
        t = dur * frac
        p_expected = os.path.join(out_dir, f"f{i:02d}_P.png")
        u_expected = os.path.join(out_dir, f"f{i:02d}_U.png")

        if os.path.exists(p_expected) and os.path.exists(u_expected):
            rows.append(dict(i=i, t=t, p_path=p_expected, u_path=u_expected))
            continue

        full_frame = os.path.join(out_dir, f"f{i:02d}_full.png")
        extract_frame(video_path, t, full_frame)
        p_path, u_path = find_green_regions(full_frame, os.path.join(out_dir, f"f{i:02d}"))
        rows.append(dict(i=i, t=t, p_path=p_path, u_path=u_path))

        if os.path.exists(full_frame):
            os.remove(full_frame)  # solo se conservan los recortes P/U, no el fotograma completo

    ok = sum(1 for r in rows if r["p_path"] and r["u_path"])
    print(f"{os.path.basename(video_path)}: duracion={dur:.1f}s, "
          f"fotogramas validos={ok}/{n_samples}")
    return dict(dur=dur, rows=rows)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Uso: python extraer_fotogramas_glass_to_glass.py <video.mp4> <carpeta_salida>")
        sys.exit(1)
    extract_video(sys.argv[1], sys.argv[2])
