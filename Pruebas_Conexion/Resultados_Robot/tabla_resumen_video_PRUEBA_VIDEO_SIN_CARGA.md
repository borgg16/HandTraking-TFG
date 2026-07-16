# Tabla Resumen de Latencia y Calidad de Vídeo (TFG)

| Condición | N Bruto | N Efectivo | Media | Mediana | P95 | P99 | Máx | Desv.Est | Jitter | FPS Efec. | Pérdida % |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| SIN_CARGA | 8561 | 8412 | 5.4 ms | 4.5 ms | 17.6 ms | 29.7 ms | 129.9 ms | 7.4 ms | 7.4 ms | 29.8 fps | 0.00% |

---
*Nota: Se ha excluido una fase de calentamiento inicial de 5.0s en cada condición/archivo.*
*Jitter calculado según RFC 3550 como la media de las diferencias absolutas de latencia consecutivas.*
*Pérdida % estimada a partir de los saltos de tiempo en la captura de frames (gaps > 50ms, asumiendo 30 fps nominales).*
