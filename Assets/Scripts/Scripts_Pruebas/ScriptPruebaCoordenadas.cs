using UnityEngine;

public class ScriptPruebaCoordenadas : MonoBehaviour
{
    public Transform[] objetosAMonitorear;
    void Update()
    {
        foreach (Transform obj in objetosAMonitorear)
        {
            if (obj != null)
                Debug.Log($"[{obj.name}] pos: {obj.position}");
        }
    }
}

