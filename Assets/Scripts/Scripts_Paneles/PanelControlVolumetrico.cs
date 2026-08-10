using System;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

/*
    PanelControlVolumetrico
    -----------------------
    Variante del PanelControl para la escena de teleoperación volumétrica.

    Hereda toda la lógica de teleoperación (normalización de la mano, pinza y envío
    al robot) y solo cambia la parte visual: al desaparecer la ventana de vídeo 2D
    se gana sitio para mostrar las coordenadas de la mano y del brazo con barras,
    y la ventana central pasa a ser el visor de la nube de puntos 3D.

    Las barras se rellenan moviendo el anchorMax de la imagen interior — así funcionan
    sin necesidad de sprite (todo el UI del proyecto usa Image de color plano).
*/
public class PanelControlVolumetrico : PanelControl
{
    //--------------------------------------------------------------------
    // BARRA DE DATO — etiqueta + valor numérico + barra de progreso
    //--------------------------------------------------------------------
    [Serializable]
    public class BarraDato
    {
        public Image relleno;
        public TextMeshProUGUI valor;

        [Tooltip("Color habitual de la barra")]
        public Color colorNormal = new Color(0.29f, 0.62f, 0.83f, 1f);

        [Tooltip("Color cuando el eje llega al límite del rango calibrado")]
        public Color colorLimite = new Color(1f, 0.65f, 0.2f, 1f);

        public void Fijar(float valor01, string texto)
        {
            float v = Mathf.Clamp01(valor01);

            if (relleno != null)
            {
                var rt = relleno.rectTransform;
                rt.anchorMin = new Vector2(0f, rt.anchorMin.y);
                rt.anchorMax = new Vector2(v, rt.anchorMax.y);
                relleno.color = (v <= 0.02f || v >= 0.98f) ? colorLimite : colorNormal;
            }

            if (valor != null) valor.text = texto;
        }

        public void Vaciar(string texto = "--")
        {
            Fijar(0f, texto);
            if (relleno != null) relleno.color = colorNormal;
        }
    }

    [Header("Barras — Mano del operario")]
    public BarraDato barraManoX;
    public BarraDato barraManoY;
    public BarraDato barraManoZ;
    public BarraDato barraPinza;

    [Header("Barras — Brazo robot")]
    public BarraDato barraRobotX;
    public BarraDato barraRobotY;
    public BarraDato barraRobotZ;

    [Tooltip("Cuánto se parece la posición del brazo a la orden enviada por la mano")]
    public BarraDato barraSincronia;

    [Header("Visor de nube de puntos")]
    [Tooltip("Receptor del DataChannel 'nube3d' del que sacamos las métricas")]
    public NubeReceiver receptorNube;

    [Tooltip("Mensaje grande dentro de la ventana del visor (se oculta al recibir nube)")]
    public TextMeshProUGUI textoEstadoNube;

    [Tooltip("Línea de telemetría bajo la ventana del visor")]
    public TextMeshProUGUI textoTelemetriaNube;

    [Header("Colores del visor")]
    public Color colorSinCanal = new Color(0.65f, 0.28f, 0.28f, 1f);
    public Color colorEsperando = new Color(1f, 0.65f, 0.2f, 1f);
    public Color colorRecibiendo = new Color(0.35f, 0.85f, 0.55f, 1f);

    [Header("Refresco de telemetría")]
    [Tooltip("Segundos entre refrescos del texto de métricas — evitamos rehacer el mesh del TMP cada frame")]
    public float intervaloTelemetria = 0.25f;

    //---- CAMPOS PRIVADOS ------------------------------------------------
    private Vector3 ultimaOrdenMano = Vector3.zero;
    private bool hayOrdenMano = false;
    private float timerTelemetria = 0f;

    private static readonly System.Globalization.CultureInfo CI =
        System.Globalization.CultureInfo.InvariantCulture;

    //--------------------------------------------------------------------
    // INICIO
    //--------------------------------------------------------------------
    public override void Iniciar(DatosCalibracion datos, ScriptWebRTC rtc)
    {
        base.Iniciar(datos, rtc);
        VaciarBarras();
        RefrescarTelemetriaNube();
    }

    //--------------------------------------------------------------------
    // MANO DEL OPERARIO — gancho llamado desde PanelControl.Update()
    //--------------------------------------------------------------------
    protected override void ActualizarVisualesMano(Vector3 normalizada, float gripper, bool pellizcoActivo)
    {
        ultimaOrdenMano = normalizada;
        hayOrdenMano = true;

        barraManoX.Fijar(normalizada.x, normalizada.x.ToString("F2", CI));
        barraManoY.Fijar(normalizada.y, normalizada.y.ToString("F2", CI));
        barraManoZ.Fijar(normalizada.z, normalizada.z.ToString("F2", CI));

        //La pinza se lee mejor como porcentaje de apertura que como 0-1
        barraPinza.Fijar(gripper, $"{gripper * 100f:F0} %");
    }

