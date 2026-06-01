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
        botonIzquierda.onClick.AddListener(() => SeleccionarMano("left"));
        botonDerecha.onClick.AddListener(() => SeleccionarMano("right"));

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
        Debug.Log("Calibration Panel: calibration reset");
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
        textoCalibracion.text = "Which arm do you want to calibrate?";
        botonIzquierda.gameObject.SetActive(true);
        botonDerecha.gameObject.SetActive(true);
        MostrarImagen(null);
    }

    void SeleccionarMano(string mano)
    {
        CancelInvoke(nameof(ActivarEsperaPellizco));
        botonIzquierda.gameObject.SetActive(false);
        botonDerecha.gameObject.SetActive(false);

        if(mano == "left")
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
        textoCalibracion.text = $"Replicate the position in the image with your {mano} arm:";
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
            textoCalibracion.text = "Neutral posture maintained!"
                            + "\n"
                            + "Now extend your arm as far as it will go"
                            + "\n"
                            + "forward and do another pinch.";
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

        textoCalibracion.text = "Reach saved!\n"
                                +  "Move your hand up/down\n"
                                +  "and left/right freely.\n"
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

        textoCalibracion.text = "Move your hand freely\n"
                                + "up/down and left/right\n"
                                + $"{segsRestantes}s remaining...";

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
        textoCalibracion.text = "Position saved!\nYou can now control the robot arm with this hand.";
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
        Debug.Log($"Calibration completed — control panel active " +
                $"(hand {(esIzquierda ? "left" : "right")})");
    }
    
    //--------------------------------------------------------
    //LIMPIEZA
    //--------------------------------------------------------
    
    void OnDestroy()
    {
        if (botonIzquierda != null) botonIzquierda.onClick.RemoveListener(() => SeleccionarMano("left"));
        if (botonDerecha   != null) botonDerecha.onClick.RemoveListener(  () => SeleccionarMano("right"));
    }

}
