using UnityEngine;

public class MaximoIzquierda : MaximoEstiramiento
{
    public Transform ManoIzquierda; //Referencia a la mano izquierda, esto es importante para que podamos obtener la posicion de la mano izquierda y guardarla como el maximo estiramiento, lo que mejora la experiencia del control y la inmersion.
    protected override Transform ObtenerMano() //Implementacion del metodo abstracto para obtener la referencia a la mano izquierda, esto es importante para garantizar que esta clase pueda proporcionar su propia implementacion de como obtener la mano, lo que mejora la flexibilidad y la reutilizacion del codigo.
    {
        return ManoIzquierda; //Devolvemos la referencia a la mano izquierda, esto es importante para que podamos utilizar esta referencia para obtener la posicion de la mano izquierda y guardarla como el maximo estiramiento, lo que mejora la experiencia del control y la inmersion.
    }
}
