using UnityEngine;

public class MaximoDerecha : MaximoEstiramiento
{
    public Transform ManoDerecha; //Referencia a la mano derecha, esto es importante para que podamos obtener la posicion de la mano derecha y guardarla como el maximo estiramiento, lo que mejora la experiencia del control y la inmersion.
    protected override Transform ObtenerMano() //Implementacion del metodo abstracto para obtener la referencia a la mano derecha, esto es importante para garantizar que esta clase pueda proporcionar su propia implementacion de como obtener la mano, lo que mejora la flexibilidad y la reutilizacion del codigo.
    {
        return ManoDerecha; //Devolvemos la referencia a la mano derecha, esto es importante para que podamos utilizar esta referencia para obtener la posicion de la mano derecha y guardarla como el maximo estiramiento, lo que mejora la experiencia del control y la inmersion.
    }
}
