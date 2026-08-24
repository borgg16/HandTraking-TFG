# Red_Clasificada_M2_M3 — mapeo de sesiones

Copias renombradas y organizadas de los `red_*.csv` (RTT/jitter/pérdida exportados por Unity)
que se han podido emparejar por solapamiento de tiempos con una sesión funcional concreta de M2/M3.
Los originales SIGUEN en `Resultados_Unity/` y `Resultados_Robot/` sin tocar; esto es una copia
organizada, no un movimiento.

## M2 — Precisión de posicionado

| Condición | Archivo(s) originales | n muestras | RTT media | RTT máx |
|---|---|---|---|---|
| C1 — Ethernet sin carga | red_20260821_214242 + 215203 + 220938 | 32+70+319 | ~14.0 ms | 28.6 ms |
| C2 — Ethernet+Clumsy carga media | red_20260821_230059 | 245 | 114.7 ms | 522.8 ms |
| C3 — Ethernet+Clumsy carga alta | red_20260822_000001 | 208 | 131.0 ms | 1114.6 ms |

## M3 — Repetibilidad

| Sesión | Archivo original | n muestras | RTT media | RTT máx | Estado |
|---|---|---|---|---|---|
| Original (21-22 ago) | red_20260822_003322 | 53 | 94.5 ms | 137.6 ms | **Anómalo** — Clumsy quedó activo en segundo plano |
| Verificación previa (24 ago, 16:53, sin dianas) | red_20260824_165344 | 34 | 13.3 ms | 15.1 ms | Limpio, baseline confirmado |
| Sesión física repetida (24 ago, 17:22) | red_20260824_172232 | 94 | 14.4 ms | 42.3 ms | Limpio — coincide con el baseline de M2 C1 (~14 ms) |

La sesión física del 24 ago tuvo **2 recalibraciones** (huecos de `cmd_hz=0` en 17:24:07–17:24:22
y 17:26:32–17:27:00, que coinciden con el inicio de los 3 ficheros `funcional_C1_..._OP1_20260824_*`).
El canal de RTT (ping/pong por WebSocket) no se vio afectado por el bug de Unity investigado el
24 ago (coroutine `CrearOferta()` sin guard de reentrancia): ese bug afecta al vídeo/DataChannel de
WebRTC, no al WebSocket de señalización que lleva el RTT. Por eso los números de red siguen limpios
pese a las recalibraciones.

Nota de etiquetado: los 3 ficheros `funcional_C1_..._20260824_*.csv` estaban mal etiquetados como
`WIFI_SIN_CARGA` (plantilla antigua); corregidos a `ETHERNET_SIN_CARGA` el 24 ago 2026, igual que se
hizo antes con los de M2/M3 del 21-22 ago.
