#!/usr/bin/env bash
# Shim de mecanismo: PostToolUse Edit|Write, y con --stop en Stop (trampas como datos,
# .claude/trampas/*.yml). Corre en cada edición: sin `mecanismo` en esta máquina sale
# en silencio, cero fricción. La lógica vive en metodo-claudio/mecanismo, no aquí.
command -v mecanismo >/dev/null 2>&1 || exit 0
exec mecanismo hook trampas "$@"
