using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Unity.WebRTC;
using UnityEngine;
using UnityEngine.UI;


public class ScriptWebRTC : MonoBehaviour
{
    [Header("Configuración de Red")]
    [Tooltip("Dirección IP local del PC del Robot. Consultar con 'ipconfig' (Windows) o con 'ip a' (Linux)")] //Muestra texto de ayuda emergente en el inspector para explicar la función de esta variable
    public string ipRobot = "192.168.1.124"; // Valor de ejemplo: actualizar por red (ver tooltip: 'ipconfig' en Windows / 'ip a' en Linux)
    public int puertoWebRTC = 8080;
    
    [Tooltip("Token secreto de sesión para autenticación en señalización.")]
    public string sessionToken = "TFG_Secret_Token_2026";

    [Header("Panel de Control")]
    [Tooltip("Imagen del video recibido")] //Muestra texto de ayuda emergente en el inspector para explicar la función de esta variable
    public RawImage imagenVideo; //Es raw y no Image porque vamos a asignar una textura de video que no es un sprite.
                                 //----------------------------------------------------------------------
                                 // VARIABLES PRIVADAS para la conexión WebRTC
    private RTCPeerConnection peerConnection;
    //Representa la conexion WebRTC completa entre Unity y el robot.
    //Gestiona internamente: Cifrado DTLS, control de congestion, ICE, etc.
    //Es el objeto central de la comunicacion punto a punto (P2P).

    private RTCDataChannel dataChannel;
    //Canal de datos bidireccional dentro de la conexion WebRTC
    //Por aqui enviamos las coordenadas al robot en formato JSON
    //y recibimos las coordenadas del brazo robot de vuelta.
    //Es similar a un socket TCP pero integrado en WebRTC sin servidor.

    private ClientWebSocket websocket;
    //Conexion al servidor de signaling de Python
    //SOLO se usará durante el establecimiento inicial de la conexion WebRTC
    //para intercambiar los mensajes SDP e ICE.
    //Una vez conectados P2P, este canal queda inactivo

    private CancellationTokenSource cancelToken;

    private ConcurrentQueue<string> mensajesPendientes = new ConcurrentQueue<string>();
    //Cola thread-safe: el hilo de red mete mensajes aqui(Enqueue)
    //Update() los saca y procesa en el hilo principal (TryDequeue).
    //Necesaria porque Unity solo permite tocar sus objetos desde el hilo principal.

    private bool conexionEstablecida = false;
    //Flag para proteger los envios por DataChannel antes de que el canal este abierto (evitamos excepciones que controlar)

    public bool ConexionEstablecida => conexionEstablecida;
    //Propiedad publica de solo lectura para que otros scripts puedan consultar el estado de la conexion

    private Texture _texturaVideoRecibida = null;

    // Sincronización de relojes por RTT
    private double clockOffsetMs = 0;
    private bool clockOffsetCalculado = false;

    public double ClockOffsetMs => clockOffsetMs;
    public bool ClockOffsetCalculado => clockOffsetCalculado;

    private void ActualizarClockOffset(double nuevoOffset)
    {
        if (!clockOffsetCalculado)
        {
            clockOffsetMs = nuevoOffset;
            clockOffsetCalculado = true;
            Debug.Log($"ScriptWebRTC: Offset de reloj inicial calculado: {clockOffsetMs:F1} ms");
        }
        else
        {
            // Filtro paso bajo para suavizar el offset (alpha = 0.1)
            clockOffsetMs = 0.1 * nuevoOffset + 0.9 * clockOffsetMs;
        }
    }

    //EVENTO PUBLICO que nos permitirá al panel de control estar "Subcrito a las coordenadas del robot"
    public event Action<Vector3> OnCoordenadasRobot;
    //Cuando recibamos coordenadas del robot hace algo

    public event Action<Double> OnFrameTs; //Timestamp del frame de video recibido, para medir latencia

    public event Action OnComandoEnviado;
    public event Action<int> OnPongRecibido;

    public event Action OnDataChannelAbierto;

    //----------------------------------------------
    // INICIALIZACIÓN
    //----------------------------------------------

