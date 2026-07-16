using UnityEngine;

public class UIManager : MonoBehaviour
{
    [Header("Paneles")]
    [Tooltip("Panel de bienvenida — activo al inicio")]
    public PanelBienvenida panelBienvenida;

    [Tooltip("Panel de calibración")]
    public PanelCalibracion panelCalibracion;

    [Tooltip("Panel de control del robot")]
    public PanelControl panelControl;

    [Tooltip("Panel de despedida")]
    public PanelDespedida panelDespedida;

    [Header("WebRTC")]
    [Tooltip("Script de comunicación WebRTC — se pasa a PanelControl")]
    public ScriptWebRTC scriptWebRTC;

    [Header("Metricas")]
    public NetworkMetrics networkMetrics;
    public MetricsLogger  metricsLogger;

    //----------------------------------------------------------
    // INICIO - Subscripcion a todos los eventos de los paneles
    //----------------------------------------------------------

    void Start()
    {
        //Comprobaciones de seguridad
        if (panelBienvenida  == null) { Debug.LogError("UIManager: panelBienvenida no asignado");  return; }
        if (panelCalibracion == null) { Debug.LogError("UIManager: panelCalibracion no asignado"); return; }
        if (panelControl     == null) { Debug.LogError("UIManager: panelControl no asignado");     return; }
        if (panelDespedida   == null) { Debug.LogError("UIManager: panelDespedida no asignado");   return; }
        if (scriptWebRTC     == null) { Debug.LogError("UIManager: scriptWebRTC no asignado");     return; }
        if (networkMetrics == null) { Debug.LogError("UIManager: networkMetrics no asignado"); return; }
        if (metricsLogger  == null) { Debug.LogError("UIManager: metricsLogger no asignado");  return; }

        //Subcripcion a eventos
        
        //PanelBienvenida: usuario pulsa "Empezar"
        panelBienvenida.OnEmpezar += IrACalibracion;

        //PanelCalibracion: calibracion completada
        panelCalibracion.OnCalibrado += IrAControl;

        //PanelControl: usuario quiere volver a calibrar
        panelControl.OnVolverCalibrar += IrACalibracion;

        //PanelControl: usuario quiere finalizar la sesion
        panelControl.OnFinalizar += IrADespedida;

        //PanelDespedida: usuario quiere volver a inicio
        panelDespedida.OnVolverInicio += IrABienvenida;

        //PanelDespedida: usuario quiere cerrar la app
        panelDespedida.OnCerrarApp += AlPulsarCerrarApp;

        

        //ESTADO INCIAL

        networkMetrics.Inicializar(scriptWebRTC);
        
        metricsLogger.Inicializar(networkMetrics, scriptWebRTC);

        MostrarSolo(panelBienvenida.gameObject);

        Debug.Log("UIManager iniciado - mostrando panel de bienvenida");

    }

    //-----------------------------------------------------
    //TRANSICIONES - llamada por los eventos de los paneles
    //-----------------------------------------------------

    void IrABienvenida()
    {
        //Reseteamos la calibracion por si volvemos desde despedida
        panelCalibracion.ResetearCalibracion();
        MostrarSolo(panelBienvenida.gameObject);
        Debug.Log("UIManager -> PanelBienvenida");
    }

    void IrACalibracion()
    {
        //Reseteamos la calibracion para empezar desde cero
        panelCalibracion.ResetearCalibracion();
        MostrarSolo(panelCalibracion.gameObject);
        
        // Reiniciamos la conexión de manera asíncrona para la nueva sesión
        if (scriptWebRTC != null)
        {
            scriptWebRTC.ReiniciarConexion();
        }
        
        Debug.Log("UIManager -> PanelCalibracion");
    }

    void IrAControl (DatosCalibracion datos)
    {
        //PanelControl necesita los datos de la calibracion para funcionar:
        //que mano fue calibrado, sus Transform de thumbTip/indexTip
        //y la referencia a ScriptWebRTC para enviar coordenadas
        MostrarSolo(panelControl.gameObject);
        panelControl.Iniciar(datos, scriptWebRTC);
        Debug.Log("UIManager -> PanelControl");
    }

    void IrADespedida()
    {
        metricsLogger.ExportarCSV();
        MostrarSolo(panelDespedida.gameObject);
        panelDespedida.Iniciar(scriptWebRTC);
        Debug.Log("UIManager -> PanelDespedida");
    }

    void AlPulsarCerrarApp()
    {
        Debug.Log("UIManager: cerrando Aplicacion");
        #if UNITY_EDITOR
            UnityEditor.EditorApplication.isPlaying = false;
        #else
            Application.Quit();
        #endif
    }

    //---------------------------------------------------
    //HELPER - ACTIVA UN PANEL Y DESACTIVA TODOS LOS DEMAS
    //---------------------------------------------------

    void MostrarSolo (GameObject panelActivo)
    {
        //Desactivamos todos los paneles y luego activo solo el que quiero
        //Asi nunca puede haber dos paneles activos simultaneos.
        panelBienvenida.gameObject.SetActive(false);
        panelCalibracion.gameObject.SetActive(false);
        panelControl.gameObject.SetActive(false);
        panelDespedida.gameObject.SetActive(false);

        panelActivo.SetActive(true);
    }

    //----------------------------------------------------
    //LIMPIEZA
    //----------------------------------------------------
    
    void OnDestroy()
    {
        //Antes de borrar elementos me desuscribo de ellos
        if(panelBienvenida != null) panelBienvenida.OnEmpezar -= IrACalibracion;
        if(panelCalibracion != null) panelCalibracion.OnCalibrado -= IrAControl;

        if(panelControl != null)
        {
            panelControl.OnVolverCalibrar -= IrACalibracion;
            panelControl.OnFinalizar -= IrADespedida;
        }

        if(panelDespedida != null)
        {
            panelDespedida.OnVolverInicio -= IrABienvenida;
            panelDespedida.OnCerrarApp -= AlPulsarCerrarApp;
        }
    }

}

