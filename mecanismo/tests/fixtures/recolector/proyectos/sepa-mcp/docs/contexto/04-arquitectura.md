# 04 · Arquitectura (inventada para tests)

## 9. Reutilizable

1. Esto no es una trampa.

## 10. Trampas trasladables

1. Auditoría en dos fases; si la fila final no entra, se descarta el resultado.
2. Sin partición del mes, el INSERT falla.
7. Upsert con `SET col = EXCLUDED.col` exige SELECT sobre `col`; usar parámetros.
35. Transacción abierta durante una llamada externa: ciérrala antes de llamar al servicio.

## 11. Pendientes

Nada.
