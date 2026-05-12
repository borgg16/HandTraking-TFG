using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class PanelControl : MonoBehaviour
{
    [Header("Columna Mano — izquierda")]
    [Tooltip("Coordenadas normalizadas actuales de la mano (0-1)")]
    public TextMeshProUGUI textoCoordsMano;

    [Tooltip("Indicador de pellizco — cambia de color cuando se detecta")]
    public TextMeshProUGUI textoPellizcoMano;

    [Header("Columna Vídeo — centro")]
    [Tooltip("RawImage donde se mostrará el feed de la cámara del robot")]
    public RawImage imagenVideo;

    [Header("Columna Robot — derecha")]
    [Tooltip("Coordenadas actuales del brazo robot (0-1)")]
    public TextMeshProUGUI textoCoordsRobot;

    [Tooltip("Indicador de acción del robot — cambia de color cuando se mueve")]
    public TextMeshProUGUI textoPellizcoRobot;

    [Header("Botones")]
    [Tooltip("Pausa el control y vuelve a la calibración")]
    public Button botonVolverCalibrar;

    [Tooltip("Cierra la conexión WebRTC y muestra el panel de despedida")]
    public Button botonFinalizarConexion;

    [Header("Colores")]
    public Color colorReposo   = Color.white;
    public Color colorPellizco = Color.green;
    public Color colorAccionRobot = Color.cyan;

    [Header("Umbrales de pinza")]
    [Tooltip("Distancia en metros para pinza CERRADA")]
    public float distanciaMinPinza = 0.01f;

    [Tooltip("Distancia en metros para pinza ABIERTA")]
    public float distanciaMaxPinza = 0.08f;

    [Tooltip("Valor normalizado (0-1) por debajo del cual se considera pellizco activo")]
    [Range(0f, 1f)]
    public float umbralPellizco = 0.2f;

    [Header("Referencias a otros paneles")]
    [Tooltip("UIManager para reiniciar la calibración")]
    public UIManager uiManager;

    [Tooltip("Panel de despedida — se activa al finalizar la conexión")]
    public GameObject panelDespedida;

    //----- CAMPOS PRIVADOS ------
    private MaximoEstiramiento manoCalibrada;
    private ScriptWebRTC scriptWebRTC;
    private Transform mano;
    private Transform thumbTip;
    private Transform indexTip;
    private bool controlActivo = false;
    private Vector3 ultimaPosRobot = Vector3.zero;

    //--------------------------------------------------
    //INICIALIZACION - LLAMADO por UIManager.CerrarPanel()
    //--------------------------------------------------

    public void Iniciar(MaximoEstiramiento calibrada, ScriptWebRTC rtc, Transform thumb, Transform index)
    {
        manoCalibrada = calibrada;
        scriptWebRTC = rtc;
        thumbTip = thumb;
        indexTip = index;

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
        if(botonVolverCalibrar!= null) botonVolverCalibrar.onClick.AddListener(VolverACalibracion);
        if(botonFinalizarConexion != null) botonFinalizarConexion.onClick.AddListener(FinalizarConexion);

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
            textoPellizcoRobot.color = robotMoviendo ? colorAccionRobot : colorReposo;
        }

        ultimaPosRobot = coords;
    }

    //-------------------------------------------------------------
    //BOTON - VOLVER A CALIBRAR
    //-------------------------------------------------------------
    void VolverACalibracion()
    {
        //Pausamos el envio de datos
        controlActivo = false;

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

        gameObject.SetActive(false);

        if(uiManager == null)
        {
            Debug.LogError("PanelControl: uiManager no asignado en el Inspector");
            return;
        }

        uiManager.IniciarCalibracion();
        Debug.Log("Control Pausado - volviendo a calibración");
    }

    //---------------------------------------------------------------
    //BOTON - FINALIZAR CONEXION
    //---------------------------------------------------------------

    void FinalizarConexion()
    {
        //Detectamos el envio de los datos inmediatamente
        controlActivo = false;

        Debug.Log("Finalizando conexion WebRTC...");

        //Comprobacion de seguridad
        if(panelDespedida == null)
        {
            Debug.LogError("PanelControl: panelDespedida no asignado en el inspector");
            return;
        }

        //Desactivamos este panel
        gameObject.SetActive(false);

        //Activamos el panel de despedida y lo iniciamos
        panelDespedida.SetActive(true);
        var scriptDespedida = panelDespedida.GetComponent<panelDespedida>();
        if(scriptDespedida != null)
        {
            scriptDespedida.Iniciar(scriptWebRTC);
        }
        else
        {
            Debug.LogError("PanelControl: el panelDespedida no tiene componente PanelDespedida");
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
            botonVolverCalibrar.onClick.RemoveListener(VolverACalibracion);
        }

        if(botonFinalizarConexion != null)
        {
            botonFinalizarConexion.onClick.RemoveListener(FinalizarConexion);
        }
    }
}
