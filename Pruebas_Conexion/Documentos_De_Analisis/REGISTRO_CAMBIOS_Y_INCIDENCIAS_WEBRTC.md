# Registro de Cambios, Incidencias y Soluciones Técnicas — WebRTC & Control Robot

**Proyecto:** TFG HandTracking — Teleoperación Robótica mediante WebRTC y Unity XR  
**Fecha de actualización:** 3 de agosto de 2026  
**Ubicación de módulos afectados:** `PC-ROBOT/Control_Brazo/safe8_WebRTC.py`, `PC-ROBOT/Control_Brazo/signaling_server.py`, `Assets/Scripts/Scripts_WebRTC/ScriptWebRTC.cs`

---

## 1. Resumen Ejecutivo de Arquitectura de Comunicación

El sistema de comunicación del proyecto consta de tres actores clave:
1. **Cliente Unity XR (Gafas Meta Quest):** Captura el seguimiento de manos y envía coordenadas normalizadas a través de un `DataChannel` de WebRTC, además de recibir el *stream* de vídeo H.264/VP8 de la cámara del robot.
2. **Servidor de Señalización (`signaling_server.py`):** Servidor WebSocket en Python (`aiohttp`/`websockets`) que actúa como intermediario para el intercambio de mensajes SDP (oferta/respuesta) y candidatos ICE.
3. **Controlador del Brazo Robot (`safe8_WebRTC.py`):** Proceso en Python que se conecta al hardware del robot vía puerto serie (`COM9` @ 115200 baudios), inicializa la cámara USB, establece la `RTCPeerConnection` con Unity y convierte las coordenadas en comandos cinemáticos cinemáticamente seguros para el brazo RoArm-M2.

---

## 2. Registro de Incidencias Detectadas y Resoluciones Aplicadas

### Incidencia 1: Conflicto de Nombres y Sombreado de Variables (`UnboundLocalError`)
- **Síntoma:** Al ejecutar `safe8_WebRTC.py`, la ejecución fallaba inmediatamente en el momento de la autenticación con la señalización.
- **Trazado de error:**
  ```text
  UnboundLocalError: cannot access local variable 'config' where it is not associated with a value
  ```
