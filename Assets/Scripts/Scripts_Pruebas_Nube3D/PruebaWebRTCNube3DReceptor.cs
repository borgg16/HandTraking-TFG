using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Unity.WebRTC;
using UnityEngine;
using Draco;

public class PruebaWebRTCNube3DReceptor : MonoBehaviour
{
    [Header("Configuracion de Red")]
    public string ipRobot = "192.168.1.124";
    public int puertoWebRTC = 8080;
    public string sessionToken = "TFG_Secret_Token_2026";
    public string channelLabel = "nube3d";

    [Header("Configuracion Visual")]
    public Material pointMaterial;

    [Header("Metricas de Nube")]
    public int frameId = 0;
    public int totalPoints = 0;
    public float decodeTimeMs = 0f;
    public float networkTimeMs = 0f;

    private RTCPeerConnection peerConnection;
    private RTCDataChannel dataChannel;
    private ClientWebSocket websocket;
    private CancellationTokenSource cancelToken;
    private ConcurrentQueue<string> signalingQueue = new ConcurrentQueue<string>();
    
    // Reensamblado de chunks
    private int activeFrameId = -1;
    private byte[][] receivedChunks;
    private int chunksReceivedCount = 0;
    private int expectedChunksCount = 0;
    private int totalFramePoints = 0;
    private float lastFrameEncodeMs = 0f;
    private long lastFrameTimestamp = 0;

    // Cola de mallas decodificadas para actualizar en el hilo principal
    private ConcurrentQueue<Mesh> decodedMeshQueue = new ConcurrentQueue<Mesh>();

    private MeshFilter meshFilter;
    private MeshRenderer meshRenderer;
    private DracoMeshLoader dracoLoader;

    void Awake()
    {
        meshFilter = GetComponent<MeshFilter>();
        if (meshFilter == null) meshFilter = gameObject.AddComponent<MeshFilter>();
        
        meshRenderer = GetComponent<MeshRenderer>();
        if (meshRenderer == null) meshRenderer = gameObject.AddComponent<MeshRenderer>();
        
        if (pointMaterial != null) meshRenderer.material = pointMaterial;
        
        dracoLoader = new DracoMeshLoader();
    }

    async void Start()
    {
        cancelToken = new CancellationTokenSource();
        WebRTC.Initialize();
        
        await ConectarSignaling();
    }

    async Task ConectarSignaling()
    {
        websocket = new ClientWebSocket();
        websocket.Options.KeepAliveInterval = TimeSpan.Zero;

        try
        {
            var uri = new Uri($"ws://{ipRobot}:{puertoWebRTC}/");
            Debug.Log($"[Receptor3D] Conectando a señalizacion: {uri}");
            await websocket.ConnectAsync(uri, cancelToken.Token);

            // Enviar token de autenticacion
            var auth = new AuthMessage { type = "auth", token = sessionToken };
            string authJson = JsonUtility.ToJson(auth);
            var authBytes = Encoding.UTF8.GetBytes(authJson);
            await websocket.SendAsync(new ArraySegment<byte>(authBytes), WebSocketMessageType.Text, true, cancelToken.Token);

            Debug.Log("[Receptor3D] Autenticado. Inicializando WebRTC...");
            InicializarWebRTC();
            
            _ = BucleRecepcionSignaling();
        }
        catch (Exception e)
        {
            Debug.LogError($"[Receptor3D] Error de conexion: {e.Message}");
        }
    }

