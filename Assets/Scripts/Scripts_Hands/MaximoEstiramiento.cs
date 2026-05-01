using UnityEngine;
//Este script se encarga de controlar el maximo estiramiento de los brazos, esto nos va a servir para crear la variable
//para calcular despues las posiciones relativas de cara a que independientemente del tamaño del jugador, el estiramiento de los brazos sea el mismo, esto se va a usar para calcular la posicion de las manos en funcion de la posicion de los hombros
//Gracias a esto, podremos estirar brazo robot siempre por igual independientemente de la longitud de los brazos del jugador, esto es importante para que el brazo robot se comporte de manera consistente y predecible, sin importar el tamaño del jugador, lo que mejora la experiencia del control y la inmersión.   
public abstract class MaximoEstiramiento : MonoBehaviour
{
    protected Trasform mano; //Esta Protected para que solo o mi propia clase o las hijas puedan acceder a dicha variable, esto es importante para mantener la encapsulacion y evitar que otras clases puedan modificar esta variable de manera indebida, lo que podria causar errores o comportamientos inesperados en el juego. Al hacerla protected, se garantiza que solo las clases que heredan de MaximoEstiramiento puedan acceder a esta variable, lo que mejora la seguridad y la integridad del código.
    public Vector3 maximoEstiramiento { get; private set; } //Esta propiedad es de solo lectura para otras clases, lo que significa que solo se puede establecer dentro de esta clase, lo que garantiza que el valor del maximo estiramiento no pueda ser modificado por otras clases, lo que mejora la seguridad y la integridad del código. Al hacerla pública, se permite que otras clases puedan acceder a este valor para realizar cálculos o tomar decisiones basadas en el máximo estiramiento, pero sin permitir que lo modifiquen directamente.
    public bool guardado { get; private set; } = false; //Esta propiedad es de solo lectura para otras clases, lo que significa que solo se puede establecer dentro de esta clase, lo que garantiza que el valor de guardado no pueda ser modificado por otras clases, lo que mejora la seguridad y la integridad del código. Al hacerla pública, se permite que otras clases puedan acceder a este valor para realizar cálculos o tomar decisiones basadas en si el máximo estiramiento ha sido guardado o no, pero sin permitir que lo modifiquen directamente.

    protected abstract Transform ObtenerMano(); //Este metodo es abstracto, lo que significa que las clases que hereden de MaximoEstiramiento deben implementar este metodo para obtener la referencia a la mano correspondiente, esto es importante para garantizar que cada clase hija pueda proporcionar su propia implementacion de como obtener la mano, lo que mejora la flexibilidad y la reutilizacion del codigo.

    void Start()
    {
        mano = ObtenerMano(); //Obtenemos la referencia a la mano utilizando el metodo abstracto, esto es importante para garantizar que cada clase hija pueda proporcionar su propia implementacion de como obtener la mano, lo que mejora la flexibilidad y la reutilizacion del codigo.
    }

    public void GuardarMaximo()
    {
        maximoEstiramiento = mano.position; //Guardamos la posicion actual de la mano como el maximo estiramiento, esto es importante para que podamos utilizar este valor posteriormente para calcular las posiciones relativas de las manos en funcion de la posicion de los hombros, lo que mejora la experiencia del control y la inmersion.
        guardado = true; //Indicamos que el maximo estiramiento ha sido guardado, esto es importante para que otras clases puedan verificar si el maximo estiramiento ha sido guardado o no antes de realizar calculos o tomar decisiones basadas en este valor, lo que mejora la seguridad y la integridad del codigo.
        Debug.Log($"Maximo estiramiento guardado en {gameObject.name} : {maximoEstiramiento}"); //Imprimimos en la consola el valor del maximo estiramiento guardado, esto es importante para que podamos verificar que el valor se ha guardado correctamente y para facilitar la depuracion del codigo.
    }

}
