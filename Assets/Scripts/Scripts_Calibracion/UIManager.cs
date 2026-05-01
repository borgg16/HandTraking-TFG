using UnityEngine;
using TMPro;
using UnityEngine.InputSystem;
using UnityEngine.UI;
public class UIManager : MonoBehaviour
{

    [Header("UI del panel de calibración")]
    public GameObject panelCalibracion;
    public TextMeshProUGUI textoCalibracion;
    public Button botonIzquierda;
    public Button botonDerecha;

    [Header("Scripts de Maximo")]
    public MaximoIzquierda maximoIzquierda;
    public MaximoDerecha maximoDerecha;

    [Header("Detección de Pellizco")]
    public Transform thumbTipIzquierda; // En el codigo de ejemplo es el L_thumbTip
    public Transform indexTipIzquierda; // En el codigo de ejemplo es el L_indexTip
    public Transform thumbTipDerecha; //En el codigo de ejemplo es el R_thumbTip
    public Transform indexTipDerecha; //En el codigo de ejemplo es el R_indexTip

    public float distanciaPellizco = 0.02f; // Distancia en Metros para considerar un pellizco

    //Vamos a crear los estados del flujo de calibración que vamos a seguir para tener el control en todo momento
    private enum Estado{ SeleccionMano, Intrucciones, EsperandoPellizco, Guardado}
    private Estado estadoActual = Estado.SeleccionMano;

    private MaximoEstiramiento manoSeleccionada;
    private InputActionReference pellizcoSeleccionado;

    void Start()
    {
        //Configurar los botones para seleccionar la mano
        botonIzquierda.onClick.AddListener(() => SeleccionarMano("izquierda"));
        botonDerecha.onClick.AddListener(() => SeleccionarMano("derecha"));

        //Comenzamos con el estado de Seleccion de Mano
        MostrarSeleccionMano();
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

    void Update()
    {
        if (estadoActual != Estado.EsperandoPellizco) return;
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
        
        Invoke(nameof(CerrarPanel),3f); //despues de 3 segundos se cierra el panel, esto es importante para que el usuario tenga tiempo de leer la confirmacion antes de que el panel desaparezca, lo que mejora la experiencia del usuario.
    }

    void CerrarPanel()
    {
        panelCalibracion.SetActive(false);
    }
}