- **Causa raíz:** En la función `ejecutar_webrtc()`, la variable local que configuraba los servidores STUN para `aiortc` fue nombrada `config = RTCConfiguration(...)`. En Python, la asignación a una variable dentro del ámbito local convierte dicho identificador en local para toda la función. Esto provocaba que el intento previo de leer `config.SESSION_TOKEN` (del módulo importado `import config`) fallara por acceder a una variable local no asignada aún.
- **Solución implementada:** Se renombró la variable local a `rtc_config = RTCConfiguration(...)`, liberando el espacio de nombres para el módulo importado `config.py`.
- **Fichero modificado:** [safe8_WebRTC.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Control_Brazo/safe8_WebRTC.py#L259)

---

### Incidencia 2: Error al Añadir Pista de Vídeo Duplicada (`InvalidAccessError`)
- **Síntoma:** Tras la primera oferta SDP procesada con éxito, la recepción de una re-oferta o mensaje duplicado provocaba el colapso del controlador en Python.
- **Trazado de error:**
  ```text
  aiortc.exceptions.InvalidAccessError: Track already has a sender
  ```
- **Causa raíz:** `aiortc` requiere que cada `MediaStreamTrack` asociado a una `RTCPeerConnection` posea un único emisor (`RTCRtpSender`). El bucle de eventos WebSocket ejecutaba `pc.addTrack(video_track)` incondicionalmente cada vez que recibía un mensaje `type == "offer"`.
- **Solución implementada:** Se añadió una guarda de comprobación previa:
  ```python
  if not pc.getSenders():
      pc.addTrack(video_track)
  ```
- **Nota (revisión del 3-ago-2026):** Con la recreación de la PC por oferta introducida en la **Incidencia 3**, cada oferta usa una `RTCPeerConnection` nueva y sin emisores, por lo que `pc.addTrack(video_track)` nunca choca con un emisor previo. La guarda `getSenders()` deja de ser necesaria y el código actual añade el track directamente sobre la PC recién creada.
- **Ficheros modificados:**
  - [safe8_WebRTC.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Control_Brazo/safe8_WebRTC.py#L387)
  - [safe8_WebRTC_PRUEBA_SIN_BRAZO.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Control_Brazo/safe8_WebRTC_PRUEBA_SIN_BRAZO.py#L398)

---

### Incidencia 3: Incapacidad de Manejar Reconexiones en Estado Cerrado (`InvalidStateError`)
- **Síntoma:** Si el usuario reiniciaba la app en las gafas, se desconectaba temporalmente o la conexión ICE pasaba a estado `closed`, cualquier intento posterior de reconexión por parte de Unity hacía que Python colapsara.
- **Trazado de error:**
  ```text
  aiortc.exceptions.InvalidStateError: Cannot handle offer in signaling state "closed"
  ```
- **Causa raíz:** Cuando el estado de la conexión ICE pasaba a `closed` o `failed`, el callback `on_ice_change()` cerraba la conexión llamando a `await pc.close()`. El socket WebSocket continuaba abierto. Al recibir Unity una nueva oferta SDP, el script intentaba invocar `await pc.setRemoteDescription(desc)` sobre el objeto `pc` en estado `closed`, lo cual no está permitido por la especificación WebRTC.
- **⚠️ Hallazgo importante (revisión del 3-ago-2026):** La solución que aparecía descrita en este registro (función fábrica `crear_pc()` + comprobación `if pc.signalingState == "closed"`) **nunca llegó a estar implementada en el código que se ejecutaba**. `safe8_WebRTC.py` seguía creando **una única** `RTCPeerConnection` fuera del bucle de señalización y **reutilizándola** para todas las ofertas. Esta es la causa real de que el vídeo dejara de mostrarse en las gafas tras la primera sesión: en cuanto el usuario volvía a dar a *Play* / reconectaba, la nueva oferta caía sobre una PC ya cerrada.
- **Cómo se reprodujo:** Se levantó el flujo completo (servidor de señalización real + par robot con la lógica de `safe8` + par que imita a `ScriptWebRTC`) sobre `localhost`. Con la PC reutilizada, la **sesión 1 funcionaba** (`OnTrack` disparado, estado `stable`) pero la **sesión 2** producía en el robot:
  ```text
  InvalidStateError: Cannot handle offer in signaling state "closed"
  ```
  y el robot ya no enviaba `answer`, dejando a Unity sin vídeo (o aplicando un `answer` rezagado → ver Incidencia 5).
- **Solución implementada (real y verificada):** Se **recrea la `RTCPeerConnection` y el `CameraVideoTrack` en cada oferta**. Como `on_datachannel` no depende de la PC concreta, se define una sola vez y se re-registra con `pc.on("datachannel", on_datachannel)`; el handler de ICE se registra por sesión capturando la PC **por valor** para no cerrar por error una PC de una reconexión posterior:
  ```python
  if pc is not None:                      # había una sesión previa
      await pc.close()
      video_track.detener()               # libera la cámara
      video_track = CameraVideoTrack(args.camera)

  pc = RTCPeerConnection(configuration=rtc_config)
  pc.on("datachannel", on_datachannel)

  @pc.on("iceconnectionstatechange")
  async def on_ice_change(_pc=pc):        # _pc=pc fija la PC de ESTA sesión
      if _pc.iceConnectionState == "failed":
          await _pc.close()
  ```
  También se protege la cola de candidatos ICE frente a `pc is None` (antes de la primera oferta) para no perder los candidatos que llegan por *trickle* antes del `setRemoteDescription`.
- **Verificación:** Con la PC recreada por oferta, tres sesiones consecutivas (S1→S2→S3) completan la negociación y disparan `OnTrack` en el receptor. Esto hace innecesaria la guarda de la Incidencia 2 (cada oferta usa una PC nueva sin emisores previos).
- **Fichero modificado:** [safe8_WebRTC.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/PC-ROBOT/Control_Brazo/safe8_WebRTC.py#L377-L408)

---

### Incidencia 4: Ausencia de Señal de Vídeo en Unity por Escala de Tiempo RTP Incompatible
- **Síntoma:** La conexión DataChannel funcionaba correctamente (permitiendo el control cinemático y movimiento del robot), pero Unity no renderizaba la textura del stream de vídeo de la cámara (pantalla/textura de vídeo en negro o vacía).
- **Causa raíz:** En la clase `CameraVideoTrack`, la propiedad `pts` (Presentation Time Stamp) se incrementaba secuencialmente de 1 en 1 (`0, 1, 2...`) con una base de tiempo de `1/30` (`fractions.Fraction(1, CAM_FPS)`). El estándar del protocolo RTP para streams de vídeo (H.264/VP8) en WebRTC especifica una frecuencia de reloj de **90.000 Hz** (`90 kHz`). El decodificador de vídeo de Unity descartaba los paquetes RTP entrantes debido a la inconsistencia en los timestamps de presentación.
- **Solución implementada:**
  1. Se definió la tasa de reloj oficial RTP para vídeo: `VIDEO_CLOCK_RATE = 90000` y `VIDEO_TIME_BASE = fractions.Fraction(1, 90000)`.
  2. Se implementó el método de sincronización de ritmo `_next_timestamp()`, calculando los deltas de marca de tiempo en pasos de `90000 / 30 = 3000` unidades por frame:
     ```python
     pts, time_base = await self._next_timestamp()
     video_frame.pts = pts
     video_frame.time_base = time_base
     ```
- **⚠️ Matización (revisión del 3-ago-2026):** Esta implementación explícita de reloj a 90 kHz vive en el **script de pruebas** `prueba_latencia_video.py`, **no** en `safe8_WebRTC.py`. `safe8_WebRTC.py` usa `video_frame.time_base = fractions.Fraction(1, CAM_FPS)` (`1/30`) con `pts` incremental de 1 en 1. **Esto NO es un defecto:** `aiortc` reescala internamente cada frame al reloj RTP de 90 kHz mediante `convert_timebase(frame.pts, frame.time_base, VIDEO_TIME_BASE)` en el codificador (`codecs/vpx.py` y `codecs/h264.py`), de modo que el frame *N* obtiene el mismo timestamp RTP (`N·3000`) con ambas representaciones. Se verificó con un *handshake* real que el `answer` es válido y que `OnTrack` se dispara con el track a `1/30`. Por tanto, **la ausencia de vídeo no se debía a los timestamps**, sino a los fallos de ciclo de vida de la conexión (Incidencias 1 y 3). No se modificó la base de tiempo de `safe8`.
- **Fichero de referencia (implementación 90 kHz):** [prueba_latencia_video.py](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/Pruebas_Conexion/Scripts_De_Prueba/prueba_latencia_video.py)

---

### Incidencia 5: Unity — `SetRemoteDescription` "Called in wrong state: stable"
- **Síntoma (último error observado en las gafas):** Al recibir la respuesta SDP del robot, Unity fallaba en `SetRemoteDescription` indicando que la llamada era errónea *"in state: stable"*, y el vídeo no llegaba a mostrarse.
- **Trazado de error (lado Unity):**
  ```text
  Error en SetRemoteDescription: Failed to set remote answer sdp: Called in wrong state: kStable
  ```
- **Causa raíz:** Una `RTCPeerConnection` que actúa de *offerer* solo admite un `answer` cuando está en estado `HaveLocalOffer`. Si a Unity le llega un `answer` **duplicado o rezagado** —típicamente el `answer` de una sesión anterior que aún viajaba por la señalización cuando las gafas ya habían reconectado con una PC nueva en estado `stable`, situación provocada aguas arriba por el bug de reutilización de PC de la **Incidencia 3**— la `PeerConnection` ya está en `stable` y `SetRemoteDescription(answer)` es rechazado, abortando la negociación de vídeo. El método `AplicarAnswer` aplicaba el `answer` sin comprobar el estado de señalización.
- **Solución implementada:** Guarda de estado en `AplicarAnswer`. Se ignora (con aviso) cualquier `answer` que no llegue estando en `HaveLocalOffer`, en lugar de dejar que reviente la negociación:
  ```csharp
  if (peerConnection == null) { yield break; }
  if (peerConnection.SignalingState != RTCSignalingState.HaveLocalOffer)
  {
      Debug.LogWarning($"Answer ignorado: estado = {peerConnection.SignalingState} " +
                       "(se esperaba HaveLocalOffer). Answer duplicado o de sesión previa.");
      yield break;
  }
  ```
  Esta guarda es defensiva y complementa la corrección de fondo (Incidencia 3): al recrear el robot su PC por oferta, ya no se generan `answer` sobre PCs muertas; y si aun así llegara uno rezagado, Unity lo descarta limpiamente sin romper la sesión válida.
- **Fichero modificado:** [ScriptWebRTC.cs](file:///c:/Users/franm/Desktop/universidad/TFG/TFG_COMPLETO/HandTraking-TFG/Assets/Scripts/Scripts_WebRTC/ScriptWebRTC.cs#L520)

---

## 3. Estado de Despliegue y Procedimiento de Ejecución

Para iniciar únicamente la infraestructura necesaria en producción (sin mocks ni pruebas de desarrollo):

1. **Iniciar Servidor de Señalización:**
   ```powershell
   .\PC-ROBOT\venv_robot\Scripts\python.exe PC-ROBOT\Control_Brazo\signaling_server.py
   ```
   *Escucha en `ws://192.168.3.28:8080`.*

2. **Iniciar Control del Brazo Robot:**
   ```powershell
   .\PC-ROBOT\venv_robot\Scripts\python.exe PC-ROBOT\Control_Brazo\safe8_WebRTC.py COM9 --ip 192.168.3.28
   ```
   *Abre comunicación serie en `COM9`, inicia la captura de vídeo de la cámara 0 y aguarda oferta WebRTC de Unity.*

---

## 4. Diagnóstico del fallo "el vídeo no se muestra en las gafas" (revisión 3-ago-2026)

**Pregunta de partida:** el vídeo funcionaba en las pruebas aisladas (`prueba_latencia_video.py`) pero no en `safe8_WebRTC.py`.

**Conclusiones tras auditar el código real (no solo la documentación):**
1. **La lógica de negociación WebRTC de `safe8` era idéntica a la versión "COMPLETAMENTE FUNCIONAL"** del historial de Git y el `answer` que genera es estructuralmente correcto (mismo nº de líneas `m=`, `m=video` en `sendonly`, aplicar el `answer` lleva al *offerer* de `have-local-offer` a `stable`). El problema **no** estaba en el SDP ni en el códec/timestamps.
2. **Por qué la prueba funcionaba y `safe8` no:** el script de prueba importa la configuración como `import config as central_config`, mientras que `safe8` la importaba como `import config` **y** reutilizaba el nombre `config` para el `RTCConfiguration` local → `UnboundLocalError` en la autenticación (**Incidencia 1**). La prueba nunca sufría ese choque de nombres. Corregido con `rtc_config`.
3. **Por qué seguía fallando tras corregir la autenticación (y de dónde salía el "in state: stable"):** `safe8` creaba **una sola** `RTCPeerConnection` y la reutilizaba. Funcionaba la primera sesión, pero cualquier reconexión de las gafas caía sobre una PC cerrada (**Incidencia 3**), dejando a Unity sin `answer` o aplicando uno rezagado sobre una PC ya `stable` (**Incidencia 5**). Las "soluciones" de reconexión que figuraban en este registro **no estaban realmente en el código**; ahora sí se han implementado y verificado.

**Cómo se validó:** reproducción del flujo completo sobre `localhost` (servidor de señalización real + par robot + par que imita a `ScriptWebRTC`), midiendo tamaño de SDP (~3 KB, se descartó fragmentación), verificando el *handshake* y ejecutando 3 sesiones consecutivas de reconexión (S1→S2→S3) que ahora completan y disparan `OnTrack`.

## 5. Notas y Aportaciones para la Memoria del TFG

- **La documentación debe reflejar el código ejecutado:** varias correcciones estaban descritas en este registro pero no aplicadas en el fichero que se ejecutaba. Conviene verificar cada corrección contra el código real (y, si es posible, con una prueba reproducible) antes de darla por resuelta.
- **Robustez del Pipeline WebRTC:** El estándar WebRTC está diseñado para redes dinámicas, pero las librerías asíncronas como `aiortc` requieren una gestión rigurosa del ciclo de vida de los estados de señalización (`stable`, `have-local-offer`, `closed`). Una `RTCPeerConnection` de `aiortc` **no se reutiliza** una vez cerrada: hay que recrearla por sesión.
- **Resiliencia ante reconexiones:** Con las modificaciones realizadas, la aplicación en Python recrea su `PeerConnection` y su track de vídeo por cada oferta, tolerando reinicios del cliente Unity o reconexiones en caliente sin que caiga el servicio ni se pierda el puerto serie abierto con el robot; y Unity descarta limpiamente los `answer` duplicados o rezagados.
