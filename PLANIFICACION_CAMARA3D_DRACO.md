# Planificación de Migración 2D → 3D: Nube de Puntos Comprimida con Draco

## 1. Objetivo y alcance de la rama experimental
Esta rama experimental (`Camara3D-Draco`) tiene como objetivo establecer la arquitectura, diseño y plan de fases detallado para sustituir la transmisión de vídeo 2D del sistema actual por una nube de puntos 3D en tiempo real. La nube de puntos se capturará con una cámara Intel RealSense, se procesará y deproyectará en Python, se comprimirá con Draco para reducir el volumen de datos y se transmitirá por WebRTC a las gafas de Realidad Virtual (Meta Quest) para su decodificación y visualización tridimensional interactiva.
El alcance de esta rama es meramente de diseño y planificación técnica; en este paso no se implementa el código del pipeline ejecutable en producción, pero se dejan sentadas las bases y la estructura de archivos e integraciones futuras.

## 2. Estado de partida
El sistema actual en la rama `WithMetrics` teleopera un brazo robótico RoArm-M2:
- **Control**: Unity (Meta Quest, XR Hands) envía las coordenadas normalizadas `{x,y,z,g}` de la mano del operador mediante un DataChannel WebRTC dedicado ("comandos").
- **Vídeo 2D**: El PC-Robot recibe la información, controla el brazo vía serie y captura vídeo 2D (a través de `CameraVideoTrack` de `aiortc`, 640×480 @ 30 fps, ~3-5 Mbps) reenviándolo a Unity, que lo proyecta en un elemento `RawImage`.
- **Métricas**: Existe un sistema de medición de RTT, jitter, y latencia de vídeo Glass-to-Glass (G2G) utilizando la diferencia de tiempo entre captura y recepción con clocks sincronizados por RTT.

