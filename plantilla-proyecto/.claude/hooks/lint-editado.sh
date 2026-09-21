#!/usr/bin/env bash
# PostToolUse sobre Edit|Write. Caso real: tickets/CLAUDE.md §10 «antes de dar algo por
# terminado: php -l en los PHP tocados, node --check si tocaste el editor de propuestas».
# Hoy eso dependía de que el modelo se acordara al final; aquí el error vuelve en el
# mismo turno en que se introdujo. Exit 2 = el modelo ve el error y corrige.
set -uo pipefail
# Bitácora para poder podar: qué hook, en qué proyecto, con qué resultado. Sin esto,
# «si en un mes no disparó, se revisa» no se puede aplicar porque nadie lo sabe.
bitacora(){ printf '%s | %-22s | %-32s | %s\n' "$(date '+%F %T')" "$1" "$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")" "$2" >> "$HOME/.claude/metodo-claudio.log" 2>/dev/null || true; }
command -v jq >/dev/null || exit 0
f="$(jq -r '.tool_input.file_path // .tool_response.filePath // empty')"
[ -n "$f" ] && [ -f "$f" ] || exit 0

case "$f" in
  *.php)
    if ! out="$(php -l "$f" 2>&1)"; then
      echo "php -l falló en $f:" >&2; echo "$out" >&2; bitacora lint-editado "BLOQUEO php -l $(basename "$f")"; exit 2
    fi ;;
  */resources/proposals/editor.html)
    # El editor se sirve crudo: un error de sintaxis JS es una página en blanco sin error.
    tmp="$(mktemp --suffix=.js)"
    # extrae el contenido de cada <script> sin src
    awk 'BEGIN{IGNORECASE=1} /<script[^>]*>/{ if ($0 !~ /src=/) {s=1; sub(/.*<script[^>]*>/,""); if ($0 !~ /<\/script>/) {print; next}} } s && /<\/script>/{sub(/<\/script>.*/,""); print; s=0; next} s{print}' "$f" > "$tmp"
    if ! out="$(node --check "$tmp" 2>&1)"; then
      rm -f "$tmp"; bitacora lint-editado "BLOQUEO node --check"; echo "node --check falló en el JS del editor de propuestas:" >&2; echo "$out" | head -20 >&2; exit 2
    fi
    rm -f "$tmp" ;;
esac
bitacora lint-editado "ok $(basename "$f")"
exit 0
