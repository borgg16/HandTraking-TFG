using UnityEngine;
using System.Collections;
using UnityEngine.UI;
using TMPro;

public class PanelDespedida : MonoBehaviour
{
    [Header("Textos")]
    [Tooltip("Texto principal del panel")]
    public TextMeshProUGUI textoTitulo;

    [Tooltip("Mensaje de despedida personalizable")]
    public TextMeshProUGUI textoMensaje;

    [Tooltip("Muestra el estado del cierre de conexión en tiempo real")]
    public TextMeshProUGUI textoEstado;

    [Header("Botones")]
    [Tooltip("Vuelve al panel de bienvenida para iniciar una nueva sesión")]
    public Button botonVolverInicio;

    [Tooltip("Cierra la aplicación completamente")]
    public Button botonCerrarApp;

    [Header("Paneles")]
    [Tooltip("Panel de bienvenida — para volver al inicio")]
    public GameObject panelBienvenida;

    [Tooltip("Referencia al ScriptWebRTC para cerrar la conexión")]
    public ScriptWebRTC scriptWebRTC;

    [Header("Configuración")]
    [Tooltip("Mensaje personalizable que aparece en la pantalla de despedida")]
    [TextArea(2, 4)]
    public string mensajeDespedida = "Gracias por usar el sistema de control.\n"+
                                     "La conexión con el brazo robot ha sido cerrada.";

    [Tooltip("Segundos que tarda el cierre antes de mostrar los botones")]
    public float tiempoCierre = 2f;

    //---------------------------------------------
    //INICIACION DEL PROCESO DE CIERRE
    //---------------------------------------------
    public void Iniciar(ScriptWebRTC rtc)
    {
        scriptWebRTC = rtc;

        //Configuramos los textos iniciales
        if(textoTitulo != null) textoTitulo.text = "Finalizando conexión...";
        if(textoMensaje != null) textoMensaje.text = mensajeDespedida;
        if(textoEstado != null) textoEstado.text = "Cerrando canal de datos...";

        //Ocultamos los botones hasta que el cierre se complete
        if(botonVolverInicio != null) botonVolverInicio.gameObject.SetActive(false);
        if(botonCerrarApp != null) botonCerrarApp.gameObject.SetActive(false);

        //Registramos los listeners de los botones
        if (botonVolverInicio != null)
            botonVolverInicio.onClick.AddListener(VolverAlInicio);
        if (botonCerrarApp != null)
            botonCerrarApp.onClick.AddListener(CerrarAplicacion);

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
        ActualizarEstado("Cerrando canal de datos...");
        yield return new WaitForSeconds(tiempoCierre * 0.33f);

        //Paso 2: Cierre del PeerConnection
        ActualizarEstado("Cerrando conexion P2P...");
        yield return new WaitForSeconds(tiempoCierre * 0.34f);

        //ScriptWebRTC cierra todo en su OnDestroy()

        //Cierre completado
        ActualizarEstado("CONEXION CERRADA CORRECTAMENTE");
        if(textoTitulo != null) textoTitulo.text = "Sesion finalizada";

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
    void VolverAlInicio()
    {
        //Volvemos al panel de bienvenida para iniciar una nueva sesion.
        //No recargamos la escena, simplemente activamos el panel de bienvenida
        if(panelBienvenida == null)
        {
            Debug.LogError("Panel Despedida: panelBienvenida no asignado en el Inspector");
            return;
        }

        panelBienvenida.SetActive(true);
        gameObject.SetActive(false);

        Debug.Log("Volviendo al panel de bienvenida");    
    }


    void CerrarAplicacion()
    {
        Debug.Log("Cerrando Aplicación...");
        //Application.Quit() cierra la aplicacion en el dispositivo
        //En el editor de Unity no cierra nada, es el comportamiento correcto
        //para pruebas (no queremos cerrar el editor accidentalmente)
        #if UNITY_EDITOR
            UnityEditor.EditorApplication.isPlaying = false;
        #else
            Application.Quit();
        #endif
    }


    //--------------------------------------------------
    //LIMPIEZA
    //--------------------------------------------------

    void OnDestroy()
    {
        if (botonVolverInicio != null)
            botonVolverInicio.onClick.RemoveListener(VolverAlInicio);
        if (botonCerrarApp != null)
            botonCerrarApp.onClick.RemoveListener(CerrarAplicacion);
    }

}