    // async porque queremos usar await dentro de la funcion.
    async void Start()
    {
        cancelToken = new CancellationTokenSource();

        StartCoroutine(WebRTC.Update());

        //Esperamos a que se conecte al servidor de señalizacion de manera asincrona para que la app no se bloquee. 
        await ConectarSignaling();
    }

    //----------------------------------------------
    
    public void CerrarConexion()
    {
        cancelToken?.Cancel();
        if (websocket?.State == WebSocketState.Open)
        {
            _ = websocket.CloseAsync(
                WebSocketCloseStatus.NormalClosure,
                "Conexión Cerrada",
                CancellationToken.None
            );
        }
        dataChannel?.Close();
        dataChannel = null;

        peerConnection?.Close();
        peerConnection = null;

        conexionEstablecida = false;
        Debug.Log("ScriptWebRTC: conexión cerrada explícitamente");
    }

    public async void ReiniciarConexion()
    {
        CerrarConexion();
        cancelToken = new CancellationTokenSource();
        Debug.Log("ScriptWebRTC: Reiniciando conexión...");
        await ConectarSignaling();
    }

    //----------------------------------------------
    // SIGNALING (Primera fase de la conexión WebRTC)
    //----------------------------------------------

    async Task ConectarSignaling() //Es async Task porque websocket.Connect() nos lo devuelve, como no se tocan objetos es seguro de usar
    {
        //Creamos la conexion WebSocket al servidor de signaling
        websocket = new ClientWebSocket();

        //LINEAS PARA INTENTAR CORREGIR COMPATIBILIDAD DE .NET CON LIBRERIA WEBRTC DE PY
        websocket.Options.KeepAliveInterval = TimeSpan.Zero;


        try
        {
            //ConnectAsync establecee la conexion TCP+handshake WebSocket.
            //await pausa este metodo hasta que conecte sin bloquear Unity.
            var uri = new Uri($"ws://{ipRobot}:{puertoWebRTC}/");
            Debug.Log($"Intentando conectar a: {uri}");
            await websocket.ConnectAsync(uri, cancelToken.Token);

            Debug.Log("WebSocket conectado al servidor de señalizacion. Enviando mensaje de autenticación...");

            // Enviar token de autenticación
            var auth = new AuthMessage { type = "auth", token = sessionToken };
            string authJson = JsonUtility.ToJson(auth);
            var authBytes = Encoding.UTF8.GetBytes(authJson);
            await websocket.SendAsync(
                new ArraySegment<byte>(authBytes),
                WebSocketMessageType.Text,
                true,
                cancelToken.Token
            );

            //Arrancamos el bucle de recepcion en segundo plano
            // _ = descarta el Task porque no necesitamos esperarla
            //El bucle corre indefinidamente hasta que se cancela en OnDestroy
            _ = BucleRecepcion();

            //Lanzamos la creación de la oferta WebRTC.
            StartCoroutine(CrearOferta());

        }
        catch (Exception e)
        {
            Debug.LogError($"Error WebSocket: {e.GetType().Name}");
            Debug.LogError($"Mensaje: {e.Message}");
            Debug.LogError($"Inner: {e.InnerException?.Message}");
            Debug.LogError($"Stack: {e.StackTrace}");
        }
    }

    //------------------------------------------------------------------
    //BUCLE DE RECEPCION - Se ejecuta en otro hilo
    //------------------------------------------------------------------
    async Task BucleRecepcion()
    {
        //Creamos un buffer de 8KB para recibir mensajes
        //Los mensajes SDP de WebRTC pueden ser varios KB
        var buffer = new byte[8192];

        while (websocket.State == WebSocketState.Open && !cancelToken.Token.IsCancellationRequested)
        {
            try
            {
                //ReceiveAsync espera hasta que llegue un mensaje completo.
                //Durante la espera no bloquea, otros Tasks pueden ejecutarse
                var resultado = await websocket.ReceiveAsync(
                    new ArraySegment<byte>(buffer),
                    cancelToken.Token
                );

                if (resultado.MessageType == WebSocketMessageType.Close)
                {
                    Debug.Log("Servidor de señalizacion cerro la conexion");
                    break;
                }

                if (resultado.MessageType == WebSocketMessageType.Text)
                {
                    //Convertimos bytes a String y los metemos en la cola
                    // NO procesamos aqui, estamos en el hilo secundario
                    // Update() lo procesará en el hilo principal
                    string mensaje = Encoding.UTF8.GetString(buffer, 0, resultado.Count);
                    mensajesPendientes.Enqueue(mensaje);
                }
            }
            catch (OperationCanceledException)
            {
                //Cancelacion normal al destruir el objeto (NO ES UN ERROR)
                break;
            }
            catch (Exception e)
            {
                if (!cancelToken.Token.IsCancellationRequested)
                {
                    Debug.LogError($"Error en bucle WebSocket: {e.Message}");
                }
            }
        }

    }