    void InicializarWebRTC()
    {
        var config = new RTCConfiguration
        {
            iceServers = new[]
            {
                new RTCIceServer { urls = new[] { "stun:stun.l.google.com:19302" } }
            }
        };

        peerConnection = new RTCPeerConnection(ref config);

        peerConnection.OnIceCandidate = candidato =>
        {
            EnviarMensajeSignaling(JsonUtility.ToJson(new SignalingMessage
            {
                type = "candidate",
                candidate = candidato.Candidate,
                sdpMid = candidato.SdpMid,
                sdpMLineIndex = candidato.SdpMLineIndex ?? 0
            }));
        };

        // Crear DataChannel "nube3d"
        var opciones = new RTCDataChannelInit { ordered = true };
        dataChannel = peerConnection.CreateDataChannel(channelLabel, opciones);

        dataChannel.OnOpen += () => Debug.Log($"[Receptor3D] DataChannel '{channelLabel}' abierto.");
        dataChannel.OnClose += () => Debug.Log($"[Receptor3D] DataChannel '{channelLabel}' cerrado.");
        
        dataChannel.OnMessage += OnDataChannelMessage;

        // Iniciar oferta
        StartCoroutine(CrearOferta());
    }

    private void OnDataChannelMessage(byte[] data)
    {
        if (data == null || data.Length < 26) return;

        // Parsear cabecera binaria (26 bytes)
        ushort magic = BitConverter.ToUInt16(data, 0);
        if (magic != 0x4E33) return; // Magic number mismatch ("N3")

        byte version = data[2];
        byte flags = data[3];
        int msgFrameId = (int)BitConverter.ToUInt32(data, 4);
        int chunkIdx = BitConverter.ToUInt16(data, 8);
        int nChunks = BitConverter.ToUInt16(data, 10);
        long tCaptura = (long)BitConverter.ToUInt64(data, 12);
        int nPuntos = (int)BitConverter.ToUInt32(data, 20);
        float encodeMs = BitConverter.ToUInt16(data, 24) / 10.0f;

        byte[] payload = new byte[data.Length - 26];
        Buffer.BlockCopy(data, 26, payload, 0, payload.Length);

        // Si es un nuevo frame, reiniciar estructura de reensamblado
        if (msgFrameId != activeFrameId)
        {
            activeFrameId = msgFrameId;
            receivedChunks = new byte[nChunks][];
            chunksReceivedCount = 0;
            expectedChunksCount = nChunks;
            totalFramePoints = nPuntos;
            lastFrameEncodeMs = encodeMs;
            lastFrameTimestamp = tCaptura;
        }

        // Guardar el chunk recibido
        if (chunkIdx < expectedChunksCount && receivedChunks[chunkIdx] == null)
        {
            receivedChunks[chunkIdx] = payload;
            chunksReceivedCount++;
        }

        // Si tenemos todos los chunks del frame, reensamblar y decodificar
        if (chunksReceivedCount == expectedChunksCount)
        {
            int totalSize = 0;
            for (int i = 0; i < expectedChunksCount; i++)
            {
                totalSize += receivedChunks[i].Length;
            }

            byte[] fullFrameBytes = new byte[totalSize];
            int currentOffset = 0;
            for (int i = 0; i < expectedChunksCount; i++)
            {
                Buffer.BlockCopy(receivedChunks[i], 0, fullFrameBytes, currentOffset, receivedChunks[i].Length);
                currentOffset += receivedChunks[i].Length;
            }

            // Decodificar asincronamente en segundo plano
            _ = DecodificarNubeDraco(fullFrameBytes, msgFrameId, lastFrameTimestamp);
        }
    }

    private async Task DecodificarNubeDraco(byte[] dracoBytes, int fId, long tCaptura)
    {
        var watch = System.Diagnostics.Stopwatch.StartNew();
        try
        {
            Mesh mesh = await dracoLoader.ConvertDracoMeshToUnity(dracoBytes);
            if (mesh != null)
            {
                long localNow = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                networkTimeMs = localNow - tCaptura;
                decodeTimeMs = watch.ElapsedMilliseconds;
                frameId = fId;

                decodedMeshQueue.Enqueue(mesh);
            }
        }
        catch (Exception e)
        {
            Debug.LogError($"[Receptor3D] Error decodificando frame {fId}: {e.Message}");
        }
    }

