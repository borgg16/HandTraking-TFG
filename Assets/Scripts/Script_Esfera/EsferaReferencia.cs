using UnityEngine;

public class EsferaReferencia : MonoBehaviour
{
    [Header("Colores")]
    public Color colorSeguro = new Color(0f, 1f, 0f, 0.12f);   // verde
    public Color colorAviso  = new Color(1f, 1f, 0f, 0.18f);   // amarillo
    public Color colorLimite = new Color(1f, 0f, 0f, 0.25f);   // rojo

    [Tooltip("Fracción del radio donde empieza el aviso")]
    [Range(0f, 1f)] public float umbralAviso  = 0.70f;
    [Tooltip("Fracción del radio donde empieza el rojo")]
    [Range(0f, 1f)] public float umbralLimite = 0.90f;

    private Renderer esferaRenderer;
    private Material mat;
    private MaximoEstiramiento manoCalibrada;
    private Transform mano;

    void Awake()
    {
        esferaRenderer = GetComponentInChildren<Renderer>();
        mat = esferaRenderer.material; //instancia propia para no tocar el Asset
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

        //Posicion y Tamaño
        transform.position = neutro;
        transform.localScale = Vector3.one * radio * 2f;

        //Color Según proximidad de la mano al limite
        if(mano != null && radio > 0f)
        {
            float PosicionNorm = Vector3.Distance(mano.position, neutro) / radio;
            Color c;
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
    }


}