    //--------------------------------------------------------------------
    // BRAZO ROBOT — llega por el evento OnCoordenadasRobot
    //--------------------------------------------------------------------
    protected override void ActualizarCoordsRobot(Vector3 coords)
    {
        base.ActualizarCoordsRobot(coords);

        barraRobotX.Fijar(coords.x, coords.x.ToString("F2", CI));
        barraRobotY.Fijar(coords.y, coords.y.ToString("F2", CI));
        barraRobotZ.Fijar(coords.z, coords.z.ToString("F2", CI));

        //Sincronía: 1 = el brazo está exactamente donde le pide la mano.
        //Ambas magnitudes están normalizadas 0-1, así que la distancia es comparable.
        if (hayOrdenMano)
        {
            float desvio = Vector3.Distance(coords, ultimaOrdenMano);
            float sincronia = Mathf.Clamp01(1f - desvio);
            barraSincronia.Fijar(sincronia, $"{sincronia * 100f:F0} %");
        }
    }

    //--------------------------------------------------------------------
    // TELEMETRIA DE LA NUBE — refresco lento, no hace falta cada frame
    //--------------------------------------------------------------------
    void LateUpdate()
    {
        timerTelemetria += Time.deltaTime;
        if (timerTelemetria < intervaloTelemetria) return;
        timerTelemetria = 0f;

        RefrescarTelemetriaNube();
    }

    private void RefrescarTelemetriaNube()
    {
        if (receptorNube == null)
        {
            if (textoEstadoNube != null)
            {
                textoEstadoNube.gameObject.SetActive(true);
                textoEstadoNube.text = "VISOR 3D NO CONFIGURADO";
                textoEstadoNube.color = colorSinCanal;
            }
            if (textoTelemetriaNube != null) textoTelemetriaNube.text = string.Empty;
            return;
        }

        //---- Mensaje central de la ventana -------------------------------
        if (textoEstadoNube != null)
        {
            switch (receptorNube.Estado)
            {
                case NubeReceiver.EstadoNube.SinConexion:
                    textoEstadoNube.gameObject.SetActive(true);
                    textoEstadoNube.text = "3D CHANNEL OFFLINE";
                    textoEstadoNube.color = colorSinCanal;
                    break;

                case NubeReceiver.EstadoNube.Esperando:
                    textoEstadoNube.gameObject.SetActive(true);
                    textoEstadoNube.text = "WAITING FOR POINT CLOUD...";
                    textoEstadoNube.color = colorEsperando;
                    break;

                default:
                    //Recibiendo: dejamos la ventana limpia para ver la nube
                    textoEstadoNube.gameObject.SetActive(false);
                    break;
            }
        }

        //---- Línea de métricas -------------------------------------------
        if (textoTelemetriaNube == null) return;

        if (receptorNube.Estado == NubeReceiver.EstadoNube.Recibiendo)
        {
            float kpts = receptorNube.PuntosUltimoFrame / 1000f;

            textoTelemetriaNube.color = colorRecibiendo;
            textoTelemetriaNube.text =
                $"FPS {receptorNube.FpsNube:F1}   PTS {kpts:F1}k   LAT {receptorNube.LatenciaMs:F0} ms\n" +
                $"BW {receptorNube.AnchoBandaMbps:F1} Mbps   DEC {receptorNube.DecodeMs:F0} ms   ENC {receptorNube.EncodeMs:F0} ms\n" +
                $"FRAME {receptorNube.FrameId}   DROP {receptorNube.TasaDescartePct:F1} %";
        }
        else
        {
            textoTelemetriaNube.color = colorEsperando;
            textoTelemetriaNube.text =
                "FPS --   PTS --   LAT -- ms\n" +
                "BW -- Mbps   DEC -- ms   ENC -- ms\n" +
                $"FRAME {receptorNube.FrameId}   DROP {receptorNube.TasaDescartePct:F1} %";
        }
    }

    //--------------------------------------------------------------------
    // LIMPIEZA DE LA UI AL SALIR DEL PANEL
    //--------------------------------------------------------------------
    protected override void LimpiarTextos()
    {
        base.LimpiarTextos();
        VaciarBarras();
    }

    private void VaciarBarras()
    {
        hayOrdenMano = false;

        barraManoX.Vaciar();
        barraManoY.Vaciar();
        barraManoZ.Vaciar();
        barraPinza.Vaciar();

        barraRobotX.Vaciar();
        barraRobotY.Vaciar();
        barraRobotZ.Vaciar();
        barraSincronia.Vaciar();
    }
}
