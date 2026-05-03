using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.Interactors;
using UnityEngine.XR.Interaction.Toolkit.UI;
using UnityEngine.EventSystems;
using System.Collections.Generic;

public class XRInteractionDiagnostic : MonoBehaviour
{
    public XRBaseInteractor leftInteractor;
    public XRBaseInteractor rightInteractor;
    public Canvas targetCanvas;

    private float _timer = 0f;
    private const float INTERVAL = 2f;

    void Start()
    {
        Debug.Log("=== XR DIAGNOSTIC INICIADO ===");

        // Auto-detect interactors
        if (leftInteractor == null || rightInteractor == null)
        {
            var all = FindObjectsByType<XRBaseInteractor>(FindObjectsSortMode.None);
            foreach (var i in all)
            {
                string n = i.gameObject.name.ToLower();
                if (leftInteractor == null && n.Contains("left"))   leftInteractor  = i;
                if (rightInteractor == null && n.Contains("right"))  rightInteractor = i;
            }
        }

        // EventSystem
        var es = FindFirstObjectByType<EventSystem>();
        if (es == null)
            Debug.LogError("[DIAGNOSTICO] NO HAY EVENTSYSTEM en la escena!");
        else if (es.GetComponent<XRUIInputModule>() == null)
            Debug.LogError("[DIAGNOSTICO] EventSystem NO tiene XRUIInputModule!");
        else
            Debug.Log("[DIAGNOSTICO] EventSystem OK");

        // Canvas
        if (targetCanvas == null)
            targetCanvas = FindFirstObjectByType<Canvas>();
        if (targetCanvas != null) CheckCanvas(targetCanvas);
        else Debug.LogError("[DIAGNOSTICO] NO SE ENCONTRO NINGUN CANVAS!");

        // Interactors
        CheckInteractor(leftInteractor,  "LEFT");
        CheckInteractor(rightInteractor, "RIGHT");

        // XR Interaction Manager
        var mgr = FindFirstObjectByType<XRInteractionManager>();
        if (mgr == null) Debug.LogError("[DIAGNOSTICO] NO HAY XRInteractionManager!");
        else             Debug.Log("[DIAGNOSTICO] XRInteractionManager OK: " + mgr.gameObject.name);
    }

    void Update()
    {
        _timer += Time.deltaTime;
        if (_timer >= INTERVAL) { _timer = 0f; LogInteractorState(); }
    }

    void CheckCanvas(Canvas canvas)
    {
        Debug.Log($"[CANVAS] '{canvas.gameObject.name}' | RenderMode: {canvas.renderMode}");

        if (canvas.renderMode != RenderMode.WorldSpace)
            Debug.LogError("[CANVAS] PROBLEMA: Canvas NO esta en World Space!");
        else
            Debug.Log("[CANVAS] Render Mode = World Space. OK");

        if (canvas.GetComponent<TrackedDeviceGraphicRaycaster>() == null)
            Debug.LogError("[CANVAS] PROBLEMA: Falta TrackedDeviceGraphicRaycaster!");
        else
            Debug.Log("[CANVAS] TrackedDeviceGraphicRaycaster OK");

        var buttons = canvas.GetComponentsInChildren<UnityEngine.UI.Button>();
        Debug.Log($"[CANVAS] Botones encontrados: {buttons.Length}");
        foreach (var btn in buttons)
        {
            if (btn.GetComponent<Collider>() == null)
                Debug.LogWarning($"[BOTON] '{btn.gameObject.name}' NO tiene Collider. Necesario para Near interaction.");
            else
                Debug.Log($"[BOTON] '{btn.gameObject.name}' tiene Collider. OK");
        }
    }

    void CheckInteractor(XRBaseInteractor interactor, string side)
    {
        if (interactor == null)
        {
            Debug.LogError($"[{side} INTERACTOR] NO ENCONTRADO!");
            return;
        }

        Debug.Log($"[{side} INTERACTOR] '{interactor.gameObject.name}' | Enabled: {interactor.enabled} | Active: {interactor.gameObject.activeSelf}");

        var nearFar = interactor as NearFarInteractor;
        if (nearFar != null)
        {
            Debug.Log($"[{side}] Tipo NearFarInteractor | " +
                      $"NearCasting: {nearFar.enableNearCasting} | " +
                      $"FarCasting: {nearFar.enableFarCasting}");
        }

        var lr = interactor.GetComponentInChildren<LineRenderer>();
        if (lr == null)
            Debug.LogWarning($"[{side}] No se encontro LineRenderer en hijos.");
        else
            Debug.Log($"[{side}] LineRenderer | Enabled: {lr.enabled} | Material: {(lr.material != null ? lr.material.name : "NULL")}");
    }

    void LogInteractorState()
    {
        LogState(leftInteractor,  "LEFT");
        LogState(rightInteractor, "RIGHT");
    }

    void LogState(XRBaseInteractor interactor, string side)
    {
        if (interactor == null) return;

        var hovers  = new List<string>();
        var selects = new List<string>();

        foreach (var h in interactor.interactablesHovered)  hovers.Add(h.transform.gameObject.name);
        foreach (var s in interactor.interactablesSelected) selects.Add(s.transform.gameObject.name);

        string hStr = hovers.Count  > 0 ? string.Join(", ", hovers)  : "ninguno";
        string sStr = selects.Count > 0 ? string.Join(", ", selects) : "ninguno";

        Debug.Log($"[{side}] Hover: {hStr} | Select: {sStr}");
    }
}
