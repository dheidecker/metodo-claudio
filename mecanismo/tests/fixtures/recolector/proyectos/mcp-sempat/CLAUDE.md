# Servidor de ejemplo (inventado)

## Cómo se prueba

- **Esto no cuenta**: no está bajo Trampas.

## Trampas del propio servidor

- **Golden: empates.** Con valores iguales el orden es arbitrario y el comparador
  es posicional, así que un empate sale como diferencia.
- **Fechas en UTC.** El corte se calcula en UTC; la conexión de ejemplo
  postgres://app:CANARIO-pass@db.interno:5432/demo no se usa.
- **Nunca `fmt.Errorf` con `%v` sobre err**: pierde la cadena de errores.

## Despliegue

Nada.