    //-----------------------------------------------------------------------------------
    // UPDATE : Procesa mensajes en el hilo principal de Unity
    //-----------------------------------------------------------------------------------
    void Update()
    {
        //Vaciamos la cola procesando cada mensaje en el hilo principal.
        //TryDequeue devuelve false cuando la cola está vacia (while termina)
        while (mensajesPendientes.TryDequeue(out string mensaje))
        {
            ProcesarMensajeSignaling(mensaje);
        }

        if (_texturaVideoRecibida != null && imagenVideo != null)
        {
            imagenVideo.texture = _texturaVideoRecibida;
            _texturaVideoRecibida = null; //Limpiamos la variable para no reasignar la textura cada frame
        }
    }

    //-------------------------------------------------
    //ENVIO DE MENSAJES POR WEBSOCKET
    //-------------------------------------------------

    void EnviarMensajesSignaling(string json)
    {
        if (websocket == null || websocket.State != WebSocketState.Open)
        {
            Debug.LogWarning("Intento de enviar mensaje con WebSocket no conectado");
            return;
        }

        var bytes = Encoding.UTF8.GetBytes(json);

        //SendAsync fire-and-forget: no esperamos confirmacion porque los mensajes
        //de señalizacion son pequeños y el canal WebSocket es fiable.
        _ = websocket.SendAsync(
            new ArraySegment<byte>(bytes),
            WebSocketMessageType.Text,
            true,                   //endOfMessage: el mensaje es completo en un solo envio
            cancelToken.Token
        );
    }




