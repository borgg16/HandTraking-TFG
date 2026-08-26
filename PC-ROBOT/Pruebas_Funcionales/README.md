# Pruebas Funcionales del TFG — Teleoperación Robótica XR

Suite integral de scripts, módulos de registro y herramientas de análisis estadístico para la evaluación experimental y validación cinemática del sistema de teleoperación del brazo robótico **RoArm-M2** mediante **WebRTC** y **Unity XR**.

---

## 1. Estructura del Módulo `Pruebas_Funcionales`

```
PC-ROBOT/Pruebas_Funcionales/
├── captura/
│   ├── reticulo_overlay.py       # (1) Lanzador con retículo de montaje P0.6
│   └── captura_16_9.py           # (2) Lanzador en 16:9 nativo (1280x720 -> 640x360)
├── movimiento/
│   ├── script_rejilla.py         # (3) Barrido espacial 2D/3D por UART (P0.3 / P0.3b)
│   └── script_repetibilidad.py   # (4) Repetibilidad mecánica multi-ángulo P0.7
├── registro/
│   └── csv_funcional.py          # (5) Módulo de persistencia RegistradorFuncional (P2)
├── analisis/
│   ├── analisis_latencia_m1.py   # (6) Detección de latencia de control por visión
│   ├── contador_correcciones.py  # (7) Análisis de derivadas y correcciones M4
│   └── analisis_estadistico_p7.py# (8) Contrastes no paramétricos, curvas e informe
├── resultados/                   # Directorio de salida de datos (CSV, PNG, MD)
├── INSTALAR_DEPENDENCIAS.txt     # Guía pip install para el venv del robot
└── README.md                     # Manual operativo y documentación
```

## 2. Condiciones de Red y Configuración Estándar de Clumsy

Para garantizar la reproducibilidad científica en las pruebas funcionales (M1–M4), se establecen los siguientes parámetros oficiales de emulación de red mediante **Clumsy**:

* **Filtro de Clumsy (Filter):**
  ```text
  ip.DstAddr == 192.168.3.5 or ip.SrcAddr == 192.168.3.5
  ```

| Condición Experimental | Estado Clumsy | Configuración Clumsy | Escenario Simulado |
|---|:---:|---|---|
| **`C1_SIN_CARGA`** / `C1_WIFI_SIN_CARGA` | 🛑 **STOP** | Sin degradación (0 ms, 0% drop) | Red limpia de referencia basal. |
| **`C2_CARGA_MEDIA`** / `C2_WIFI_CARGA_MEDIA` | ▶️ **START** | • **Lag:** `10 ms`<br>• **Drop:** `2.0%` | Tráfico concurrente moderado. |
| **`C3_CARGA_ALTA`** / `C3_WIFI_CARGA_ALTA` | ▶️ **START** | • **Lag:** `15 ms`<br>• **Drop:** `5.0%` | Congestión severa de canal. |
| **`C4_ETHERNET`** | 🛑 **STOP** | Enlace cableado directo | Latencia mínima teórica. |

---

## 3. Guía de Ejecución de los Scripts

### 2.1 Captura y Calibración de Cámara (*Eye-in-Hand*)

#### 1. Retículo de Montaje (Fase P0.6)
Superpone una cruz verde centrada y líneas de guía amarillas (mordazas a 50% de altura, línea de mesa a 86%):
```powershell
python PC-ROBOT/Pruebas_Funcionales/captura/reticulo_overlay.py COM9 --ip 192.168.3.28
```

#### 2. Modo 16:9 Opcional
Captura a 1280×720 (aprovechando el FOV nativo 69°×42° del sensor D415) y reescala a 640×360:
```powershell
python PC-ROBOT/Pruebas_Funcionales/captura/captura_16_9.py COM9 --ip 192.168.3.28
```

---

### 2.2 Validación Cinemática por UART (Sin Unity / Gafas)

#### 3. Barrido de Rejilla (Fases P0.3 y P0.3b)
Recorre una cuadrícula de coordenadas espaciales con interpolación suave para verificar área alcanzable y ausencia de colisiones:
```powershell
# Modo interactivo con confirmación manual (recomendado para verificación física inicial):
python PC-ROBOT/Pruebas_Funcionales/movimiento/script_rejilla.py --puerto COM9

# Modo automático:
python PC-ROBOT/Pruebas_Funcionales/movimiento/script_rejilla.py --puerto COM9 --modo-automatico --pausa-auto 1.5
```
*Genera:* `resultados/rejilla_<timestamp>.csv`