## 3. Decisiones de diseño
Para migrar este pipeline a una visualización 3D inmersiva, se confirman las siguientes decisiones:
1. **Cámara 3D**: Intel RealSense serie D (D435 o similar) empleando el SDK oficial `pyrealsense2` en Python.
2. **Visualización**: La nube de puntos se visualizará directamente en el entorno de Realidad Virtual (Quest), con lo cual el proceso de decodificación y renderizado se realiza localmente en el visor.
3. **Transporte de Nube**: Se empleará un DataChannel WebRTC dedicado llamado `"nube3d"` para canalizar la nube de puntos comprimida binaria, manteniendo "comandos" en su canal existente.
4. **Compresión**: Uso de la librería de compresión 3D Draco (a través de `DracoPy` en Python y `com.unity.cloud.draco` en Unity/C#).

## 4. Arquitectura del pipeline 3D end-to-end
A continuación se detalla el flujo de datos e interacción entre los componentes en la arquitectura 3D propuesta:

```
PC-ROBOT (Python 3.11.9)                          Quest (Unity 6000.3.10f1, Android)
========================                          ==================================
RealSense D435 depth+color 640×480@30             ScriptWebRTC.cs
  │                                                 ├ DataChannel "comandos" (existente, intacto)
  ├──► 1. Alineación (rs.align depth→color)        └ DataChannel "nube3d" (NUEVO, binario)
  │                                                     │
  ├──► 2. Submuestreo y recorte (Z 0.3-1.5m,            ▼
  │       stride 2 numpy a 320x240)                 NubeReceiver.cs (reensamblado chunks)
  │                                                     │
  ├──► 3. Deproyección vectorial numpy                  ▼
  │       (usando mallas (u-cx)/fx)                 NubeDracoDecoder.cs (com.unity.cloud.draco)
  │                                                     │
  ├──► 4. Filtro (cap 60k pts aleatorio)                ▼
  │                                                 NubeRenderer.cs (MeshTopology.Points)
  ├──► 5. Compresión DracoPy.encode                     │   (escala (1,-1,1) para corregir ejes)
  │       (qp=11, compression_level=1)                  ▼
  │                                                 Render en Quest (Shader URP con PSIZE
  ├──► 6. Segmentación (chunks de 16 KiB)           o quads instanciados como plan B)
  │
  └──► Enviar vía DataChannel "nube3d" ─────────────► (Fallback: RawImage vídeo 2D conmutable)
```

### Etapas detalladas del Pipeline:
1. **Captura y Alineación**: RealSense captura los frames de color y profundidad sincronizados a 640×480 a 30 fps. Se realiza la alineación del mapa de profundidad al frame de color.
2. **Pre-procesado y Filtrado**: Se aplica un stride de 2 (reducción a 320×240) y se limitan los puntos al rango de interés físico (0.3 a 1.5 metros).
3. **Deproyección Vectorizada**: Usando matrices precalculadas de las coordenadas de píxeles y los intrínsecos de la cámara en NumPy, se deproyecta cada píxel a coordenadas cartesianas 3D `(X, Y, Z)` de forma vectorial acelerada en CPU.
4. **Submuestreo**: Se limita el número total de puntos a enviar a un máximo de 60,000 mediante un submuestreo aleatorio rápido.
5. **Compresión**: Se pasan los arrays de puntos `(float32)` y colores `(uint8)` a `DracoPy.encode` configurando cuantización `qp=11` y nivel de compresión `1` (priorizando velocidad frente a ratio de compresión).
6. **Segmentación y Envío**: La trama comprimida se serializa precedida de una cabecera de control de 26 bytes y se divide en chunks de 16 KiB para ser transmitidos.
7. **Negociación y Fallback**: El pipeline de vídeo 2D actual se mantiene como una opción de fallback alternativo seleccionable en configuración.

## 5. Protocolo de transporte "nube3d"
La transmisión de las mallas Draco a través de WebRTC se estructurará mediante el DataChannel `"nube3d"` de la siguiente manera:

- **Establecimiento de canal**: Unity crea el DataChannel `"nube3d"` en `CrearOferta()` junto con `"comandos"`. Python escucha en `@pc.on("datachannel")` y discrimina los canales por su `channel.label` (`"comandos"` o `"nube3d"`). No es necesario modificar `signaling_server.py`.
- **Chunking (Segmentación)**: Para evitar cuellos de botella y problemas de tamaño máximo de mensaje SCTP (aiortc anuncia 64 KiB y Unity/libwebrtc 256 KiB), la trama total de la nube de puntos se dividirá en chunks de **16 KiB**.
- **Cabecera binaria (26 bytes)**: Cada chunk comienza con una cabecera binaria estructurada en formato Little-Endian (`struct.pack("<HBBIHHQIH")`):
  - `magic` (2 bytes): Identificador constante `0x4E33` ("N3").
  - `version` (1 byte): Versión del protocolo (inicialmente `1`).
  - `flags` (1 byte): Bandera de control (ej. bit 0 indica fallback 2D activo).
  - `frame_id` (4 bytes): Identificador único de frame autoincremental `uint32`.
  - `chunk_idx` (2 bytes): Índice del chunk actual `uint16` (0-indexed).
  - `n_chunks` (2 bytes): Cantidad total de chunks de este frame `uint16`.
  - `t_captura` (8 bytes): Marca de tiempo de la captura en milisegundos Unix `uint64` (equivale al `frame_ts` para la métrica).
  - `n_puntos` (4 bytes): Número total de puntos en el frame `uint32`.
  - `encode_ms_x10` (2 bytes): Tiempo de compresión Draco en milisegundos multiplicado por 10 `uint16`.
- **Fiabilidad**: Se configurará en Fase 1 con `ordered=true` por simplicidad, pero el objetivo final para minimizar la latencia por retransmisiones es configurar el canal como `unordered` y con `maxRetransmits=0`. En Unity, el script reensamblador descartará cualquier chunk perteneciente a un `frame_id` anterior o que tenga un retraso en reensamblado >250 ms.
- **Control de Congestión (Backpressure)**: En Python, antes de codificar y enviar un frame, se evalúa `channel.bufferedAmount`. Si el buffer supera los 512 KiB, se descarta el frame completo incrementando el contador de omitidos (skips), previniendo retrasos acumulados en la red.
- **Alternativa descartada**: Se evaluó codificar la profundidad en los canales de color de una pista de vídeo 2D estándar (ej. codificación en los bits del formato RGB). Sin embargo, los códecs de vídeo con pérdida (H.264, VP8) destruyen los bits menos significativos arruinando la precisión de la profundidad. Además, este método no permite experimentar con compresión Draco nativa 3D, que es el eje central de este desarrollo.

## 6. Presupuesto de ancho de banda y latencia
### Consumo de datos (Ancho de banda)
- **Bruto sin comprimir (640×480)**: 307,200 puntos × 15 bytes (XYZ float32 + RGB 3 bytes) ≈ **4.6 MB/frame** (inaccesible a 30 fps).
- **Bruto submuestreado (stride 2 + rango de distancia)**: ~40k-50k puntos ≈ **600-750 KB/frame**.
- **Comprimido con Draco (qp=11)**: Estimación de 2 a 2.5 bytes por punto (pérdida de precisión sub-milimétrica tolerable, inferior al ruido de la cámara) ≈ **60-150 KB/frame**.
- **Caudal de red estimado (Draco)**:
  - *Modo Bajo* (10 fps, 30k pts): **~4.8 Mbps** (equivalente al vídeo 2D).
  - *Modo Nominal* (10 fps, 50k pts): **~10 Mbps**.
  - *Modo Alto* (15 fps, 50k pts): **~15 Mbps**.
  Todas estas opciones son perfectamente viables en una red WiFi local de alta velocidad (medida en torno a 280 Mbps) o Ethernet (1 Gbps).

### Latencia estimada del Pipeline
Para cumplir el requisito de control interactivo inmersivo, se marca como objetivo una latencia media Glass-to-Glass (G2G) **< 150 ms** y un percentil 95 (P95) **< 250 ms**:

| Etapa | Latencia Estimada |
|---|---|
| Captura + Alineación RealSense | 3 - 8 ms |
| Stride, filtrado por distancia y submuestreo NumPy | 2 - 6 ms |
| Deproyección y empaquetado NumPy | 2 - 4 ms |
| Compresión DracoPy en Executor (Subproceso) | 5 - 20 ms |
| Tránsito de red (incluyendo fragmentación de chunks) | 10 - 30 ms |
| Reensamblado y decodificación Draco en Quest (C# Jobs) | 5 - 30 ms |
| Subida a GPU y Renderizado Quest | 5 - 14 ms |
| **Total Estimado G2G** | **32 - 112 ms (+ retraso de frame 66-100 ms)** |

## 7. Plan de fases (F0 a F5)
La implementación progresiva se divide en seis fases bien acotadas para aislar problemas técnicos antes de integrar componentes:

### F0 — Spike de viabilidad (Local y sin red)
- **Objetivo**: Validar el roundtrip de compresión/descompresión local, comprobar rendimiento de DracoPy en Python 3.11, la integración del paquete Draco de Unity en Quest y el método de renderizado de puntos en VR.
- **Archivos Modificados/Nuevos**:
  - `[NEW]` [prueba_realsense_draco_local.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/Pruebas_Conexion/Scripts_De_Prueba/prueba_realsense_draco_local.py)
  - `[MODIFY]` [requirements.txt](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/requirements.txt)
  - `[MODIFY]` [manifest.json](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/Packages/manifest.json)
  - `[NEW]` `Assets/Scenes/EscenaPruebaDraco.unity`
  - `[NEW]` `Assets/Scripts/Scripts_Pruebas_Nube3D/PruebaDecodeDracoLocal.cs`
  - `[NEW]` `Assets/Shaders/NubePuntos.shader` (Shader URP simple con soporte de PSIZE).
- **Criterios de Éxito**:
  - Instalación limpia de `pyrealsense2` y `DracoPy` sobre numpy 2.4.6 sin romper dependencias.
  - Velocidad de encode DracoPy para 50k puntos ≤ 20 ms en CPU.
  - Generación de fichero `.drc` local correcto.
  - El paquete Unity `com.unity.cloud.draco` decodifica la nube Draco en el Quest con éxito.
  - Renderizado visible de la nube en Quest en el Editor y dispositivo real (usando PointTopology o quads instanciados como plan B).

### F1 — Emisor Python + Mock Receptor en PC (Aislamiento de Red)
- **Objetivo**: Implementar el pipeline emisor completo en Python, la segmentación en chunks y validar el transporte WebRTC de la nube hacia un simulador receptor en PC sin usar las gafas de VR.
- **Archivos Modificados/Nuevos**:
  - `[NEW]` [realsense_manager.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Camara3D/realsense_manager.py)
  - `[NEW]` [draco_encoder.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Camara3D/draco_encoder.py)
  - `[NEW]` [nube_protocolo.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Camara3D/nube_protocolo.py)
  - `[NEW]` [prueba_nube3d_emisor.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/Pruebas_Conexion/Scripts_De_Prueba/prueba_nube3d_emisor.py)
  - `[NEW]` [mock_unity_nube3d.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Simuladores/mock_unity_nube3d.py)
- **Criterios de Éxito**:
  - Envío estable a 10-15 fps sostenidos durante 5 minutos en red local PC-PC.
  - 0% de corrupción de datos reensamblados en canal fiable.
  - Tráfico medio total de nube ≤ 12 Mbps.
  - `bufferedAmount` estable en Python sin desbordamientos de buffer.

### F2 — Unity Recibe, Decodifica y Renderiza (Red Completa)
- **Objetivo**: Integrar en Unity la recepción WebRTC por el DataChannel `"nube3d"`, el reensamblado de chunks, la decodificación Draco en background y el pintado en tiempo real en la escena VR.
- **Archivos Modificados/Nuevos**:
  - `[MODIFY]` [ScriptWebRTC.cs](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/Assets/Scripts/Scripts_WebRTC/ScriptWebRTC.cs)
  - `[NEW]` `Assets/Scripts/Scripts_Nube3D/NubeReceiver.cs`
  - `[NEW]` `Assets/Scripts/Scripts_Nube3D/NubeDracoDecoder.cs`
  - `[NEW]` `Assets/Scripts/Scripts_Nube3D/NubeRenderer.cs`
  - `[NEW]` `Assets/Scripts/Scripts_Pruebas_Nube3D/NubeLatencyMedidor.cs`
  - `[NEW]` `Assets/Scenes/EscenaPruebaNube3D.unity`
- **Criterios de Éxito**:
  - Renderizado fluido en Quest a ≥ 10 fps estables y tasa de refresco VR a 72 Hz.
  - Latencia G2G media < 150 ms y P95 < 250 ms en red Gigabit Ethernet.
  - Generación de CSV de latencia con formato idéntico al de vídeo para retrocompatibilidad de análisis.

### F3 — Integración en safe8_WebRTC.py (Teleoperación + Nube)
- **Objetivo**: Integrar la nube en el backend unificado, permitiendo teleoperar el robot físicamente mientras se observa la escena en 3D.
- **Archivos Modificados/Nuevos**:
  - `[MODIFY]` [safe8_WebRTC.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Control_Brazo/safe8_WebRTC.py)
  - `[MODIFY]` [config.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Configuracion/config.py)
  - `[MODIFY]` `Assets/Scenes/EscenaPrincipal.unity` (Toggle en el panel de control de Unity).
- **Criterios de Éxito**:
  - Envío simultáneo de teleoperación y recepción de nube 3D.
  - El RTT del canal de control `"comandos"` no debe incrementarse más de un 10% por la carga de la nube.
  - Funcionamiento continuo sin memory leaks ni cuelgues del loop de Python durante 10 minutos.
  - Corrección del sombreado de variable `config` en `safe8_WebRTC.py:259` renombrándola a `rtc_config`.

### F4 — Campaña de métricas y análisis de datos
- **Objetivo**: Analizar la eficiencia de la compresión Draco frente al vídeo 2D tradicional bajo perfiles de carga de red emulados con Clumsy/iperf3.
- **Archivos Modificados/Nuevos**:
  - `[NEW]` [analisis_nube3d.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Analisis_Datos/analisis_nube3d.py)
  - `[NEW]` `Assets/Scripts/Scripts_Metricas/NubeMetricsLogger.cs`
  - `[NEW]` `Pruebas_Conexion/Documentos_De_Analisis/Guia_Pruebas_Nube3D.md`
  - `[MODIFY]` [generar_comparativa.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Analisis_Datos/generar_comparativa.py) (Corregir ruta absoluta `ROOT_DIR` hardcodeada).
  - `[MODIFY]` [generar_graficos_tfg.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Analisis_Datos/generar_graficos_tfg.py) (Corregir ruta absoluta `ROOT_DIR` hardcodeada).
- **Criterios de Éxito**:
  - Generación de métricas de FPS real, bytes/frame, ratio de compresión Draco y descarte.
  - Tabla comparativa automatizada y gráficas de latencia y jitter de nube 3D vs vídeo 2D.

### F5 — Trabajo Futuro (Líneas de Investigación)
- **Objetivo**: Documentar las posibles optimizaciones avanzadas fuera del alcance de la implementación base (filtrado voxel-grid espacial, alineación temporal TSDF, reducción de redundancias por keyframes de nube, codificación delta 3D).

## 8. Metodología de métricas 3D
Para medir la latencia y pérdida del nuevo canal de nube de puntos se aprovechará la lógica existente de vídeo 2D:
- **Latencia in-band**: La marca de tiempo de captura (`t_captura`) viaja dentro del chunk. Unity calcula la latencia G2G restando este valor del tiempo local tras aplicar el `ClockOffsetMs` medido en los pings periódicos.
- **Formato CSV de Latencia**: Unity registrará la latencia en un archivo CSV con la misma cabecera y estructura que el de vídeo (`t_sesion,latencia_ms,t_captura,t_recibido`), permitiendo que el script `analisis_video.py` lo lea y procese para calcular medias, percentiles e histogramas sin modificaciones estructurales.
- **Estadísticas Adicionales**: Se añadirán dos CSV nuevos exportados desde la función `csv_export` del sistema:
  - *Robot*: `nube3d_robot_{sesion}.csv` (campos: `frame_id`, `n_puntos`, `bytes_raw`, `bytes_draco`, `ratio_compresion`, `encode_ms`, `estado`).
  - *Unity*: `nube3d_unity_{sesion}.csv` (campos: `frame_id`, `latencia`, `bytes`, `n_puntos`, `decode_ms`, `chunks_recibidos`, `chunks_descartados`).
  Los archivos se guardarán en la nueva carpeta `Pruebas_Conexion/Resultados_Nube3D/`.

## 9. Riesgos y mitigaciones
A continuación se recopilan los riesgos identificados en la arquitectura propuesta y cómo mitigarlos durante la fase F0:

| Riesgo | Impacto | Mitigación / Plan B |
|---|---|---|
| **Incompatibilidad de DracoPy** | Crítico | DracoPy podría dar conflictos con la versión numpy 2.4.6. En F0 se validará su importación y, si falla, se compilará desde fuentes o se usará un binario externo `draco_encoder.exe` llamado mediante subproceso. |
| **Problemas de decodificación en Unity** | Alto | El paquete `com.unity.cloud.draco` está optimizado para mallas tridimensionales con caras. Podría dar problemas al decodificar nubes puras de puntos. En F0 se probará con mallas de puntos sin caras y, si falla, se invocará manual y nativamente la DLL `libdraco` mediante P/Invoke. |
| **PSIZE no soportado en Quest** | Alto | El tamaño de punto en el shader (`PSIZE`) a veces es ignorado por los drivers de Vulkan/Adreno en Android/Quest. En F0 se validará si se renderizan con tamaño correcto. El Plan B es usar quads instanciados mediante un GraphicsBuffer. |
| **CPU del Quest insuficiente** | Alto | La decodificación Draco a 10 fps podría saturar el procesador móvil del Quest. Se mitigará usando las llamadas asíncronas de la API de Draco con Jobs/Burst, y si no es suficiente, limitando la nube a un rango de 25k-30k puntos o bajando los fps nominales a 5-8. |
| **Rendimiento SCTP en aiortc** | Medio | Al ser aiortc una librería en Python puro, el throughput de envío de múltiples chunks binarios podría elevar la latencia en CPU. Se comprobará en F1; de ser crítico, se optimizará el tamaño de chunk o se reducirá el frame rate. |
| **Congestión del DataChannel de control** | Alto | La transferencia a ráfagas de la nube en la misma asociación SCTP que los comandos del brazo podría retrasar el envío del control. Se implementará una monitorización estricta del RTT del brazo en F3, aplicando backpressure agresivo si RTT aumenta >10%. |
| **RealSense en USB 2.0** | Medio | Si la cámara se conecta a un puerto USB 2.0, el SDK limitará la resolución o el bitrate. Se validará al inicializar el driver mediante `usb_type_descriptor`, lanzando una advertencia y degradando la resolución de captura automáticamente a 424×240. |

## 10. Configuración y dependencias
Para habilitar el pipeline de nube de puntos en el proyecto, se configuran las siguientes entradas:

### config.py (Configuración global)
Se añade la sección de parámetros para la cámara 3D y compresión:
```python
# CONFIGURACIÓN CÁMARA 3D (REAL SENSE & DRACO)
REALSENSE_RESOLUCION = (640, 480)
REALSENSE_FPS = 30
REALSENSE_RANGO_Z = (0.3, 1.5)  # En metros
REALSENSE_STRIDE = 2             # Submuestreo por pasos (equivale a 320x240)
NUBE_MAX_PUNTOS = 60000
NUBE_FPS_OBJETIVO = 10
DRACO_QP = 11                    # Cuantización de posición
DRACO_NIVEL_COMPRESION = 1       # Priorizar velocidad
NUBE_CHANNEL_LABEL = "nube3d"
NUBE_CHUNK_BYTES = 16384         # Chunks de 16 KiB
NUBE_BUFFER_MAX_BYTES = 524288   # Límite de control de congestión (512 KiB)
```

### PC-ROBOT/requirements.txt (Nuevas dependencias Python)
Se congela el venv actual y se agregan las siguientes librerías de soporte 3D:
```text
pyrealsense2
DracoPy
# (más el resto de librerías del venv de WithMetrics ya existentes)
```

### Packages/manifest.json (Unity)
Se agregará la dependencia al paquete de Draco oficial de Unity:
```json
"com.unity.cloud.draco": "5.4.0"
```
