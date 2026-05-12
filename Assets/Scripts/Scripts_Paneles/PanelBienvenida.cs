using UnityEngine;
using UnityEngine.UI;

public class PanelBienvenida : MonoBehaviour
{
    [Header("Boton")]
    [Tooltip("Boton que activa el panel de calibracion")]
    public Button botonEmpezar;

    [Header("Panel siguiente")]
    [Tooltip("Panel de Calibracion - se activa al pulsar el boton")]
    public GameObject panelCalibracion;

    void Start()
    {
        //Registramos el listener del boton desde el codigo
        //Cuando el usuario haga click/pellizco sobre el, se llama a Empezar()
        botonEmpezar.onClick.AddListener(Empezar);
    }

    void Empezar()
    {
        //Ocultamos este panel y mostramos el de calibracion
        //SetActive(false) desactiva el GameObject completo
        //deja de renderizarse y de recibir eventos de inputs
        gameObject.SetActive(false);

        if(panelCalibracion == null)
        {
            Debug.LogError("Panel Bienvenida: panelCalibracion no asignado en el Inspector");
            return;
        }

        panelCalibracion.SetActive(true);
        Debug.Log("PanelBienvenida cerrado - Iniciando Calibracion");
    }

}
