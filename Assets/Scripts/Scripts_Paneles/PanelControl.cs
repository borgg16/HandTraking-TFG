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
    public Color colorReposo     = Color.white;
    public Color colorPellizco   = Color.green;
    public Color colorRobot      = Color.cyan;

    [Header("Umbrales de pinza")]
    [Tooltip("Distancia en metros para pinza CERRADA")]
    public float distanciaMinPinza = 0.01f;

    [Tooltip("Distancia en metros para pinza ABIERTA")]
    public float distanciaMaxPinza = 0.08f;

    [Tooltip("Valor de gripper (0-1) por debajo del cual se considera pellizco")]
    [Range(0f, 1f)]
    public float umbralPellizco = 0.2f;

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
        thumbTip      = datos.thumbTip;
        indexTip      = datos.indexTip;
        scriptWebRTC  = rtc;

        //Obtenemos el Transform de la mano segun la subclase
        var izquierda = manoCalibrada.GetComponent<MaximoIzquierda>();
        if(izquierda != null)
        {
            mano = izquierda.ManoIzquierda;
        }
        else
        {
            var derecha = manoCalibrada.GetComponent<MaximoDerecha>();
            if(derecha != null)
            {
                mano = derecha.ManoDerecha;
            }
            else
            {
                Debug.LogError("PanelControl: no se encontro MaximoIzquierda ni MaximoDerecha");
                return;
            }
        }

        //Subcripcion al evento de coordenadas del robot
        scriptWebRTC.OnCoordenadasRobot += ActualizarCoordsRobot;

        //Listeners de botones
        if(botonVolverCalibrar!= null) botonVolverCalibrar.onClick.AddListener(AlPulsarVolverCalibrar);
        if(botonAlPulsarFinalizar != null) botonAlPulsarFinalizar.onClick.AddListener(AlPulsarFinalizar);

        //Textos Iniciales
        if(textoCoordsMano != null) textoCoordsMano.text     = "X: --\nY: --\nZ: --\nPinza: --";
        if(textoCoordsRobot != null) textoCoordsRobot.text    = "X: --\nY: --\nZ: --";
        if(textoPellizcoMano != null)
        {
            textoPellizcoMano.text   = "*Sin pellizco";
            textoPellizcoMano.color  = colorReposo;
        }
        if(textoPellizcoRobot != null)
        { 
            textoPellizcoRobot.text  = "*Robot en reposo";
            textoPellizcoRobot.color = colorReposo;
        }

        controlActivo = true;

        Debug.Log("PanelControl iniciado - Enviando datos al Robot");

    }

    //------------------------------------------------------------------
    //UPDATE
    //------------------------------------------------------------------
    void Update()
    {
        if(!controlActivo) return;
        if(manoCalibrada == null || !manoCalibrada.guardado || mano == null) return;
        if(thumbTip == null || indexTip == null) return;

        //------- Posicion Normalizada ---------------------------------
        Vector3 posActual = mano.position;
        Vector3 posMaxima = manoCalibrada.maximoEstiramiento;

        Vector3 normalizada = new Vector3(
            posMaxima.x != 0 ? Mathf.Clamp01(posActual.x / posMaxima.x) : 0f,
            posMaxima.y != 0 ? Mathf.Clamp01(posActual.y / posMaxima.y) : 0f,
            posMaxima.z != 0 ? Mathf.Clamp01(posActual.z / posMaxima.z) : 0f
        );

        //----- Apertura de la pinza ----------------------------------
        float distanciaDedos = Vector3.Distance(thumbTip.position, indexTip.position);
        float gripper = Mathf.InverseLerp(distanciaMinPinza, distanciaMaxPinza, distanciaDedos);
            //InverseLerp: 0 = dedos tocandose(pinza cerrada), 1 = dedos separados (abierta)

        //----- Indicador de pellizco de la mano ----------------------
        bool pellizcoActivo = gripper < umbralPellizco;
        
        if(textoPellizcoMano != null)
        {
            textoPellizcoMano.text  = pellizcoActivo ? "*PELLIZCO ACTIVO" : "*Sin pellizco";
            textoPellizcoMano.color = pellizcoActivo ? colorPellizco : colorReposo;
        }

        //----- Texto de coordenadas de la mano ----------------------
        if(textoCoordsMano != null)
        {
            textoCoordsMano.text =  $"X: {normalizada.x:F2}\n" +
                                    $"Y: {normalizada.y:F2}\n" +
                                    $"Z: {normalizada.z:F2}\n" +
                                    $"Pinza: {gripper:F2}";
        }

        //----- Enviar al robot --------------------------------------
        scriptWebRTC.EnviarPosicion(normalizada, gripper);
    }

    //----------------------------------------------------------------
    //COORDENADAS DEL ROBOT - evento desde ScriptWebRTC
    //----------------------------------------------------------------
    void ActualizarCoordsRobot(Vector3 coords)
    {
        if(textoCoordsRobot == null) return;

        textoCoordsRobot.text = $"X: {coords.x:F2}\n" +
                                $"Y: {coords.y:F2}\n" +
                                $"Z: {coords.z:F2}";

        //Detectamos movimiento del robot comparando con la posicion anterior
        bool robotMoviendo = Vector3.Distance(coords, ultimaPosRobot) > 0.01f;
        
        if(textoPellizcoRobot != null)
        {
            textoPellizcoRobot.text = robotMoviendo ? "ROBOT EN MOVIMIENTO" : "Robot en reposo";
            textoPellizcoRobot.color = robotMoviendo ? colorRobot : colorReposo;
        }

        ultimaPosRobot = coords;
    }

    //-------------------------------------------------------------
    //BOTON - VOLVER A CALIBRAR
    //-------------------------------------------------------------
    
    void AlPulsarVolverCalibrar()
    {
        controlActivo = false;
        LimpiarTextos();
        OnVolverCalibrar?.Invoke();
        Debug.Log("PanelControl: notificando UIManager → volver a calibrar");
    }

    void AlPulsarFinalizar()
    {
        controlActivo = false;
        LimpiarTextos();
        OnFinalizar?.Invoke();
        Debug.Log("PanelControl: notificando UIManager → finalizar conexión");
    }

    void LimpiarTextos()
    {
         //Reseteamos textos
        if(textoCoordsMano != null) textoCoordsMano.text = "Mano: (calibración en curso...)";
        if(textoCoordsRobot != null) textoCoordsRobot.text = "Brazo: (en espera...)";
        if(textoPellizcoMano != null)
        {
            textoPellizcoMano.text = "*En Pausa";
            textoPellizcoMano.color = colorReposo;
        }
        if(textoPellizcoRobot != null)
        {
            textoPellizcoRobot.text = "*En Pausa";
            textoPellizcoRobot.color = colorReposo;
        }
    }


    //--------------------------------------------------------------------
    //LIMPIEZA
    //--------------------------------------------------------------------
    
    void OnDestroy()
    {
        if(scriptWebRTC != null)
        {
            scriptWebRTC.OnCoordenadasRobot -= ActualizarCoordsRobot;
        }

        if(botonVolverCalibrar != null)
        {
            botonVolverCalibrar.onClick.RemoveListener(AlPulsarVolverCalibrar);
        }

        if(botonAlPulsarFinalizar != null)
        {
            botonAlPulsarFinalizar.onClick.RemoveListener(AlPulsarFinalizar);
        }
    }
}
