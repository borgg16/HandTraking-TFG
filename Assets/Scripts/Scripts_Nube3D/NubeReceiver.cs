using System;
using System.Collections.Concurrent;
using System.Threading.Tasks;
using UnityEngine;
using Draco;

/*
    NubeReceiver
    ------------
    Recibe la nube de puntos comprimida con Draco que emite la CamaraDraco3D (RealSense
    + DracoPy en el PC-ROBOT) a traves del DataChannel "nube3d" de ScriptWebRTC.

    Responsabilidades:
      1. Reensamblar los chunks de 16 KiB usando la cabecera binaria de 26 bytes
         descrita en PLANIFICACION_CAMARA3D_DRACO.md (apartado 5).
      2. Decodificar la trama Draco en segundo plano.
      3. Entregar la malla resultante al NubeRenderer en el hilo principal.
      4. Exponer las metricas del canal (fps, puntos, latencia G2G, ancho de banda,
         tiempo de decodificacion y descartes) para que el PanelControlVolumetrico
         las pinte en la ventana del visor.
*/
public class NubeReceiver : MonoBehaviour
{
    public enum EstadoNube { SinConexion, Esperando, Recibiendo }

    [Header("Referencias")]
    [Tooltip("Script WebRTC del que escuchamos el evento OnChunkNube3D")]
    public ScriptWebRTC scriptWebRTC;

    [Tooltip("Visor 3D al que se le entrega la malla decodificada")]
    public NubeRenderer visor;

    [Header("Protocolo de reensamblado")]
    [Tooltip("Descartamos un frame incompleto si llega otro mas nuevo pasado este tiempo")]
    public int msDescarteReensamblado = 250;

    [Tooltip("Segundos sin recibir un frame completo para considerar que la nube se ha caido")]
    public float segundosTimeoutNube = 2f;

    [Header("Control de carga")]
    [Tooltip("Numero maximo de decodificaciones Draco simultaneas — protege la CPU del Quest")]
    public int decodificacionesSimultaneas = 2;

    //---- METRICAS PUBLICAS (solo lectura, las consume el panel) --------------
    public EstadoNube Estado { get; private set; } = EstadoNube.SinConexion;
    public int FrameId { get; private set; }
    public int PuntosUltimoFrame { get; private set; }
    public float LatenciaMs { get; private set; }
    public float DecodeMs { get; private set; }
    public float EncodeMs { get; private set; }
    public float AnchoBandaMbps { get; private set; }
    public float FpsNube { get; private set; }
    public int FramesRecibidos { get; private set; }
    public int FramesDescartados { get; private set; }
    public int ChunksDescartados { get; private set; }

    public float TasaDescartePct =>
        (FramesRecibidos + FramesDescartados) > 0
            ? 100f * FramesDescartados / (FramesRecibidos + FramesDescartados)
            : 0f;

    //---- CONSTANTES DEL PROTOCOLO -------------------------------------------
    private const ushort MAGIC = 0x4E33;   // "N3"
    private const int CABECERA_BYTES = 26;

    //---- REENSAMBLADO -------------------------------------------------------
    private long frameActivo = -1;
    private byte[][] chunksRecibidos;
    private int chunksContados = 0;
    private int chunksEsperados = 0;
    private int puntosFrameActivo = 0;
    private float encodeMsFrameActivo = 0f;
    private long capturaFrameActivo = 0;
    private float tInicioReensamblado = 0f;

    //---- COLAS Y CONTADORES -------------------------------------------------
    private ConcurrentQueue<MallaDecodificada> mallasPendientes = new ConcurrentQueue<MallaDecodificada>();
    private int decodificacionesEnCurso = 0;

    private int bytesEnVentana = 0;
    private float timerVentana = 0f;
    private int framesEnVentana = 0;
    private float tUltimoFrame = -999f;

    private struct MallaDecodificada
    {
        public Mesh malla;
        public int frameId;
        public int puntos;
        public float latenciaMs;
        public float decodeMs;
        public float encodeMs;
    }