#### 4. Repetibilidad Mecánica sin Operador (Fase P0.7)
Comanda 30 ciclos hacia una diana fija aproximándose desde 8 cuadrantes deterministas:
```powershell
python PC-ROBOT/Pruebas_Funcionales/movimiento/script_repetibilidad.py --puerto COM9 --n-repeticiones 30
```
*Genera:* `resultados/repetibilidad_p07_<timestamp>.csv`

---

### 2.3 Procesamiento de Datos y Análisis Estadístico

#### 6. Análisis de Latencia de Control M1
Calcula el retardo entre el inicio de movimiento de la mano y la respuesta del robot:
```powershell
# Vídeo individual:
python PC-ROBOT/Pruebas_Funcionales/analisis/analisis_latencia_m1.py --video video_intento1.mp4 --condicion C1_WIFI_SIN_CARGA

# Procesamiento por lotes:
python PC-ROBOT/Pruebas_Funcionales/analisis/analisis_latencia_m1.py --carpeta-videos ./grabaciones_c1/ --condicion C1_WIFI_SIN_CARGA
```
*Genera:* `resultados/latencia_m1_<condicion>.csv`

#### 7. Contador de Correcciones de Trayectoria (Fase M4)
Extrae los cambios de signo en la derivada del eje dominante de movimiento:
```powershell
python PC-ROBOT/Pruebas_Funcionales/analisis/contador_correcciones.py --csv-funcional resultados/funcional_C1_WIFI_SIN_CARGA_OP1_xxx.csv --todos
```
*Genera:* `resultados/correcciones_m4.csv`

#### 8. Análisis Estadístico Global e Informe P7
Calcula Kruskal-Wallis, Mann-Whitney U + corrección Bonferroni con tamaño de efecto $r$, Wilcoxon, curvas de aprendizaje y reporte Markdown:
```powershell
python PC-ROBOT/Pruebas_Funcionales/analisis/analisis_estadistico_p7.py
```
*Genera:* `resultados/informe_p7_<timestamp>.md`, `tabla_resumen_p7.csv`, `grafico_correlacion_g2g_m4.png` y `curva_aprendizaje_m4.png`.

---

## 3. Estructura de los Ficheros CSV

### `funcional_<condicion>_<operador>_<timestamp>.csv`
| Columna | Descripción |
|---|---|
| `t_unity_captura` | Epoch (ms) de captura en Unity XR Hands |
| `norm_x, norm_y, norm_z, g` | Vector de control normalizado [0, 1] |
| `t_unity_envio` | Epoch (ms) de transmisión desde Unity |
| `t_robot_recepcion` | Epoch (ms) de recepción en el bucle asyncio |
| `x_cm, y_cm, z_cm` | Coordenadas cartesianas tras desnormalización y clamp |
| `t_rad` | Ángulo de pinza en radianes |
| `t_uart_escritura` | Epoch (ms) inmediatamente antes de `ser.write()` |
| `clamp_activo` | Booleano (`True` si algún eje excedió los límites seguros) |
| `rtt_ms` | RTT de sincronización si está disponible |
| `perdida_pct` | Porcentaje de pérdida de paquetes |
| `id_intento, id_operador, condicion_red, nivel_objeto` | Metadatos de la prueba |

---

## 4. Integración del Registrador en `safe8_WebRTC.py` (Script 5)

Para activar el registro funcional en producción sin alterar el flujo básico, se puede añadir el módulo en `safe8_WebRTC.py` de la siguiente manera:

1. **Importar el módulo (en la cabecera):**
   ```python
   from Pruebas_Funcionales.registro.csv_funcional import RegistradorFuncional
   registrador = RegistradorFuncional()
   ```

2. **Iniciar sesión al establecer conexión DataChannel (`on_datachannel`):**
   ```python
   registrador.abrir_sesion(
       id_operador=getattr(args, "operador", "OP1"),
       condicion_red=getattr(args, "condicion", "C1_WIFI_SIN_CARGA"),
       id_intento=1
   )
   ```

3. **Registrar cada comando justo tras calcular `cmd` y enviar por UART:**
   ```python
   registrador.registrar_comando(
       norm_x=nx, norm_y=ny, norm_z=nz, g=ng,
       t_robot_recepcion=t_recibido,
       x_cm=x_f, y_cm=y_f, z_cm=z_f, t_rad=t_rad,
       t_uart_escritura=time.time()*1000.0,
       clamp_activo=clamp_aplicado
   )
   ```

4. **Cerrar sesión al desconectar:**
   ```python
   registrador.cerrar_sesion()
   ```
