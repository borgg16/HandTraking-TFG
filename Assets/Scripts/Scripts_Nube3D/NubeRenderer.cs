using UnityEngine;

/*
    NubeRenderer
    ------------
    Pinta la malla de puntos que entrega el NubeReceiver dentro de la ventana
    "3D POINT CLOUD" del panel de control.

    El objeto cuelga del Canvas (world space, escala 0.001) para que el visor
    acompañe siempre al panel: asi la nube queda encuadrada en su ventana igual
    que antes lo estaba el video 2D.

    Ajustes tipicos desde el inspector:
      - escalaVisor    : cuanto ocupa la nube dentro de la ventana.
      - desplazamiento : recentra la nube (la RealSense entrega Z entre 0.3 y 1.5 m,
                         asi que por defecto restamos 0.9 para dejarla centrada).
      - rotacionVisor  : desde que lado se mira la escena capturada.
*/
[RequireComponent(typeof(MeshFilter))]
[RequireComponent(typeof(MeshRenderer))]
public class NubeRenderer : MonoBehaviour
{
    [Header("Material de la nube")]
    [Tooltip("Material con el shader Custom/NubePuntos (MaterialNube)")]
    public Material materialPuntos;

    [Tooltip("Tamaño de cada punto en pixeles (propiedad _PointSize del shader)")]
    [Range(1f, 20f)]
    public float tamanoPunto = 5f;

    [Header("Encuadre dentro de la ventana")]
    [Tooltip("Escala del visor — 1 = tamaño real de la nube capturada")]
    [Range(0.05f, 5f)]
    public float escalaVisor = 1f;

    [Tooltip("Recentrado de la nube respecto al origen del visor, en metros de la nube. " +
             "La RealSense entrega Z entre 0.3 y 1.5 m, así que -0.9 la deja centrada en la ventana.")]
    public Vector3 desplazamiento = new Vector3(0f, 0f, -0.9f);

    [Tooltip("Giro del visor. (0,0,0) = se ve la escena desde el punto de vista de la cámara del robot; " +
             "(0,180,0) = se ve desde el lado opuesto")]
    public Vector3 rotacionVisor = Vector3.zero;

    [Tooltip("Solo si el emisor NO corrige el eje Y de la cámara (el pipeline actual ya lo corrige en Python)")]
    public bool invertirEjeY = false;

    [Header("Compatibilidad")]
    [Tooltip("Si la malla decodificada no viene como nube de puntos, se reconstruyen los indices")]
    public bool forzarTopologiaPuntos = true;

    public int PuntosVisibles { get; private set; }

    private MeshFilter meshFilter;
    private MeshRenderer meshRenderer;
    private Material instanciaMaterial;

    //-------------------------------------------------------------------------
    void Awake()
    {
        Preparar();
    }

    //El visor cuelga del panel de control, que arranca desactivado: puede llegarnos
    //una nube antes de que Unity haya ejecutado el Awake, así que cacheamos bajo demanda.
    private void Preparar()
    {
        if (meshFilter != null) return;

        meshFilter = GetComponent<MeshFilter>();
        meshRenderer = GetComponent<MeshRenderer>();

        if (materialPuntos != null) meshRenderer.material = materialPuntos;

        //Trabajamos sobre la instancia para no ensuciar el material del proyecto
        instanciaMaterial = meshRenderer.material;
        AplicarTamanoPunto();
        AplicarEncuadre();
    }

    //-------------------------------------------------------------------------
    // ENTRADA PRINCIPAL — llamada por NubeReceiver en el hilo principal
    //-------------------------------------------------------------------------
    public void MostrarNube(Mesh malla)
    {
        if (malla == null) return;
        Preparar();

        if (forzarTopologiaPuntos && malla.GetTopology(0) != MeshTopology.Points)
        {
            int n = malla.vertexCount;
            int[] indices = new int[n];
            for (int i = 0; i < n; i++) indices[i] = i;
            malla.SetIndices(indices, MeshTopology.Points, 0, true);
        }

        //Draco no siempre rellena los bounds y sin ellos el frustum culling
        //puede hacer desaparecer la nube segun donde mire el operario.
        malla.RecalculateBounds();

        //Liberamos la malla anterior: llegan 10-15 por segundo y no se recolectan solas
        Mesh anterior = meshFilter.sharedMesh;
        meshFilter.mesh = malla;
        if (anterior != null) Destroy(anterior);

        PuntosVisibles = malla.vertexCount;
    }

    public void Limpiar()
    {
        Mesh anterior = meshFilter != null ? meshFilter.sharedMesh : null;
        if (anterior != null) Destroy(anterior);
        if (meshFilter != null) meshFilter.mesh = null;
        PuntosVisibles = 0;
    }

    //-------------------------------------------------------------------------
    // ENCUADRE
    //-------------------------------------------------------------------------
    private void AplicarEncuadre()
    {
        float signoY = invertirEjeY ? -1f : 1f;
        Vector3 escala = new Vector3(escalaVisor, escalaVisor * signoY, escalaVisor);
        Quaternion giro = Quaternion.Euler(rotacionVisor);

        transform.localScale = escala;
        transform.localRotation = giro;

        //El desplazamiento va en metros de la nube, así que lo pasamos por la misma
        //escala y giro que los vértices: así el recentrado no depende de escalaVisor
        //ni se descoloca al girar el visor.
        transform.localPosition = giro * Vector3.Scale(escala, desplazamiento);
    }

    private void AplicarTamanoPunto()
    {
        if (instanciaMaterial != null && instanciaMaterial.HasProperty("_PointSize"))
        {
            instanciaMaterial.SetFloat("_PointSize", tamanoPunto);
        }
    }

#if UNITY_EDITOR
    //Permite recolocar el visor en vivo desde el inspector mientras se prueba
    void OnValidate()
    {
        if (!Application.isPlaying) return;
        AplicarEncuadre();
        AplicarTamanoPunto();
    }
#endif

    void OnDestroy()
    {
        Limpiar();
    }
}