    //-------------------------------------------------------------------------
    // INICIALIZACION
    //-------------------------------------------------------------------------
    void Start()
    {
        if (scriptWebRTC == null)
        {
            Debug.LogError("NubeReceiver: no se ha asignado el ScriptWebRTC en el inspector");
            enabled = false;
            return;
        }

        if (visor == null)
        {
            Debug.LogWarning("NubeReceiver: no hay NubeRenderer asignado — la nube se recibira pero no se pintara");
        }

        scriptWebRTC.OnChunkNube3D += ProcesarChunk;
        Debug.Log("NubeReceiver: escuchando el DataChannel de nube de puntos...");
    }

    //-------------------------------------------------------------------------
    // RECEPCION DE UN CHUNK — cabecera de 26 bytes + payload Draco
    //-------------------------------------------------------------------------
    private void ProcesarChunk(byte[] datos)
    {
        if (datos == null || datos.Length <= CABECERA_BYTES) return;

        bytesEnVentana += datos.Length;

        //Cabecera little-endian: struct.pack("<HBBIHHQIH")
        ushort magic = BitConverter.ToUInt16(datos, 0);
        if (magic != MAGIC)
        {
            //Trama que no pertenece al protocolo de nube — la ignoramos sin ruido
            return;
        }

        long msgFrameId = BitConverter.ToUInt32(datos, 4);
        int chunkIdx = BitConverter.ToUInt16(datos, 8);
        int nChunks = BitConverter.ToUInt16(datos, 10);
        long tCaptura = (long)BitConverter.ToUInt64(datos, 12);
        int nPuntos = (int)BitConverter.ToUInt32(datos, 20);
        float encodeMs = BitConverter.ToUInt16(datos, 24) / 10f;

        if (nChunks <= 0 || chunkIdx >= nChunks) return;

        //---- Chunk de un frame ya superado: lo tiramos --------------------
        if (msgFrameId < frameActivo)
        {
            ChunksDescartados++;
            return;
        }

        //---- Frame nuevo: reiniciamos la estructura de reensamblado -------
        if (msgFrameId != frameActivo)
        {
            bool incompleto = chunksEsperados > 0 && chunksContados < chunksEsperados;
            bool caducado = Time.realtimeSinceStartup - tInicioReensamblado > msDescarteReensamblado / 1000f;

            if (incompleto)
            {
                //El frame anterior nunca se completo (o tardo demasiado): lo contabilizamos como perdido
                FramesDescartados++;
                ChunksDescartados += chunksEsperados - chunksContados;
                if (caducado)
                {
                    Debug.LogWarning($"NubeReceiver: frame {frameActivo} descartado por timeout de reensamblado");
                }
            }

            frameActivo = msgFrameId;
            chunksRecibidos = new byte[nChunks][];
            chunksContados = 0;
            chunksEsperados = nChunks;
            puntosFrameActivo = nPuntos;
            encodeMsFrameActivo = encodeMs;
            capturaFrameActivo = tCaptura;
            tInicioReensamblado = Time.realtimeSinceStartup;
        }

        //---- Guardamos el chunk ------------------------------------------
        if (chunksRecibidos[chunkIdx] != null) return; //duplicado

        byte[] payload = new byte[datos.Length - CABECERA_BYTES];
        Buffer.BlockCopy(datos, CABECERA_BYTES, payload, 0, payload.Length);
        chunksRecibidos[chunkIdx] = payload;
        chunksContados++;

        //---- Frame completo: montamos la trama y la decodificamos ---------
        if (chunksContados != chunksEsperados) return;

        int total = 0;
        for (int i = 0; i < chunksEsperados; i++) total += chunksRecibidos[i].Length;

        byte[] trama = new byte[total];
        int offset = 0;
        for (int i = 0; i < chunksEsperados; i++)
        {
            Buffer.BlockCopy(chunksRecibidos[i], 0, trama, offset, chunksRecibidos[i].Length);
            offset += chunksRecibidos[i].Length;
        }

        //Backpressure: si la CPU no da abasto decodificando preferimos tirar el frame
        //antes que acumular retraso (el criterio es el mismo que usa el emisor en Python)
        if (decodificacionesEnCurso >= decodificacionesSimultaneas)
        {
            FramesDescartados++;
            return;
        }

        decodificacionesEnCurso++;
        _ = DecodificarNube(trama, (int)frameActivo, puntosFrameActivo, capturaFrameActivo, encodeMsFrameActivo);
    }

