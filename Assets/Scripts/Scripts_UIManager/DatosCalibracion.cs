using UnityEngine;

public struct DatosCalibracion
{
    public MaximoEstiramiento manoCalibrada;
    //Script de calibracion
    //Contiene la posicion del maximo estiramiento y el flag guardado

    public Transform thumbTip;
    //Punta del pulgar de la mano calibrada
    //PanelControl la usa para calcular la apertura de la pinza

    public Transform indexTip;
    //Punta del indice de la mano calibrada
    //PanelControl la usa para calcular la apertura de la pinza

    //Constructor para crear el struct de forma legible
    public DatosCalibracion(MaximoEstiramiento mano, Transform thumb, Transform index)
    {
        manoCalibrada = mano;
        thumbTip = thumb;
        indexTip = index;
    }
}
