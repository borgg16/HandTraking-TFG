using UnityEngine;
using System.Collections.Generic;
using TMPro;
public class NetworkMetrics : MonoBehaviour
{
    //Vamos a medir RTT, jitter, perdidas de pings y tasa de comandos sobre el DataChannel WenRTC
    //Se va a incializar desde el UIManager despues de que WebRTC esté listo para su uso

    [Header("Configuración")]
    [Tooltip("Segundos entre pings periódicos al robot")]
    public float intervaloPing = 3f;

    [Tooltip("Número de muestras RTT para calcular jitter (ventana deslizante)")]
    public int ventanaRTT = 20;

    [Header("Overlay UI — muestra los valores en pantalla")]
    public TextMeshProUGUI textoRTT;
    public TextMeshProUGUI textoJitter;
    public TextMeshProUGUI textoCmdHz;
    public TextMeshProUGUI textoPerdida;

    // Variables de solo lectura (publicas)----------------------
    public float RTT_ms             { get; private set; }
    public float Jitter_ms          { get; private set; }
    public float ComandosPorSegundo { get; private set; }
    public float TasaPerdidaPct     { get; private set; }
    public bool  Inicializado       { get; private set; }

    // Variables privadas --------------------------------------
    private ScriptWebRTC           scriptWebRTC;
    private Dictionary<int, float> pingsPendientes = new Dictionary<int, float>();
    private Queue<float> historialRTT = new Queue<float>();

    private int   secuenciaPing     = 0;
    private int   pingsTotales      = 0;
    private int   pingsPerdidos     = 0;
    private int   comandosEnVentana = 0;
    private float timerCmdRate      = 0f;

    private const float VENTANA_CMD  = 1f;  // recalcula Hz cada segundo
    private const float TIMEOUT_PING = 4f;  // ping sin respuesta tras 4 s → perdido

    //--------------------------------------------------------
    public void Inicializar(ScriptWebRTC rtc)
    {
        scriptWebRTC = rtc;
        scriptWebRTC.OnPongRecibido += ProcesarPong;
        scriptWebRTC.OnComandoEnviado += ContarComando;
        scriptWebRTC.OnDataChannelAbierto += ArrancarPings;

        InvokeRepeating(nameof(LimpiarPingsCaducados), TIMEOUT_PING, TIMEOUT_PING);

        Inicializado = true;
        Debug.Log("NetworkMetrics: iniciado...");
    }

    // Metodo ArrancarPings --------------------------------------
    private bool pingsArrancados = false;

    void ArrancarPings()
    {
        if (pingsArrancados) return; // Evitamos arrancar multiples veces si el canal se abre varias veces por alguna razon
        pingsArrancados = true;
        InvokeRepeating(nameof(EnviarPing), 0f, intervaloPing);
        Debug.Log("NetworkMetrics: DataChannel abierto, arrancando pings periódicos");
    }

    // Funcion update ---------------------------------------
    void Update()
    {
        timerCmdRate += Time.deltaTime;
        if (timerCmdRate >= VENTANA_CMD)
        {
            ComandosPorSegundo = comandosEnVentana / timerCmdRate;
            comandosEnVentana = 0;
            timerCmdRate = 0f;
        }

        // Actualizar UI
        if (textoRTT != null)
        {
            textoRTT.text = $"RTT: {RTT_ms:F0} ms";
        }
        if (textoJitter  != null) textoJitter.text  = $"Jitter: {Jitter_ms:F0} ms";
        if (textoCmdHz   != null) textoCmdHz.text   = $"Hz: {ComandosPorSegundo:F0}";
        if (textoPerdida != null) textoPerdida.text = $"Pérd: {TasaPerdidaPct:F1} %";
    }

    // Envio del ping ---------------------------------------
    void EnviarPing()
    {
        if(!Inicializado || scriptWebRTC == null) return;

        if(!scriptWebRTC.ConexionEstablecida)
        {
            //Debug.LogWarning("NetworkMetrics: No se puede enviar ping, conexión no establecida");
            return;
        }

        int seq = secuenciaPing++;
        pingsPendientes[seq] = Time.realtimeSinceStartup;
        pingsTotales++;
        scriptWebRTC.EnviarPing(seq);
    }

    // Recepción del pong --------------------------------------
    void ProcesarPong(int seq)
    {
        if(!pingsPendientes.TryGetValue(seq, out float tEnvio))
        {
            Debug.LogWarning($"Pong recibido con secuencia desconocida: {seq}");
            return;
        }
        pingsPendientes.Remove(seq);
        
        float rtt = (Time.realtimeSinceStartup - tEnvio) * 1000f; // ms
        RTT_ms = rtt;

        historialRTT.Enqueue(rtt);
        if (historialRTT.Count > ventanaRTT) historialRTT.Dequeue();

        Jitter_ms = CalcularDesviacion(historialRTT);
        ActualizarTasaPerdida();
    }

    // Timeouts de pings --------------------------------------
    void LimpiarPingsCaducados()
    {
        float ahora = Time.realtimeSinceStartup;
        var caducados = new List<int>();

        foreach (var kvp in pingsPendientes) //kvp se refiere al key peer value del diccionario, es decir, secuencia y tiempo de envio
        {
            if (ahora - kvp.Value > TIMEOUT_PING)
            {
                caducados.Add(kvp.Key);
            }
        }
        foreach (int seq in caducados)
        {
            pingsPendientes.Remove(seq);
            pingsPerdidos++;
        }
        
        if(caducados.Count > 0){ 
            Debug.Log($"NetworkMetrics: {caducados.Count} pings perdidos por timeout");
            ActualizarTasaPerdida();
        }
    }

    // Funciones auxiliares --------------------------------------
    void ContarComando()
    {
        comandosEnVentana++;
    }

    void ActualizarTasaPerdida()
    {
        if (pingsTotales > 0)
        {
            TasaPerdidaPct = pingsTotales > 0 ? (pingsPerdidos / (float)pingsTotales) * 100f : 0f;
        }
    }

    static float CalcularDesviacion(Queue<float> valores)
    {
        if (valores.Count < 2) return 0f;

        float media = 0f;
        
        foreach (float v in valores) media += v;
        media /= valores.Count;

        float suma = 0f;

        foreach (float v in valores) suma += (v - media) * (v - media);
        
        return Mathf.Sqrt(suma / (valores.Count));
    }

    // Limpieza ---------------------------------------
    void OnDestroy()
    {
        CancelInvoke();
        if (scriptWebRTC != null)
        {
            scriptWebRTC.OnPongRecibido -= ProcesarPong;
            scriptWebRTC.OnComandoEnviado -= ContarComando;
            scriptWebRTC.OnDataChannelAbierto -= ArrancarPings;
        }
    }

}
