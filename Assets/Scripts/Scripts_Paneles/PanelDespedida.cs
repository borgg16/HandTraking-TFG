using System;
using UnityEngine;
using System.Collections;
using UnityEngine.UI;
using TMPro;

public class PanelDespedida : MonoBehaviour
{
    [Header("Textos")]
    public TextMeshProUGUI textoTitulo;
    public TextMeshProUGUI textoMensaje;
    public TextMeshProUGUI textoEstado;

    [Header("Botones")]
    public Button botonVolverInicio;
    public Button botonCerrarApp;

    [Header("Configuración")]
    [Tooltip("Mensaje personalizable que aparece en la pantalla de despedida")]
    [TextArea(2, 4)]
    public string mensajeDespedida = "Thanks for using the control system.\n"+
                                    "The connection with the robot arm has been closed.";

    [Tooltip("Segundos que tarda la secuencia de cierre")]
    public float tiempoCierre = 2f;

    //EVENTOS PUBLICOS
    public event Action OnVolverInicio;
    public event Action OnCerrarApp;

    //CAMPO PRIVADO
    private ScriptWebRTC scriptWebRTC;

    //---------------------------------------------
    //INICIACION DEL PROCESO DE CIERRE
    //---------------------------------------------
    public void Iniciar(ScriptWebRTC rtc)
    {
        scriptWebRTC = rtc;

        //Configuramos los textos iniciales
        if(textoTitulo != null) textoTitulo.text = "Ending connection...";
        if(textoMensaje != null) textoMensaje.text = mensajeDespedida;
        if(textoEstado != null) textoEstado.text = "Closing data channel...";

        //Ocultamos los botones hasta que el cierre se complete
        if(botonVolverInicio != null) botonVolverInicio.gameObject.SetActive(false);
        if(botonCerrarApp != null) botonCerrarApp.gameObject.SetActive(false);

        //Registramos los listeners de los botones
        if (botonVolverInicio != null)
            botonVolverInicio.onClick.AddListener(AlPulsarVolverInicio);
        if (botonCerrarApp != null)
            botonCerrarApp.onClick.AddListener(AlPulsarCerrarApp);

        //Lanzamos la secuencia de cierre
        StartCoroutine(SecuenciaCierre());

    }


    //-----------------------------------------------
    //SECUENCIA DE CIERRE
    //-----------------------------------------------
    // muy importante el orden de cierre para no dejar progresos zombies

    IEnumerator SecuenciaCierre()
    {
        //Paso 1: Cierre del DataChannel
        ActualizarEstado("Closing data channel...");
        yield return new WaitForSeconds(tiempoCierre * 0.33f);

        //Paso 2: Cierre del PeerConnection
        ActualizarEstado("Closing P2P connection...");
        yield return new WaitForSeconds(tiempoCierre * 0.34f);

        //ScriptWebRTC cierra todo en su OnDestroy()

        //Cierre completado
        ActualizarEstado("CONNECTION CLOSED CORRECTLY");
        if(textoTitulo != null) textoTitulo.text = "Session ended";

        //Mostramos los botones ahora que el cierre está completo
        if(botonVolverInicio != null) botonVolverInicio.gameObject.SetActive(true);
        if(botonCerrarApp != null) botonCerrarApp.gameObject.SetActive(true);

        Debug.Log("PanelDespedida: Secuencia de cierre completada");
    }

    void ActualizarEstado(string estado)
    {
        if(textoEstado != null) textoEstado.text = estado;
        Debug.Log($"Panel despedida: {estado}");
    }

    //---------------------------------------------
    //ACCIONES DE LOS BOTONES
    //---------------------------------------------
    void AlPulsarVolverInicio()
    {
        OnVolverInicio?.Invoke();
        Debug.Log("PanelDespedida: notificando UIManager -> volver al inicio");
    }


    void AlPulsarCerrarApp()
    {
        OnCerrarApp?.Invoke();
        Debug.Log("PanelDespedida: notificando UIManager -> cerrar aplicación");
    }


    //--------------------------------------------------
    //LIMPIEZA
    //--------------------------------------------------

    void OnDestroy()
    {
        if (botonVolverInicio != null)
            botonVolverInicio.onClick.RemoveListener(AlPulsarVolverInicio);
        if (botonCerrarApp != null)
            botonCerrarApp.onClick.RemoveListener(AlPulsarCerrarApp);
    }

}
