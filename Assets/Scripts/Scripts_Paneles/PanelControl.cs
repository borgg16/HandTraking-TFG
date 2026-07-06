using System;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class PanelControl : MonoBehaviour
{
    [Header("Columna Mano")]
    public TextMeshProUGUI textoCoordsMano;
    public TextMeshProUGUI textoPellizcoMano;

    [Header("Columna Vídeo")]
    public RawImage imagenVideo;

    [Header("Columna Robot")]
    public TextMeshProUGUI textoCoordsRobot;
    public TextMeshProUGUI textoPellizcoRobot;

    [Header("Barra Inferior")]
    public Button botonVolverCalibrar;
    public Button botonAlPulsarFinalizar;

    [Header("Colores")]
    public Color colorReposo = Color.white;
    public Color colorPellizco = Color.green;
    public Color colorRobot = Color.cyan;

    [Header("Umbrales de pinza")]
    [Tooltip("Distancia en metros para pinza CERRADA")]
    public float distanciaMinPinza = 0.01f;

    [Tooltip("Distancia en metros para pinza ABIERTA")]
    public float distanciaMaxPinza = 0.08f;

    [Tooltip("Valor de gripper (0-1) por debajo del cual se considera pellizco")]
    [Range(0f, 1f)]
    public float umbralPellizco = 0.2f;

    [Header("Sensibilidad")]
    [Tooltip("Multiplica el rango de X e Y — sube si el movimiento lateral parece corto")]
    [Range(1f, 5f)]
    public float sensibilidadLateral = 1f;

    [Header("Esfera de Referencia")]
    public EsferaReferencia esferaReferencia;

    [Header("Frecuencia de envío")]
    [Tooltip("Frecuencia máxima de envío de comandos al robot en Hz")]
    public float frecuenciaEnvioHz = 50f;
    private float ultimoEnvio = 0f;

    //EVENTOS PARA LOS CAMBIOS DE PANELES
    public event Action OnVolverCalibrar;
    public event Action OnFinalizar;

    //----- CAMPOS PRIVADOS ------
    private MaximoEstiramiento manoCalibrada;
    private ScriptWebRTC scriptWebRTC;
    private Transform mano;
    private Transform thumbTip;
    private Transform indexTip;
    private bool controlActivo = false;
    private Vector3 ultimaPosRobot = Vector3.zero;

    //--------------------------------------------------
    //INICIALIZACION - LLAMADO por panelCalibracion.CerrarPanel()
    //--------------------------------------------------

    public void Iniciar(DatosCalibracion datos, ScriptWebRTC rtc)
    {
        manoCalibrada = datos.manoCalibrada;
        thumbTip = datos.thumbTip;
        indexTip = datos.indexTip;
        scriptWebRTC = rtc;

        //Obtenemos el Transform de la mano segun el tipo real de la subclase
        if (manoCalibrada is MaximoIzquierda izquierda)
        {
            mano = izquierda.ManoIzquierda;
        }
        else if (manoCalibrada is MaximoDerecha derecha)
        {
            mano = derecha.ManoDerecha;
        }
        else
        {
            Debug.LogError("PanelControl: no se encontro MaximoIzquierda ni MaximoDerecha");
            return;
        }

        //Subcripcion al evento de coordenadas del robot
        scriptWebRTC.OnCoordenadasRobot += ActualizarCoordsRobot;

        //Listeners de botones
        if (botonVolverCalibrar != null) botonVolverCalibrar.onClick.AddListener(AlPulsarVolverCalibrar);
        if (botonAlPulsarFinalizar != null) botonAlPulsarFinalizar.onClick.AddListener(AlPulsarFinalizar);

        //Textos Iniciales
        if (textoCoordsMano != null) textoCoordsMano.text = "X: --\nY: --\nZ: --\nPinch: --";
        if (textoCoordsRobot != null) textoCoordsRobot.text = "X: --\nY: --\nZ: --";
        if (textoPellizcoMano != null)
        {
            textoPellizcoMano.text = "*Without pinching";
            textoPellizcoMano.color = colorReposo;
        }
        if (textoPellizcoRobot != null)
        {
            textoPellizcoRobot.text = "*Robot at rest";
            textoPellizcoRobot.color = colorReposo;
        }

        controlActivo = true;

        if (esferaReferencia != null) esferaReferencia.Iniciar(manoCalibrada, mano);

        Debug.Log("PanelControl iniciado - Enviando datos al Robot");

    }

    //------------------------------------------------------------------
    //UPDATE
    //------------------------------------------------------------------
    void Update()
    {
        if (!controlActivo) return;
        if (!manoCalibrada.neutroGuardado || !manoCalibrada.guardado || mano == null) return;
        if (thumbTip == null || indexTip == null) return;

        //------- Posicion Normalizada ---------------------------------
        Vector3 posActual = mano.position;

        Vector3 neutro = manoCalibrada.posturaNeutra;
        float normX, normY, normZ;

        // X e Y: usamos el rango de exploración si está disponible
        if (manoCalibrada.exploracionGuardada)
        {
            Vector3 rMin = manoCalibrada.rangoMin;
            Vector3 rMax = manoCalibrada.rangoMax;

            float desvX = posActual.x - neutro.x;
            float extXPos = rMax.x - neutro.x;
            float extXNeg = neutro.x - rMin.x;
            if (desvX >= 0f)
            {
                normX = extXPos > 0.001f ? Mathf.Clamp01(0.5f + 0.5f * (desvX / extXPos) * sensibilidadLateral) : 0.5f;
            }
            else
            {
                normX = extXNeg > 0.001f ? Mathf.Clamp01(0.5f + 0.5f * (desvX / extXNeg) * sensibilidadLateral) : 0.5f;
            }

            float desvY = posActual.y - neutro.y;
            float extYPos = rMax.y - neutro.y;
            float extYNeg = neutro.y - rMin.y;

            if (desvY >= 0f)
            {
                normY = extYPos > 0.001f ? Mathf.Clamp01(0.5f + 0.5f * (desvY / extYPos) * sensibilidadLateral) : 0.5f;
            }
            else
            {
                normY = extYNeg > 0.001f ? Mathf.Clamp01(0.5f + 0.5f * (desvY / extYNeg) * sensibilidadLateral) : 0.5f;
            }
        }
        else
        {
            Vector3 r = manoCalibrada.maximoEstiramiento - neutro;
            normX = Mathf.Abs(r.x) > 0.001f ? Mathf.Clamp01((posActual.x - neutro.x) / r.x) : 0f;
            normY = Mathf.Abs(r.y) > 0.001f ? Mathf.Clamp01((posActual.y - neutro.y) / r.y) : 0f;
        }

        // Z: profundidad desde postura neutra hasta alcance máximo
        Vector3 rangoZ = manoCalibrada.maximoEstiramiento - neutro;
        normZ = Mathf.Abs(rangoZ.z) > 0.001f
            ? Mathf.Clamp01((posActual.z - neutro.z) / rangoZ.z)
            : 0f;

        Vector3 normalizada = new Vector3(normX, normY, normZ);

        //----- Apertura de la pinza ----------------------------------
        float distanciaDedos = Vector3.Distance(thumbTip.position, indexTip.position);
        float gripper = Mathf.InverseLerp(distanciaMinPinza, distanciaMaxPinza, distanciaDedos);
        //InverseLerp: 0 = dedos tocandose(pinza cerrada), 1 = dedos separados (abierta)

        //----- Indicador de pellizco de la mano ----------------------
        bool pellizcoActivo = gripper < umbralPellizco;

        if (textoPellizcoMano != null)
        {
            textoPellizcoMano.text = pellizcoActivo ? "*ACTIVE PINCH" : "*Without pinching";
            textoPellizcoMano.color = pellizcoActivo ? colorPellizco : colorReposo;
        }

        //----- Texto de coordenadas de la mano ----------------------
        if (textoCoordsMano != null)
        {
            textoCoordsMano.text = $"X: {normalizada.x:F2}\n" +
                                    $"Y: {normalizada.y:F2}\n" +
                                    $"Z: {normalizada.z:F2}\n" +
                                    $"Pinch: {gripper:F2}";
        }

        //----- Enviar al robot --------------------------------------
        // Limitamos la frecuencia de envío usando Time.time para evitar sobrecargar la red
        if (Time.time - ultimoEnvio >= 1f / frecuenciaEnvioHz)
        {
            ultimoEnvio = Time.time;
            scriptWebRTC.EnviarPosicion(normalizada, gripper);
        }
    }

    //----------------------------------------------------------------
    //COORDENADAS DEL ROBOT - evento desde ScriptWebRTC
    //----------------------------------------------------------------
    void ActualizarCoordsRobot(Vector3 coords)
    {
        if (textoCoordsRobot == null) return;

        textoCoordsRobot.text = $"X: {coords.x:F2}\n" +
                                $"Y: {coords.y:F2}\n" +
                                $"Z: {coords.z:F2}";

        //Detectamos movimiento del robot comparando con la posicion anterior
        bool robotMoviendo = Vector3.Distance(coords, ultimaPosRobot) > 0.01f;

        if (textoPellizcoRobot != null)
        {
            textoPellizcoRobot.text = robotMoviendo ? "ROBOT IN MOTION" : "Robot at rest";
            textoPellizcoRobot.color = robotMoviendo ? colorRobot : colorReposo;
        }

        ultimaPosRobot = coords;
    }

    //-------------------------------------------------------------
    //BOTON - VOLVER A CALIBRAR
    //-------------------------------------------------------------

    void AlPulsarVolverCalibrar()
    {
        if (esferaReferencia != null) esferaReferencia.Ocultar();
        controlActivo = false;
        LimpiarTextos();
        OnVolverCalibrar?.Invoke();
        Debug.Log("PanelControl: notificando UIManager → volver a calibrar");
    }

    void AlPulsarFinalizar()
    {
        if (esferaReferencia != null) esferaReferencia.Ocultar();
        controlActivo = false;
        LimpiarTextos();
        OnFinalizar?.Invoke();
        Debug.Log("PanelControl: notificando UIManager → finalizar conexión");
    }

    void LimpiarTextos()
    {
        //Reseteamos textos
        if (textoCoordsMano != null) textoCoordsMano.text = "Hand: (calibration in progress...)";
        if (textoCoordsRobot != null) textoCoordsRobot.text = "Robot Arm: (waiting...)";
        if (textoPellizcoMano != null)
        {
            textoPellizcoMano.text = "*On Hold";
            textoPellizcoMano.color = colorReposo;
        }
        if (textoPellizcoRobot != null)
        {
            textoPellizcoRobot.text = "*On Hold";
            textoPellizcoRobot.color = colorReposo;
        }
    }


    //--------------------------------------------------------------------
    //LIMPIEZA
    //--------------------------------------------------------------------

    void OnDestroy()
    {
        if (scriptWebRTC != null)
        {
            scriptWebRTC.OnCoordenadasRobot -= ActualizarCoordsRobot;
        }

        if (botonVolverCalibrar != null)
        {
            botonVolverCalibrar.onClick.RemoveListener(AlPulsarVolverCalibrar);
        }

        if (botonAlPulsarFinalizar != null)
        {
            botonAlPulsarFinalizar.onClick.RemoveListener(AlPulsarFinalizar);
        }
    }
}
