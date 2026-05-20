using UnityEngine;

public class EsferaReferencia : MonoBehaviour
{
    [Header("Colores")]
    public Color colorSeguro = new Color(0f, 1f, 0f, 0.6f);   // verde
    public Color colorAviso  = new Color(1f, 1f, 0f, 0.7f);   // amarillo
    public Color colorLimite = new Color(1f, 0f, 0f, 0.8f);   // rojo

    [Tooltip("Fracción del radio donde empieza el aviso")]
    [Range(0f, 1f)] public float umbralAviso  = 0.70f;
    [Tooltip("Fracción del radio donde empieza el rojo")]
    [Range(0f, 1f)] public float umbralLimite = 0.90f;

    [Tooltip("Grosor de los aros en metros")]
    public float grosorAro = 0.004f;

    [Tooltip("Segmentos por aro — más = más suave")]
    [Range(16, 64)] public int segmentos = 48;

    private MaximoEstiramiento manoCalibrada;
    private Transform mano;

    // Los tres aros: XY(horizontal), XZ(vertical frontal), YZ(vertical lateral)
    private LineRenderer aroXY;
    private LineRenderer aroXZ;
    private LineRenderer aroYZ;

    float radioActual = 0f;

    void Awake()
    {
        //Ocultamos el mesh original(esfera), ya que no lo necesitamos
        var mr = GetComponentInChildren<MeshRenderer>();
        if(mr != null) mr.enabled = false;

        //Creamos los 3 aros como hijos de este GameObject
        aroXY = CrearAro("Aro_XY");
        aroXZ = CrearAro("Aro_XZ");
        aroYZ = CrearAro("Aro_YZ");

        gameObject.SetActive(false);
    }

    //Llamada desde PanelCalibracion(exploracion) y PanelControl(control)
    public void Iniciar(MaximoEstiramiento calibrada, Transform manoTransform)
    {
        manoCalibrada = calibrada;
        mano = manoTransform;
        gameObject.SetActive(true);
    }

    public void Ocultar() => gameObject.SetActive(false);

    void Update()
    {
        if(manoCalibrada == null || !manoCalibrada.neutroGuardado) return;

        Vector3 neutro = manoCalibrada.posturaNeutra;
        float radio = manoCalibrada.guardado ? Vector3.Distance(neutro, manoCalibrada.maximoEstiramiento) : 0.4f;
        //durante la fase de pasar de neutro->maxima, establecemos el radio provisional de 0.4f

        if(!Mathf.Approximately(radio, radioActual))
        {
            radioActual = radio;
            DibujarAros(radio);
        }

        //Posicion y Tamaño
        transform.position = neutro;

        //Color Según proximidad de la mano al limite
        Color c = colorSeguro;
        if(mano != null && radio > 0f)
        {
            float PosicionNorm = Vector3.Distance(mano.position, neutro) / radio;
            
            if(PosicionNorm < umbralAviso)
            {
                c = colorSeguro;
            }else if (PosicionNorm < umbralLimite)
            {
                c = Color.Lerp(colorSeguro, colorAviso, (PosicionNorm-umbralAviso)/(umbralLimite-umbralAviso));
            }
            else
            {
                c = Color.Lerp(colorAviso, colorLimite, Mathf.Clamp01((PosicionNorm - umbralLimite) / (1f - umbralLimite)));
                mat.color = c;
            }
        }
        AplicarColor(aroXY,c);
        AplicarColor(aroXZ,c);
        AplicarColor(aroYZ,c);
    }

    //------------------------------------------------------
    //FUNCIONES DEDICADAS A LOS AROS
    //------------------------------------------------------
    LineRenderer CrearAro(string nombre)
    {
        var go = new GameObject(nombre);
        go.transform.SetParent(transform, false);

        var lr = go.AddComponent<LineRenderer>();
        lr.useWorldSpace   = false;       // coordenadas locales -> se mueve con el padre
        lr.loop            = true;
        lr.startWidth      = grosorAro;
        lr.endWidth        = grosorAro;
        lr.positionCount   = segmentos;
        lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        lr.receiveShadows  = false;

        // Material Unlit para que no dependa de la iluminación
        lr.material = new Material(Shader.Find("Universal Render Pipeline/Unlit"));
        lr.material.SetFloat("_Surface", 1f); // Transparent

        return lr;
    }

    void DibujarAros(float radio)
    {
        // Aro XY — plano horizontal (Y constante)
        for (int i = 0; i < segmentos; i++)
        {
            float angulo = i * 2f * Mathf.PI / segmentos;
            aroXY.SetPosition(i, new Vector3(
                Mathf.Cos(angulo) * radio,
                0f,
                Mathf.Sin(angulo) * radio));
        }

        // Aro XZ — plano vertical frontal (Z constante)
        for (int i = 0; i < segmentos; i++)
        {
            float angulo = i * 2f * Mathf.PI / segmentos;
            aroXZ.SetPosition(i, new Vector3(
                Mathf.Cos(angulo) * radio,
                Mathf.Sin(angulo) * radio,
                0f));
        }

        // Aro YZ — plano vertical lateral (X constante)
        for (int i = 0; i < segmentos; i++)
        {
            float angulo = i * 2f * Mathf.PI / segmentos;
            aroYZ.SetPosition(i, new Vector3(
                0f,
                Mathf.Sin(angulo) * radio,
                Mathf.Cos(angulo) * radio));
        }
    }

    void AplicarColor(LineRenderer lr, Color c)
    {
        if (lr == null) return;
        lr.startColor = c;
        lr.endColor   = c;
    }

}
