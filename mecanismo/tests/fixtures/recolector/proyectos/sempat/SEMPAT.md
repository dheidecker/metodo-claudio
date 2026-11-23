# Proyecto de ejemplo (inventado)

## 9. Estado actual

Nada que ver aquí.

## 10. Trampas conocidas

### 10.1. Los perfiles viven en tablas separadas

`PerfilA` y `PerfilB` heredan en tablas distintas. Por lo tanto:

- `PerfilB.objects.all()` **no ve** a los de `PerfilA`.
- Las consultas generales van sobre la tabla base.

### 10.2. La caché local no es compartida

Cada proceso tiene la suya; usa la compartida.

## 11. Referencias

- **Esto no es una trampa**: está fuera de la sección.
