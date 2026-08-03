import os
import sys
import time
import math
import numpy as np

# Configurar consola en Windows para UTF-8 y evitar errores de encoding
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')

# Intentar importar dependencias
try:
    import pyrealsense2 as rs
    REALSENSE_AVAILABLE = True
except ImportError:
    REALSENSE_AVAILABLE = False
    print("[WARNING] pyrealsense2 no está instalado o no es compatible. Se usará simulación de nube sintética.")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[WARNING] opencv-python (cv2) no está instalado. Se usará simulación de nube sintética.")

try:
    import DracoPy
    DRACO_AVAILABLE = True
except ImportError:
    DRACO_AVAILABLE = False
    print("[WARNING] DracoPy no está instalado o no es compatible. Solo se medirá el rendimiento sin compresión.")

# Crear directorio de salida si no existe
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Assets", "StreamingAssets"))
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "nube_local.drc")

def generar_nube_sintetica(t_ms):
    """
    Genera una nube de puntos sintética (superficie senoidal animada)
    para pruebas cuando no hay cámara física RealSense.
    """
    # 200x200 = 40,000 puntos
    resolucion = 200
    x = np.linspace(-0.5, 0.5, resolucion)
    y = np.linspace(-0.5, 0.5, resolucion)
    xx, yy = np.meshgrid(x, y)
    
    # Animación basada en el tiempo
    frecuencia = 2.0 * math.pi * (t_ms / 1000.0) * 0.5
    zz = 1.0 + 0.15 * np.sin(5.0 * np.sqrt(xx**2 + yy**2) - frecuencia)
    
    points = np.stack((xx.ravel(), yy.ravel(), zz.ravel()), axis=-1).astype(np.float32)
    
    # Generar colores agradables (gradient RGB)
    r = ((xx.ravel() + 0.5) * 255).astype(np.uint8)
    g = ((yy.ravel() + 0.5) * 255).astype(np.uint8)
    b = ((zz.ravel() - 0.8) / 0.35 * 255).clip(0, 255).astype(np.uint8)
    colors = np.stack((r, g, b), axis=-1)
    
    return points, colors

class RealSenseCapturer:
    def __init__(self):
        self.pipeline = rs.pipeline()
        self.config = rs.config()
        self.config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
        self.config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        
        # Objeto de alineación (depth a color)
        self.align = rs.align(rs.stream.color)
        
        self.profile = None
        self.is_started = False
        
    def start(self):
        try:
            self.profile = self.pipeline.start(self.config)
            
            # Obtener y mostrar descripción del puerto USB
            device = self.profile.get_device()
            usb_type = "Desconocido"
            if device.supports(rs.camera_info.usb_type_descriptor):
                usb_type = device.get_info(rs.camera_info.usb_type_descriptor)
            print(f"[OK] Cámara RealSense iniciada correctamente (USB Type: {usb_type})")
            self.is_started = True
            return True
        except Exception as e:
            print(f"[ERROR] Error al iniciar la cámara RealSense física: {e}")
            return False
            
    def capture_frame(self):
        if not self.is_started:
            return None, None
            
        frames = self.pipeline.wait_for_frames()
        aligned_frames = self.align.process(frames)
        
        depth_frame = aligned_frames.get_depth_frame()
        color_frame = aligned_frames.get_color_frame()
        
        if not depth_frame or not color_frame:
            return None, None
            
        # Intrínsecos
        intrinsics = depth_frame.profile.as_video_stream_profile().intrinsics
        
        # Convertir a numpy arrays
        depth_image = np.asanyarray(depth_frame.get_data())
        color_image = np.asanyarray(color_frame.get_data())
        
        # Aplicar stride=2 (submuestreo rápido, reduce a 320x240)
        stride = 2
        depth_sub = depth_image[::stride, ::stride]
        color_sub = color_image[::stride, ::stride]
        
        h, w = depth_sub.shape
        
        # Precalcular mallas de índices u, v deproyectadas vectorialmente
        u = np.arange(w) * stride
        v = np.arange(h) * stride
        uu, vv = np.meshgrid(u, v)
        
        # Convertir profundidad a metros
        depth_scale = self.profile.get_device().first_depth_sensor().get_depth_scale()
        z_metros = depth_sub * depth_scale
        
        # Filtrado por rango de profundidad (0.3m a 1.5m)
        mask = (z_metros >= 0.3) & (z_metros <= 1.5)
        
        # Deproyección vectorial
        # X = (u - cx) * Z / fx
        # Y = (v - cy) * Z / fy
        # Z = Z
        x_coords = (uu - intrinsics.ppx) * z_metros / intrinsics.fx
        y_coords = -(vv - intrinsics.ppy) * z_metros / intrinsics.fy
        
        # Filtrar puntos y colores
        points = np.stack((x_coords[mask], y_coords[mask], z_metros[mask]), axis=-1).astype(np.float32)
        
        # RealSense captura BGR, convertimos a RGB para Unity
        colors_rgb = cv2.cvtColor(color_sub, cv2.COLOR_BGR2RGB)
        colors = colors_rgb[mask].astype(np.uint8)
        
        # Limitar número de puntos máximo (ej. 60,000 pts aleatorios si se supera)
        max_pts = 60000
        if len(points) > max_pts:
            idx = np.random.choice(len(points), max_pts, replace=False)
            points = points[idx]
            colors = colors[idx]
            
        return points, colors
        
    def stop(self):
        if self.is_started:
            self.pipeline.stop()
            self.is_started = False
            print("[INFO] Cámara RealSense detenida.")

