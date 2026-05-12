using System;
using UnityEngine;
using UnityEngine.UI;

public class PanelBienvenida : MonoBehaviour
{
    [Header("Boton")]
    [Tooltip("Boton que activa el panel de calibracion")]
    public Button botonEmpezar;

    public event Action OnEmpezar;
    //UIManager se suscribe a este evento para 
    //saber cuando el usuario quiere empezar. PanelBienvenida
    //no sabe que pasara despues, eso lo gestiona UIManager

    void Start()
    {
        if(botonEmpezar == null)
        {
            Debug.LogError("PanelBienvenida: botonEmpezar no asignado en el inspector");
            return;
        }
        //Registramos el listener del boton desde el codigo
        //Cuando el usuario haga click/pellizco sobre el, se llama a Empezar()
        botonEmpezar.onClick.AddListener(Empezar);
    }

    //-----------------------------------------------------
    //ACCION
    //-----------------------------------------------------
    void Empezar()
    {
        //Notificamos al UIManager que el usuario quiere empezar.
        //El ?. evita que se invoque si nadie se ha suscrito
        OnEmpezar?.Invoke();
        Debug.Log("PanelBienvenida: boton Empezar Pulsado");
    }

    //-----------------------------------------------------
    //LIMPIEZA
    //-----------------------------------------------------

    void OnDestroy()
    {
        if(botonEmpezar != null) botonEmpezar.onClick.RemoveListener(Empezar);
    }

}