    //----------------------------------------------
    //PEER CONECTION (El nucleo de la conexión WebRTC)
    //----------------------------------------------
    IEnumerator CrearOferta()
    {
        var config = new RTCConfiguration
        {
            iceServers = new[]
            {
                new RTCIceServer {
                    urls = new[] { "stun:stun.l.google.com:19302" }
                    }
            }
        };
        //ICE (Interactive Connectivity Establishment) es el mecanismo que descubre como llegar de un dispositivo al otro a través de la red)
        //El servidor STUN (Session Traversal Utilities for NAT) es un servicio que ayuda a los dispositivos a descubrir su dirección IP pública y el tipo de NAT (Network Address Translation) que están utilizando, lo cual es crucial para establecer conexiones WebRTC exitosas.

        peerConnection = new RTCPeerConnection(ref config);
        //ref config poruqe RTCConfiguration es un struct, no una clase así que vamos a pasar la referencia del struct de la configuracion

        //----- CallBack de los candidatos ICE (Interactive Connectivity Establishment)---------------------------------------------------------
        peerConnection.OnIceCandidate = candidato =>
        {
            //Cuando la red descubre una posible ruta de red (Candidato), lo enviamos al robot a través del servidor de signaling
            //El robot hará lo mismo y WebRTC probará todas las rutas posibles para elegir la mejor.
            EnviarMensajesSignaling(JsonUtility.ToJson(new SignalingMessage
            {
                type = "candidate",
                candidate = candidato.Candidate,
                sdpMid = candidato.SdpMid, //identifica a que stream pertenece el candidato
                sdpMLineIndex = candidato.SdpMLineIndex ?? 0 //Si hay valor toma valor, en caso de null pues pone 0 (es el indice numerico del stream dentro del documento SDP)
            }));

        };

        peerConnection.OnIceConnectionChange = estado =>
        {
            Debug.Log("ICE Estado: " + estado);
        };//Para ver en consola los distintos estados por los que pasa


        //----- CallBack de recepcion del video del robot -------------------------------------------------------------------------------------
        peerConnection.OnTrack = e =>
        {
            //OnTrack se dispara cuando el robot nos envia un archivo de video
            if (e.Track is VideoStreamTrack videoTrack)
            {
                videoTrack.Enabled = true;

                videoTrack.OnVideoReceived += tex =>
                {
                    _texturaVideoRecibida = tex;
                };
            }
        };

        //----- DataChannel para enviar comandos al robot -------------------------------------------------------------------------------------
        var opciones = new RTCDataChannelInit
        {
            ordered = true //ponerlo a true garantiza que los mensajes lleguen en orden.
            //Para coordenadas es importante ya que no queremos que el robot ejecute 'mover posicion A' despues de 'mover posicion B', si B llega primero se reordena el paquete
        };

        dataChannel = peerConnection.CreateDataChannel("comandos", opciones);
        //Aqui podemos crear varios canales si fuera necesario separar mensajes, "comandos" es un string que indica el nombre del canal.

        dataChannel.OnOpen += () =>
        {
            conexionEstablecida = true;
            OnDataChannelAbierto?.Invoke(); //Notificamos a Metrics que ya esta abierto
            Debug.Log("DataChannel abierto -- preparado para enviar comandos");
            StartCoroutine(BucleClockSync());
        };

        dataChannel.OnClose += () =>
        {
            conexionEstablecida = false;
            Debug.Log("DataChannel cerrado");
        };

        //La linea esta nos va a servir para recibir las coordenadas del brazo por este canal
        //TODO: (lo deberia guardar en una variable)
        dataChannel.OnMessage += bytes =>
        {
            string json = Encoding.UTF8.GetString(bytes);

            var tipo = JsonUtility.FromJson<FrameTsMsg>(json);
            if(tipo != null && tipo.type == "frame_ts")
            {
                OnFrameTs?.Invoke(tipo.t);
                return;
            }

            var header = JsonUtility.FromJson<MsgTipo>(json);
            if (header != null && header.type == "pong")
            {
                var pong = JsonUtility.FromJson<PongMsg>(json);
                if (pong.client_ts > 0 && pong.server_ts > 0)
                {
                    double tRecibidoMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    double rtt = tRecibidoMs - pong.client_ts;
                    double estimatedServerTime = pong.client_ts + (rtt / 2.0);
                    double offset = pong.server_ts - estimatedServerTime;
                    ActualizarClockOffset(offset);
                }

                if (pong.seq >= 0)
                {
                    OnPongRecibido?.Invoke(pong.seq);
                }
                return;
            }

            var coordenadasRobot = JsonUtility.FromJson<CoordenadaMsg>(json);
            if (coordenadasRobot != null)
                OnCoordenadasRobot?.Invoke(
                    new Vector3(coordenadasRobot.x,
                                coordenadasRobot.y,
                                coordenadasRobot.z));
            else
                Debug.LogWarning($"Mensaje no reconocido: {json}");
        };

        //----- Negociación de la conexión (SDP) -------------------------------------------------------------------------------------
        /*
            SDP (Session Description Protocol) es un documento de texto
            que describe que capacidades tiene cada extremo: que codecs de video soporta,
            que canales de datos quiere abrir, etc.

            El proceso de negociación es el siguiente:
            1. El cliente (Unity) crea una oferta (offer) con su descripción SDP
            2. Robot responde con una respuesta (answer) con su propia descripción SDP
        */
        peerConnection.AddTransceiver(TrackKind.Video, new RTCRtpTransceiverInit
        {
            direction = RTCRtpTransceiverDirection.RecvOnly //Solo queremos recibir video, no enviar
        });


        var ofertaOp = peerConnection.CreateOffer();

        yield return ofertaOp; //Esperamos a que se cree la oferta sin bloquear el hilo principal de Unity

        //TODO: Comprobar si hubo error en la oferta
        if (ofertaOp.IsError)
        {
            Debug.LogError("Error creando la oferta: " + ofertaOp.Error.message);
            yield break; //Salimos de la corrutina si hubo error
        }

        var descLocal = new RTCSessionDescription
        {
            type = RTCSdpType.Offer,
            sdp = ofertaOp.Desc.sdp
        };

        var setLocalOp = peerConnection.SetLocalDescription(ref descLocal);
        yield return setLocalOp; //Esperamos a que se establezca la descripcion local

        //Comrprobamos que este libre de errores
        if (setLocalOp.IsError)
        {
            Debug.LogError("Error en SetLocalDescription: " + setLocalOp.Error.message);
            yield break; //Salimos de la corrutina si hubo error
        }

        //Enviamos la oferta al robot a través del servidor de signaling.
        //Robot recibira la oferta en OnMessage del WebSocket, generara una respuesta y la devolvera a ESTE codigo.
        EnviarMensajesSignaling(JsonUtility.ToJson(new SignalingMessage
        {
            type = "offer",
            sdp = ofertaOp.Desc.sdp
        }));

        Debug.Log("Oferta SDP enviada al robot, esperando respuesta...");
    }