def main():
    print("==========================================================")
    print("PRUEBA LOCAL DE CAPTURA Y COMPRESIÓN DRACO (F0)")
    print("==========================================================")
    print(f"Guardando salida en: {OUTPUT_PATH}")
    
    capturer = None
    use_simulation = True
    
    if REALSENSE_AVAILABLE and CV2_AVAILABLE:
        # Intentar iniciar la cámara física
        try:
            capturer = RealSenseCapturer()
            if capturer.start():
                use_simulation = False
        except Exception as e:
            print(f"[INFO] No se pudo iniciar el capturador RealSense: {e}")
            
    if use_simulation:
        print("[INFO] Modo simulación activo. Generando nube sintética...")
        
    print("\nIniciando bucle de captura y compresión. Presiona Ctrl+C para salir.\n")
    
    frame_count = 0
    try:
        while True:
            t_start = time.perf_counter()
            
            # 1. Captura o generación
            t_cap_start = time.perf_counter()
            if use_simulation:
                t_ms = int(time.time() * 1000)
                points, colors = generar_nube_sintetica(t_ms)
                time.sleep(0.03) # Simular tiempo de lectura a ~30fps
            else:
                points, colors = capturer.capture_frame()
                if points is None:
                    time.sleep(0.01)
                    continue
            t_cap_end = time.perf_counter()
            cap_time_ms = (t_cap_end - t_cap_start) * 1000
            
            n_points = len(points)
            if n_points == 0:
                print("[WARNING] Frame vacío (0 puntos). Omitiendo.")
                continue
                
            # 2. Compresión Draco
            t_enc_start = time.perf_counter()
            draco_bytes = b""
            if DRACO_AVAILABLE:
                # qp=11 (quantization bits)
                # compression_level=1 (Compresión ultra rápida)
                draco_bytes = DracoPy.encode(
                    points,
                    colors=colors,
                    quantization_bits=11,
                    compression_level=1
                )
            t_enc_end = time.perf_counter()
            encode_time_ms = (t_enc_end - t_enc_start) * 1000
            
            # 3. Guardado en fichero local para Unity (StreamingAssets)
            t_save_start = time.perf_counter()
            if len(draco_bytes) > 0:
                with open(OUTPUT_PATH, "wb") as f:
                    f.write(draco_bytes)
            t_save_end = time.perf_counter()
            save_time_ms = (t_save_end - t_save_start) * 1000
            
            # Calcular ratios
            raw_size_kb = (points.nbytes + colors.nbytes) / 1024.0
            draco_size_kb = len(draco_bytes) / 1024.0
            ratio = raw_size_kb / draco_size_kb if draco_size_kb > 0 else 1.0
            
            total_time_ms = (time.perf_counter() - t_start) * 1000
            
            frame_count += 1
            if frame_count % 10 == 0 or frame_count == 1:
                print(f"[Frame {frame_count:04d}] Puntos: {n_points:5d} | "
                      f"Raw: {raw_size_kb:6.1f} KB | Draco: {draco_size_kb:5.1f} KB (Ratio: {ratio:4.1f}x) | "
                      f"Tiempos: Cap={cap_time_ms:4.1f}ms, Enc={encode_time_ms:4.1f}ms, Guard={save_time_ms:3.1f}ms | "
                      f"Total={total_time_ms:4.1f}ms")
                      
            # Limitar la tasa de refresco a ~10 fps nominales para evitar saturación del disco
            time.sleep(max(0, 0.1 - (time.perf_counter() - t_start)))
            
    except KeyboardInterrupt:
        print("\n[INFO] Bucle terminado por el usuario.")
    finally:
        if capturer:
            capturer.stop()

if __name__ == "__main__":
    main()
