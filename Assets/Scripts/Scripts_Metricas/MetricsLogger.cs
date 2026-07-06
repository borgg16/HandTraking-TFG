using UnityEngine;
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

// Este archivo se va a encargar de cada cierto tiempo almacenar en memoria los datos registrados, produciendo que en caso de fallo no perdamos los datos. Mas Robusto.
public class MetricsLogger : MonoBehaviour
{
    [Tooltip("Segundos entre muestras automáticas de red")]
    public float intervaloMuestra = 5f;

    [Tooltip("Número de muestras acumuladas en RAM antes de hacer flush a disco")]
    public int filasPorFlush = 60;   // 60 × 5 s = flush cada 5 min

    // Variables Privadas --------------------------------
    private NetworkMetrics networkMetrics;
    private ScriptWebRTC   scriptWebRTC;

    private List<string> filas = new List<string>();
    private string sesionId;
    private string rutaArchivo;
    private bool headerEscrito = false;

    private static readonly Encoding UTF8 = Encoding.UTF8; //FORZADA A DEFINIRSE EN EL CONSTRUCTOR Y QUE NO PUEDA MODIFICARSE A POSTERIORI
    private static readonly System.Globalization.CultureInfo INV = System.Globalization.CultureInfo.InvariantCulture;

    private const string CABECERA = "timestamp,rtt_ms,jitter_ms,cmd_hz,tasa_perdida_pct";

    // -----------------------------------------------
    public void Inicializar (NetworkMetrics nm, ScriptWebRTC rtc)
    {
        networkMetrics = nm;
        scriptWebRTC = rtc;
        sesionId = DateTime.Now.ToString("yyyyMMdd_HHmmss");
#if UNITY_EDITOR
        string carpeta = Path.Combine(Application.dataPath, "../resultados_unity");
        if (!Directory.Exists(carpeta)) Directory.CreateDirectory(carpeta);
        rutaArchivo = Path.Combine(carpeta, $"red_{sesionId}.csv");
#else
        rutaArchivo = Path.Combine(Application.persistentDataPath, $"red_{sesionId}.csv");
#endif

        InvokeRepeating(nameof(TomarMuestra), intervaloMuestra, intervaloMuestra);
        Debug.Log($"[MetricsLogger] Sesión iniciada: {sesionId} -> archivo local: {rutaArchivo}");
    }

    // Muestra Periódica --------------------------------
    void TomarMuestra()
    {
        if(networkMetrics == null || !networkMetrics.Inicializado) return;
        if (networkMetrics.RTT_ms == 0f) return; // Evitar muestras vacías o no inicializadas

        filas.Add(
            $"{DateTime.Now:HH:mm:ss.fff}," +
            $"{networkMetrics.RTT_ms.ToString("F1", INV)}," +
            $"{networkMetrics.Jitter_ms.ToString("F1", INV)}," +
            $"{networkMetrics.ComandosPorSegundo.ToString("F1", INV)}," +
            $"{networkMetrics.TasaPerdidaPct.ToString("F1", INV)}"
        );

        if (filas.Count >= filasPorFlush)
        {
            FlushADisco();
        }
    }

    // Flush Periodico a Disco --------------------------------
    void FlushADisco()
    {
        if(filas.Count == 0) return;

        int n = filas.Count;
        try
        {
            //Primera vez crea el archivo con la cabecera
            //Siguientes veces añaden sin cabecera
            using (var sw = new StreamWriter(rutaArchivo, append: headerEscrito, UTF8))
            {
                if (!headerEscrito)
                {
                    sw.WriteLine(CABECERA);
                    headerEscrito = true;
                }
                foreach (string fila in filas)
                {
                    sw.WriteLine(fila);
                }
            }

            filas.Clear();
            Debug.Log($"[MetricsLogger] Flush a disco: {n} filas escritas en {rutaArchivo}");
        }catch (Exception ex)
        {
            Debug.LogError($"[MetricsLogger] Error al escribir en disco: {ex.Message}");
            //Las filas siguen en la RAM; se intentará de nuevo en el próximo flush
        }
    }

    // EXPORTACION FINAL AL PC ROBOT por DataChannel --------------------------------
    public void ExportarCSV()
    {
        // 1. Vaciamos los datos que queden en la RAM
        FlushADisco();

        //2. Comprobar que hay archivo para enviar
        if (!File.Exists(rutaArchivo))
        {
            Debug.LogWarning($"[MetricsLogger] No hay datos para exportar.");
            return;
        }

        //3. Leer el archivo completo y enviarlo por DataChannel
        try
        {
            string csv = File.ReadAllText(rutaArchivo, UTF8);
            scriptWebRTC.EnviarDatosCSV(sesionId, csv);
            Debug.Log($"[MetricsLogger] Archivo CSV exportado por DataChannel: {rutaArchivo} | sesion: {sesionId}");
        }
        catch (Exception ex)
        {
            Debug.LogError($"[MetricsLogger] Error al leer el archivo CSV: {ex.Message}");
        }
    }

    // Limpieza al Finalizar Sesión --------------------------------
    void OnDestroy()
    {
        CancelInvoke();
        FlushADisco(); // Por seguridad para no perder datos si se destruye el objeto antes de exportar
    }
}
