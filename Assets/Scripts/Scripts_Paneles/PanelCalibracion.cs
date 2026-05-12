using System;
using UnityEngine;
using TMPro;
using UnityEngine.InputSystem;
using UnityEngine.UI;
public class PanelCalibracion : MonoBehaviour
{

    [Header("UI")]
    [Tooltip("Texto principal — cambia según el estado")]
    public TextMeshProUGUI textoCalibracion;

    [Tooltip("Botón para seleccionar el brazo izquierdo")]
    public Button botonIzquierda;

    [Tooltip("Botón para seleccionar el brazo derecho")]
    public Button botonDerecha;

    [Header("Scripts de Máximo Estiramiento")]
    [Tooltip("Script MaximoIzquierda en el GameObject UIManager")]
    public MaximoIzquierda maximoIzquierda;

    [Tooltip("Script MaximoDerecha en el GameObject UIManager")]
    public MaximoDerecha maximoDerecha;

    [Header("Detección de Pellizco")]
    [Tooltip("L_ThumbTip — jerarquía Left Hand Tracking")]
    public Transform thumbTipIzquierda;

    [Tooltip("L_IndexTip — jerarquía Left Hand Tracking")]
    public Transform indexTipIzquierda;

    [Tooltip("R_ThumbTip — jerarquía Right Hand Tracking")]
    public Transform thumbTipDerecha;

    [Tooltip("R_IndexTip — jerarquía Right Hand Tracking")]
    public Transform indexTipDerecha;

    [Tooltip("Distancia en metros para considerar pellizco de calibración")]
    public float distanciaPellizco = 0.02f;

    // Se dispara cuando el usuario completa la calibración con un pellizco.
    // Pasa DatosCalibracion con todo lo que PanelControl necesitará.
    // UIManager se suscribe para saber cuándo ir a PanelControl.
    public event Action<DatosCalibracion> OnCalibrado;

    //Vamos a crear los estados del flujo de calibración que vamos a seguir para tener el control en todo momento
    private enum Estado{ SeleccionMano, Intrucciones, EsperandoPellizco, Guardado}
    private Estado estadoActual = Estado.SeleccionMano;

    private MaximoEstiramiento manoSeleccionada;

    void Start()
    {
        //Configurar los botones para seleccionar la mano
        botonIzquierda.onClick.AddListener(() => SeleccionarMano("izquierda"));
        botonDerecha.onClick.AddListener(() => SeleccionarMano("derecha"));

        //Comenzamos con el estado de Seleccion de Mano
        MostrarSeleccionMano();
    }


    //----------------------------------------------
    //RESETEO DE CALIBRACION POR LLAMADA DEL UIMANAGER
    //----------------------------------------------
    public void ResetearCalibracion()
    {
        //Borramos la calibracion anterior para empezar de cero
        //Llamada por UIManager antes de mostrar el panel
        maximoIzquierda.ResetearMaximo();
        maximoDerecha.ResetearMaximo();
        MostrarSeleccionMano();
        Debug.Log("PanelCalibracion: calibracion reseteada");
    }



    //----------------------------------------------
    // ESTADOS 
    //----------------------------------------------
    
    void MostrarSeleccionMano()
    {
        estadoActual = Estado.SeleccionMano;
        textoCalibracion.text = "¿Qué brazo deseas calibrar?";
        botonIzquierda.gameObject.SetActive(true);
        botonDerecha.gameObject.SetActive(true);
    }

    void SeleccionarMano(string mano)
    {
        botonIzquierda.gameObject.SetActive(false);
        botonDerecha.gameObject.SetActive(false);

        if(mano == "izquierda")
        {
            manoSeleccionada = maximoIzquierda;
        }
        else
        {
            manoSeleccionada = maximoDerecha;
        }

        MostrarInstrucciones(mano);
    }

    void MostrarInstrucciones(string mano)
    {
        estadoActual = Estado.Intrucciones;
        textoCalibracion.text = $"Estira el brazo {mano} hacia el frente\n"
        + "formando un ángulo de 90 grados con el torso.\n"
        + "Luego haz un pellizco para guardar la posición.";

        estadoActual = Estado.EsperandoPellizco;
    }

    void Update() //Deteccion del pellizco de calibracion
    {
        if (estadoActual != Estado.EsperandoPellizco) return;
        
        if (thumbTipIzquierda == null || indexTipIzquierda == null ||
            thumbTipDerecha   == null || indexTipDerecha   == null)
        {
            Debug.LogWarning("panelCalibracion: faltan Transform de pellizco en el Inspector");
            return;
        }
        
        bool esIzquierda = (manoSeleccionada == maximoIzquierda); //Si son iguales es izquierda (true), si no es derecha

        float distancia = esIzquierda ? Vector3.Distance(thumbTipIzquierda.position, indexTipIzquierda.position) : Vector3.Distance(thumbTipDerecha.position, indexTipDerecha.position); 
        Debug.Log("Distancia Pellizco: " + distancia);

        if(distancia < distanciaPellizco)
        {
            manoSeleccionada.GuardarMaximo();
            MostrarConfirmacion();
        }

    }

    void MostrarConfirmacion()
    {
        estadoActual = Estado.Guardado;
        textoCalibracion.text = "¡Posición guardada!\nYa puedes controlar el brazo robot con esta mano.";
        
        Invoke(nameof(NotificarCalibrado),3f); //despues de 3 segundos se cierra el panel, esto es importante para que el usuario tenga tiempo de leer la confirmacion antes de que el panel desaparezca, lo que mejora la experiencia del usuario.
    }
    void NotificarCalibrado()
    {

        // Determinamos qué thumb/index pasar según la mano calibrada
        bool esIzquierda   = (manoSeleccionada == maximoIzquierda);
        Transform thumbTip = esIzquierda ? thumbTipIzquierda : thumbTipDerecha;
        Transform indexTip = esIzquierda ? indexTipIzquierda : indexTipDerecha;

        DatosCalibracion datos = new DatosCalibracion(manoSeleccionada, thumbTip, indexTip);

        //Notificamos al UIManager para que active el Panel de Control con estos datos
        OnCalibrado?.Invoke(datos);
        Debug.Log($"Calibración completada — panel de control activo " +
                $"(mano {(esIzquierda ? "izquierda" : "derecha")})");
    }
    
    //--------------------------------------------------------
    //LIMPIEZA
    //--------------------------------------------------------
    
    void OnDestroy()
    {
        if (botonIzquierda != null) botonIzquierda.onClick.RemoveListener(() => SeleccionarMano("izquierda"));
        if (botonDerecha   != null) botonDerecha.onClick.RemoveListener(  () => SeleccionarMano("derecha"));
    }

}