    //------------------------------------------------------------------------
    // PROCESAMIENTO DE MENSAJES DEL ROBOT A TRAVÉS DEL SERVIDOR DE SIGNALING
    //------------------------------------------------------------------------
    void ProcesarMensajeSignaling(string json)
    {

        SignalingMessage msg;
        try
        {
            msg = JsonUtility.FromJson<SignalingMessage>(json);
        }
        catch (Exception ex)
        {
            Debug.LogError($"Error parseando mensaje de signaling: {ex.Message}");
            return;
        }

        if (msg == null || string.IsNullOrEmpty(msg.type))
        {
            Debug.LogWarning($"Mensaje de signaling con formato desconocido: {json}");
            return;
        }

        switch (msg.type)
        {
            case "answer":
                //El robot acepto nuestra oferta y nos manda su SDP.
                StartCoroutine(AplicarAnswer(msg.sdp));
                break;

            case "candidate":
                //El robot nos comunica una de sus rutas de red posibles.
                //WebRTC probara esta ruta junto con las nuestras para elegir la mejor combinacion de caminos
                if (peerConnection == null)
                {
                    Debug.LogWarning("Recibido candidato ICE pero la conexión WebRTC no esta inicializada");
                    return;
                }

                var candidato = new RTCIceCandidate(new RTCIceCandidateInit
                {
                    candidate = msg.candidate,
                    sdpMid = msg.sdpMid,
                    sdpMLineIndex = msg.sdpMLineIndex
                });
                peerConnection.AddIceCandidate(candidato);
                break;

            default:
                Debug.LogWarning($"Tipo de mensaje de signaling desconocido: {msg.type}");
                break;
        }
    }

    IEnumerator AplicarAnswer(string sdp)
    {
        // GUARDA DE ESTADO: solo aplicamos el answer si estamos en HaveLocalOffer.
        // Si llega un answer duplicado o rezagado (p. ej. de una sesión anterior tras
        // reconectar), la PeerConnection ya estaría en Stable y SetRemoteDescription
        // fallaría con "Called in wrong state: stable", rompiendo la negociación.
        // En ese caso lo ignoramos en vez de dejar que reviente.
        if (peerConnection == null)
        {
            Debug.LogWarning("Answer recibido pero no hay PeerConnection activa. Ignorado.");
            yield break;
        }
        if (peerConnection.SignalingState != RTCSignalingState.HaveLocalOffer)
        {
            Debug.LogWarning(
                $"Answer ignorado: estado de señalización = {peerConnection.SignalingState} " +
                "(se esperaba HaveLocalOffer). Probable answer duplicado o de una sesión previa.");
            yield break;
        }

        var desc = new RTCSessionDescription
        {
            type = RTCSdpType.Answer,
            sdp = sdp
        };

        var op = peerConnection.SetRemoteDescription(ref desc);
        yield return op;

        if (op.IsError)
        {
            Debug.LogError("Error en SetRemoteDescription: " + op.Error.message);
        }
        else
        {
            Debug.Log("---- NEGOCIACION WEB_RCT COMPLETA - CONEXION P2P ESTABLECIDA -----");
        }
    }

    //---------------------------------------------------------
    // ENLACE CON PANEL DE CONTROL PARA IMPRIMIR COORDENADAS DEL ROBOT
    //---------------------------------------------------------
    /*
        Vamos a enviar la poscion normalizada de la mano y aperturade pinza al robot
        - <param name = "posNormalizada"> x = lateral, y = altura, z = profundidad (todos entre 0 y 1) </param>
        - <param name = "gripper"> 0 = pinza cerrada, 1 = pinza abierta </param>
    */

