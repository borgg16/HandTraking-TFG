using System;
using UnityEngine;
using TMPro;
using UnityEngine.InputSystem;
using UnityEngine.UI;
public class PanelCalibracion : MonoBehaviour
{

    [Header("UI")]
    [Tooltip("Texto principal e Imagen — cambia según el estado")]
    public TextMeshProUGUI textoCalibracion;
    public GameObject contenedorImagen;
    public RawImage imagenCalibracion;

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

    [Header("Exploración lateral/vertical")]
    [Tooltip("Segundos de movimiento libre tras guardar el alcance máximo")]
    public float tiempoExploracion = 5f;
    private float timerExploracion = 0f;

    [Header("Esfera de Referencia")]
    public EsferaReferencia esferaReferencia;

    [Header("Imágenes de instrucción — Brazo Derecho")]
    [Tooltip("Ilustración: postura neutra con brazo derecho (codo 90°)")]
    public Texture2D spriteNeutroDerecha; 

    [Header("Imágenes de instrucción — Brazo Izquierdo")]
    [Tooltip("Ilustración: postura neutra con brazo izquierdo (codo 90°)")]
    public Texture2D spriteNeutroIzquierda;

    // Se dispara cuando el usuario completa la calibración con un pellizco.
    // Pasa DatosCalibracion con todo lo que PanelControl necesitará.
    // UIManager se suscribe para saber cuándo ir a PanelControl.
    public event Action<DatosCalibracion> OnCalibrado;

    //Vamos a crear los estados del flujo de calibración que vamos a seguir para tener el control en todo momento
    private enum Estado{ SeleccionMano, Instrucciones, EsperandoNeutro, EsperandoMaximo, EsperandoExploracion, Guardado}
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
        CancelInvoke(nameof(ActivarEsperaPellizco));
        CancelInvoke(nameof(ActivarEsperaMaximo));
        CancelInvoke(nameof(ActivarExploracion));
        maximoIzquierda.ResetearMaximo();
        maximoDerecha.ResetearMaximo();
        MostrarSeleccionMano();
        Debug.Log("PanelCalibracion: calibracion reseteada");
    }


    //---------------------------------------------
    // HELPER IMAGENES DE INSTRUCCION
    //---------------------------------------------
    Texture2D ElegirTexture2D(Texture2D izquierda, Texture2D derecha)
    {
        return (manoSeleccionada == maximoIzquierda) ? izquierda : derecha;
    }

    void MostrarImagen(Texture2D textura)
    {
        if(imagenCalibracion == null) return;
        if(textura != null)
        {
            imagenCalibracion.texture = textura;
            contenedorImagen.SetActive(true);
        }
        else
        {
            contenedorImagen.SetActive(false);
        }
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
        MostrarImagen(null);
    }

    void SeleccionarMano(string mano)
    {
        CancelInvoke(nameof(ActivarEsperaPellizco));
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
        estadoActual = Estado.Instrucciones;
        textoCalibracion.text = $"Replica con tu brazo {mano} la posición de la imagen:";
        MostrarImagen(ElegirTexture2D(spriteNeutroIzquierda, spriteNeutroDerecha));
        Invoke(nameof(ActivarEsperaPellizco),1.5f);
    }

    void ActivarEsperaPellizco()
    {
        estadoActual = Estado.EsperandoNeutro;
    }

    void Update() //Deteccion del pellizco de calibracion
    {
        switch (estadoActual)
        {
            case Estado.EsperandoNeutro:
            case Estado.EsperandoMaximo:
                ComprobarPellizco();
                break;
            case Estado.EsperandoExploracion:
                TickExploracion();
                break;
        }
    }

    void ComprobarPellizco()
    {
        if(thumbTipIzquierda == null || indexTipIzquierda == null || thumbTipDerecha == null || indexTipDerecha == null ) return;

        bool esIzquierda = (manoSeleccionada == maximoIzquierda);
        float distancia = esIzquierda ? Vector3.Distance(thumbTipIzquierda.position, indexTipIzquierda.position) : Vector3.Distance(thumbTipDerecha.position, indexTipDerecha.position);

        if(distancia >= distanciaPellizco) return;

        if(estadoActual == Estado.EsperandoNeutro)
        {
            manoSeleccionada.GuardarNeutro();
            MostrarImagen(null);
            textoCalibracion.text = "¡Postura neutra guardada!\n"
                                + "Ahora estira el brazo al máximo\n"
                                + "hacia el frente y haz otro pellizco.";
            Invoke(nameof(ActivarEsperaMaximo),1.5f);

        }else if (estadoActual == Estado.EsperandoMaximo)
        {
            manoSeleccionada.GuardarMaximo();
            estadoActual=Estado.Instrucciones;
            IniciarExploracion();
        }
    }

    void ActivarEsperaMaximo()
    {
        estadoActual = Estado.EsperandoMaximo;
    }

    void IniciarExploracion()
    {
        estadoActual = Estado.Instrucciones;
        timerExploracion = tiempoExploracion;

        textoCalibracion.text = "¡Alcance guardado!\n"
                                + "Mueve la mano arriba/abajo\n"
                                + "e izquierda/derecha libremente.\n"
                                + $"{tiempoExploracion:F0}s..."; //F0 es sin decimales
        
        //Mostramos la esfera para que el usuario vea su espacio de trabajo
        if(esferaReferencia != null)
        {
            bool esIzquierda = (manoSeleccionada == maximoIzquierda);
            Transform manoT = esIzquierda ? maximoIzquierda.ManoIzquierda : maximoDerecha.ManoDerecha;
            esferaReferencia.Iniciar(manoSeleccionada, manoT);
        }

        Invoke(nameof(ActivarExploracion),1.5f);
    }

    void ActivarExploracion()
    {
        estadoActual = Estado.EsperandoExploracion;
    }

    void TickExploracion()
    {
        bool esIzquierda = (manoSeleccionada == maximoIzquierda);
        Transform manoT = esIzquierda ? maximoIzquierda.ManoIzquierda : maximoDerecha.ManoDerecha;

        manoSeleccionada.ActualizarExploracion(manoT.position);

        timerExploracion -= Time.deltaTime;
        int segsRestantes = Mathf.CeilToInt(timerExploracion);

        textoCalibracion.text = "Mueve la mano libremente\n"
                                + "arriba/abajo e izquierda/derecha\n"
                                + $"{segsRestantes}s restantes...";

        if(timerExploracion <= 0f)
        {
            manoSeleccionada.GuardarExploracion();
            if(esferaReferencia != null) esferaReferencia.Ocultar();
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
