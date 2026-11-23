#!/usr/bin/env bash
# Shim de mecanismo: Stop. Puerta de evidencia (.claude/evidencia/): avisa —o bloquea, si
# .claude/mecanismo.yml dice `puerta: bloqueo`— cuando lo cambiado no tiene evidencia vigente.
# Sin `mecanismo` en esta máquina sale en silencio, cero fricción.
command -v mecanismo >/dev/null 2>&1 || exit 0
exec mecanismo hook stop-evidencia