    public void EnviarPosicion(Vector3 posNormalizada, float gripper)
    {
        if (!conexionEstablecida)
        {
            Debug.LogWarning("Intentando enviar comando al robot pero la conexion no esta establecida");
            return;
        }

        var ci = System.Globalization.CultureInfo.InvariantCulture; //Para asegurar que el punto decimal es '.' y no ',' segun la configuracion regional
        string x = posNormalizada.x.ToString("F3", ci);
        string y = posNormalizada.y.ToString("F3", ci);
        string z = posNormalizada.z.ToString("F3", ci);
        string g = Mathf.Clamp01(gripper).ToString("F3", ci);

        //Vamos a construir el JSON manualmente porque hemos detectado que al hacerlo con funciones y tal se añade retardo (algun frame puede escaparse) y producir basurilla
        string json = $"{{\"x\":{x}," +
                        $"\"y\":{y}," +
                        $"\"z\":{z}," +
                        $"\"g\":{g}}}";

        dataChannel.Send(json);
        OnComandoEnviado?.Invoke();
    }

    public void EnviarPing(int seq)
    {
        if (!conexionEstablecida) return;
        long ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        dataChannel.Send($"{{\"type\":\"ping\",\"seq\":{seq},\"client_ts\":{ts}}}");
    }

    public void EnviarDatosCSV(string sesionId, string csv)
    {
        if (!conexionEstablecida) return;
        string esc = csv
            .Replace("\\", "\\\\").Replace("\"", "\\\"")
            .Replace("\n", "\\n").Replace("\r", "");
        dataChannel.Send(
            $"{{\"type\":\"csv_export\","
            + $"\"sesion\":\"{sesionId}\","
            + $"\"data\":\"{esc}\"}}");
        Debug.Log($"ScriptWebRTC: CSV enviado — {sesionId}");
    }

    //------------------------------------------------------------------------
    // LIMPIEZA DE SOCKETS Y CONEXIONES AL CERRAR LA APLICACIÓN
    //------------------------------------------------------------------------
    void OnDestroy()
    {
        //Cancelamos el token, esto proboca que el BucleRecepcion() termina en su proxima iteracion
        cancelToken?.Cancel();

        //Cerramos el WebSocket enviando el frame de cierre estándar
        if (websocket?.State == WebSocketState.Open)
        {
            _ = websocket.CloseAsync(
                WebSocketCloseStatus.NormalClosure,
                "Aplicacion Cerrando",
                CancellationToken.None
            );
        }

        dataChannel?.Close();
        peerConnection?.Close();
    }

    //------------------------------------------------------------------------
    // CLASES AUXILIARES PARA PARSEAR LOS MENSAJES DE SEÑALIZACIÓN
    //------------------------------------------------------------------------
    [System.Serializable] //Pasa de JSON a otros datos
    public class SignalingMessage
    {
        public string type; // "offer", "answer", "candidate"
        public string sdp; // Solo para offer/answer
        public string candidate; // ruta de red (candidate)
        public string sdpMid; // identificador del stream
        public int sdpMLineIndex; // indice en el documento SDP
    }

    [System.Serializable]
    public class CoordenadaMsg
    {
        public float x; // lateral normalizada entre 0 y 1
        public float y; // altura normalizada entre 0 y 1
        public float z; // profundidad normalizada entre 0 y 1

        //TODO: Podriamos incluir el estado de la pinza
        //No incluimos "g" - el robot no nos va a enviar el estado de la pinza, solo la posicion del brazo, para simplificar
    }

    [System.Serializable]
    public class FrameTsMsg
    {
        public string type;
        public double t;
    }

    [System.Serializable]
    public class AuthMessage
    {
        public string type;
        public string token;
    }

    [System.Serializable] private class MsgTipo { public string type; }
    
    [System.Serializable]
    private class PongMsg
    {
        public string type;
        public int seq;
        public double client_ts;
        public double server_ts;
    }

    private IEnumerator BucleClockSync()
    {
        int seqSync = -1000;
        while (conexionEstablecida && dataChannel != null)
        {
            EnviarPing(seqSync--);
            yield return new WaitForSeconds(2.0f);
        }
    }


}