    //-------------------------------------------------------------------------
    // DECODIFICACION DRACO (asincrona — com.unity.cloud.draco usa Jobs/Burst)
    //-------------------------------------------------------------------------
    private async Task DecodificarNube(byte[] trama, int fId, int nPuntos, long tCaptura, float encodeMs)
    {
        var crono = System.Diagnostics.Stopwatch.StartNew();
        try
        {
            Mesh malla = await DracoDecoder.DecodeMesh(trama);
            crono.Stop();

            if (malla == null)
            {
                FramesDescartados++;
                return;
            }

            //Latencia G2G: corregimos el reloj del robot con el offset medido por RTT
            //(mismo criterio que VideoLatencyMedidor para que los CSV sean comparables)
            double tRecibido = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            double tCapturaCorregido = tCaptura;
            if (scriptWebRTC != null && scriptWebRTC.ClockOffsetCalculado)
            {
                tCapturaCorregido = tCaptura - scriptWebRTC.ClockOffsetMs;
            }

            mallasPendientes.Enqueue(new MallaDecodificada
            {
                malla = malla,
                frameId = fId,
                puntos = nPuntos > 0 ? nPuntos : malla.vertexCount,
                latenciaMs = (float)(tRecibido - tCapturaCorregido),
                decodeMs = crono.ElapsedMilliseconds,
                encodeMs = encodeMs
            });
        }
        catch (Exception e)
        {
            FramesDescartados++;
            Debug.LogError($"NubeReceiver: error decodificando el frame {fId} — {e.Message}");
        }
        finally
        {
            decodificacionesEnCurso--;
        }
    }

    //-------------------------------------------------------------------------
    // UPDATE — pintado y metricas en el hilo principal
    //-------------------------------------------------------------------------
    void Update()
    {
        //Nos quedamos siempre con la malla mas reciente: si se han acumulado varias
        //es que vamos por detras, y mostrar una nube vieja solo añade latencia.
        bool hayMalla = false;
        MallaDecodificada ultima = default;

        while (mallasPendientes.TryDequeue(out MallaDecodificada m))
        {
            if (hayMalla)
            {
                Destroy(ultima.malla);
                FramesDescartados++;
            }
            ultima = m;
            hayMalla = true;
        }

        if (hayMalla)
        {
            FrameId = ultima.frameId;
            PuntosUltimoFrame = ultima.puntos;
            LatenciaMs = ultima.latenciaMs;
            DecodeMs = ultima.decodeMs;
            EncodeMs = ultima.encodeMs;
            FramesRecibidos++;
            framesEnVentana++;
            tUltimoFrame = Time.realtimeSinceStartup;

            if (visor != null) visor.MostrarNube(ultima.malla);
            else Destroy(ultima.malla);
        }

        //---- Ventana de 1 s para fps y ancho de banda ---------------------
        timerVentana += Time.deltaTime;
        if (timerVentana >= 1f)
        {
            AnchoBandaMbps = (bytesEnVentana * 8f) / (1000f * 1000f * timerVentana);
            FpsNube = framesEnVentana / timerVentana;
            bytesEnVentana = 0;
            framesEnVentana = 0;
            timerVentana = 0f;
        }

        //---- Estado del visor --------------------------------------------
        bool canalAbierto = scriptWebRTC != null && scriptWebRTC.CanalNube3DAbierto;
        bool nubeViva = Time.realtimeSinceStartup - tUltimoFrame < segundosTimeoutNube;

        if (!canalAbierto) Estado = EstadoNube.SinConexion;
        else if (!nubeViva) Estado = EstadoNube.Esperando;
        else Estado = EstadoNube.Recibiendo;

        if (Estado != EstadoNube.Recibiendo)
        {
            FpsNube = 0f;
            AnchoBandaMbps = 0f;
        }
    }

    //-------------------------------------------------------------------------
    // LIMPIEZA
    //-------------------------------------------------------------------------
    void OnDestroy()
    {
        if (scriptWebRTC != null) scriptWebRTC.OnChunkNube3D -= ProcesarChunk;

        while (mallasPendientes.TryDequeue(out MallaDecodificada m))
        {
            if (m.malla != null) Destroy(m.malla);
        }
    }
}
