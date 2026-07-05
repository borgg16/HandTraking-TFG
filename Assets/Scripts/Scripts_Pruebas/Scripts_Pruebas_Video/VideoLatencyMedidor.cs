using System;
using UnityEngine;
using System.IO;
using TMPro;

public class VideoLatencyMedidor : MonoBehaviour
{
    [Header("Referencias")]
    [Tooltip("Script WebRTC del que escuchamos el evento OnFrameTs")]
    public ScriptWebRTC scriptWebRTC;

    [Tooltip("Overlay de texto que muestra el timestamp de Unity (U:XXXXX ms)")]
    public TextMeshProUGUI textoTimestampUnity;

    [Tooltip("Nombre del archivo CSV. Se guarda en Application.persistentDataPath (Almacenamiento interno del Quest)")]
    public string nombreArchivoCSV = "latencia_video_pruebaX.csv";

    [Tooltip("Cada cuantas muestras se hace Flush() del csv del disco, por seguridad ante cierres inesperados de la app")]
    public int flushCada = 20;

    // CAMPOS PRIVADOS
    private StreamWriter _csv;
    private float _tInicioSesion;
    private int _totalMuestras = 0;
    private bool _sesionIniciada = false;

    //-------------------------------------------
    // INICIALIZACION
    //-------------------------------------------
    void Start()
    {
        if(scriptWebRTC == null)
        {
            Debug.LogError("VideoLatencyMedidor: No se ha asignado el ScriptWebRTC en el inspector");
            return;
        }

        // Nos subscribimos al evento que ScriptWebRTC dispara cada vez que llega un mensaje por DataChannel
        scriptWebRTC.OnFrameTs += OnFrameTs;

        AbrirCSV();

        _tInicioSesion = Time.realtimeSinceStartup;
        _sesionIniciada = true;

        Debug.Log("VideoLatencyMedidor: Sesion iniciada - esperando timestamps de video...");
    }

    //-------------------------------------------
    // ABRIMOS EL CSV
    //-------------------------------------------
    void AbrirCSV()
    {
        string ruta  = Path.Combine(Application.persistentDataPath, nombreArchivoCSV);

        try
        {
            _csv = new StreamWriter(ruta, false); // false = sobrescribir el archivo si ya existe
            _csv.WriteLine("TiempoDesdeInicioSesion,TimestampVideo,LatenciaVideo");
            _csv.Flush();
        }
        catch (Exception e)
        {
            Debug.LogError("VideoLatencyMedidor: Error al abrir el archivo CSV: " + e.Message);
        }
    }

    //-------------------------------------------
    // CALLBACK CUANDO LLEGA UN TIMESTAMP DE VIDEO
    //-------------------------------------------
    //adjuntamos al frame el tiempo en ms en el momento de capturarlo
    void OnFrameTs(double tCapturaMs)
    {
        if(!_sesionIniciada || _csv == null) return;

        //TimeStamp actual de Unity en ms
        double tRecibidoMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        double latenciaMs = tRecibidoMs - tCapturaMs;
        
        // Por seguridad vamos a hacer un "filtrado de sanidad" es decir descartar valores absurdos
        if(latenciaMs < 0 || latenciaMs > 5000)
        {
            Debug.LogWarning($"VideoLatencyMedidor: Latencia de video fuera de rango (descartada): {latenciaMs:F1} ms");
            return;
        }

        float tSesion = Time.realtimeSinceStartup - _tInicioSesion;

        //Actualizamos el Overlay de latencia en pantalla (U:XXXXX ms)----------------------
        if(textoTimestampUnity != null)
        {
            long msRecortado = (long)tRecibidoMs % 100000; // recortamos a 5 cifras para que no se desborde el overlay
            textoTimestampUnity.text = $"U:{msRecortado:D5}";
        }

        //Escribimos la fila en el CSV----------------------------------------------------------
        var ci = System.Globalization.CultureInfo.InvariantCulture; // para que el separador decimal sea siempre punto
        
        _csv.WriteLine(
            $"{tSesion.ToString("F2",ci)},"+
            $"{latenciaMs.ToString("F1",ci)},"+
            $"{tCapturaMs.ToString("F0",ci)},"+
            $"{tRecibidoMs.ToString("F0",ci)}"
        );

        _totalMuestras++;

        if(_totalMuestras % flushCada == 0)
        {
            _csv.Flush();
            Debug.Log($"VideoLatencyMedidor: Flush() del CSV tras {_totalMuestras} muestras");
        }
    }

    //-------------------------------------------
    // MARCADO DE LAS CONDICIONES EXPERIMENTALES
    //-------------------------------------------
    public void MarcarCondicion(string etiqueta)
    {
        if(_csv == null) return;

        float tSesion = Time.realtimeSinceStartup - _tInicioSesion;
        var ci = System.Globalization.CultureInfo.InvariantCulture; // para que el separador decimal sea siempre punto

        //Escribimos una fila especial que analisis_video.py pueda filtrar por el prefijo "MARCA" en al columna latencia_e2e_ms
        _csv.WriteLine(
            $"{tSesion.ToString("F2",ci)},"+
            $"MARCA_{etiqueta},," // dejamos vacias las columnas de latencia y timestamp
        );
        
        _csv.Flush();

        Debug.Log($"VideoLatencyMedidor: Condicion marcada -> {etiqueta} (t={tSesion:F1}s)");
    }


    //-------------------------------------------
    //LIMPIEZA Y CIERRE DEL CSV
    //-------------------------------------------
    public void Detener()
    {
        if(scriptWebRTC != null)
        {
            scriptWebRTC.OnFrameTs -= OnFrameTs;
        }

        _csv?.Flush();
        _csv?.Close();
        _csv = null;

        Debug.Log($"VideoLatencyMedidor: Sesion detenida. Total muestras registradas: {_totalMuestras}");
    }

    void OnDestroy()
    {
        Detener();
    }

}
