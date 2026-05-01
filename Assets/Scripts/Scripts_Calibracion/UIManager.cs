using UnityEngine;
using TMPro;
using UnityEngine.InputSystem;
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

    [Header("Input Pellizco")]
    public InputActionReference pellizcoIzquierdo;
    public InputActionReference pellizcoDerecho;

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

    void OnEnable()
    {
        pellizcoIzquierdo.action.Enable();
        pellizcoDerecho.action.Enable();
    }

    void OnDisable()
    {
        pellizcoIzquierdo.action.Disable();
        pellizcoDerecho.action.Disable();
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
            pellizcoSeleccionado = pellizcoIzquierdo;
        }
        else
        {
            manoSeleccionada = maximoDerecha;
            pellizcoSeleccionado = pellizcoDerecho;
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
        if (pellizcoSeleccionado == null) return;

        //Para detectar el pellizco (valor > 0.8 = pellizco fuerte)
        float valorPellizco = pellizcoSeleccionado.action.ReadValue<float>();
    
        if (valorPellizco > 0.8f)
        {
            manoSeleccionada.GuardarMaximo();
            MostrarConfirmacion();
        }
    
    }

    void MostrarConfirmacion()
    {
        estadoActual = Estado.Guardado;
        textoCalibracion.text = "¡Posición guardada!\nYa puedes controlar el brazo robot con esta mano.";
        
        Invoke(nameof(CerrarPanel),3f);
    }

    void CerrarPanel()
    {
        panelCalibracion.SetActive(false);
    }
}
