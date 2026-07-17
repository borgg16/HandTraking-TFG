import sys
import pyrealsense2 as rs
import numpy as np
import cv2

# Configurar consola en Windows para UTF-8 y evitar errores de encoding
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')

print("Iniciando cámara RealSense...")
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

align = rs.align(rs.stream.color)

try:
    pipeline.start(config)
    print("[OK] Cámara iniciada. Abre la ventana 'RealSense (Color | Depth)' en tu escritorio.")
    print("Presiona la tecla 'q' en esa ventana para salir.")
    while True:
        frames = pipeline.wait_for_frames()
        aligned_frames = align.process(frames)
        depth_frame = aligned_frames.get_depth_frame()
        color_frame = aligned_frames.get_color_frame()
        if not depth_frame or not color_frame:
            continue
            
        depth_image = np.asanyarray(depth_frame.get_data())
        color_image = np.asanyarray(color_frame.get_data())
        
        # Convertir profundidad a una imagen visible coloreada (colormap)
        depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET)
        
        # Concatenar color y profundidad horizontalmente
        images = np.hstack((color_image, depth_colormap))
        
        cv2.imshow('RealSense (Color | Depth)', images)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
finally:
    pipeline.stop()
    cv2.destroyAllWindows()
    print("[INFO] Cámara detenida y ventanas cerradas.")