    IEnumerator CrearOferta()
    {
        var ofertaOp = peerConnection.CreateOffer();
        yield return ofertaOp;

        if (ofertaOp.IsError)
        {
            Debug.LogError("[Receptor3D] Error creando oferta: " + ofertaOp.Error.message);
            yield break;
        }

        var descLocal = new RTCSessionDescription { type = RTCSdpType.Offer, sdp = ofertaOp.Desc.sdp };
        var setLocalOp = peerConnection.SetLocalDescription(ref descLocal);
        yield return setLocalOp;

        EnviarMensajeSignaling(JsonUtility.ToJson(new SignalingMessage
        {
            type = "offer",
            sdp = ofertaOp.Desc.sdp
        }));
        Debug.Log("[Receptor3D] Oferta SDP enviada.");
    }

    void Update()
    {
        // Procesar mensajes de señalizacion en el hilo principal
        while (signalingQueue.TryDequeue(out string msg))
        {
            ProcesarMensajeSignaling(msg);
        }

        // Aplicar mallas decodificadas al MeshFilter en el hilo principal
        if (decodedMeshQueue.TryDequeue(out Mesh newMesh))
        {
            if (meshFilter.sharedMesh != null)
            {
                Destroy(meshFilter.sharedMesh);
            }
            meshFilter.mesh = newMesh;
            totalPoints = newMesh.vertexCount;
        }
    }

    void ProcesarMensajeSignaling(string json)
    {
        SignalingMessage msg = JsonUtility.FromJson<SignalingMessage>(json);
        if (msg == null || string.IsNullOrEmpty(msg.type)) return;

        switch (msg.type)
        {
            case "answer":
                StartCoroutine(AplicarAnswer(msg.sdp));
                break;
            case "candidate":
                var candidato = new RTCIceCandidate(new RTCIceCandidateInit
                {
                    candidate = msg.candidate,
                    sdpMid = msg.sdpMid,
                    sdpMLineIndex = msg.sdpMLineIndex
                });
                peerConnection.AddIceCandidate(candidato);
                break;
        }
    }

    IEnumerator AplicarAnswer(string sdp)
    {
        var desc = new RTCSessionDescription { type = RTCSdpType.Answer, sdp = sdp };
        var op = peerConnection.SetRemoteDescription(ref desc);
        yield return op;
        
        if (op.IsError) Debug.LogError("[Receptor3D] Error al aplicar Answer: " + op.Error.message);
        else Debug.Log("[Receptor3D] Conexion P2P WebRTC establecida con exito.");
    }

    async Task BucleRecepcionSignaling()
    {
        var buffer = new byte[8192];
        while (websocket.State == WebSocketState.Open && !cancelToken.Token.IsCancellationRequested)
        {
            try
            {
                var resultado = await websocket.ReceiveAsync(new ArraySegment<byte>(buffer), cancelToken.Token);
                if (resultado.MessageType == WebSocketMessageType.Close) break;
                if (resultado.MessageType == WebSocketMessageType.Text)
                {
                    string mensaje = Encoding.UTF8.GetString(buffer, 0, resultado.Count);
                    signalingQueue.Enqueue(mensaje);
                }
            }
            catch (Exception)
            {
                break;
            }
        }
    }

    void EnviarMensajeSignaling(string json)
    {
        if (websocket == null || websocket.State != WebSocketState.Open) return;
        var bytes = Encoding.UTF8.GetBytes(json);
        _ = websocket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, cancelToken.Token);
    }

    void OnDestroy()
    {
        cancelToken?.Cancel();
        websocket?.Dispose();
        peerConnection?.Dispose();
        WebRTC.Dispose();
    }

    [Serializable]
    private class AuthMessage { public string type; public string token; }
    [Serializable]
    private class SignalingMessage { public string type; public string sdp; public string candidate; public string sdpMid; public int sdpMLineIndex; }
}
