#!/usr/bin/env bash
# Stop. «Antes de dar algo por terminado» (tickets/CLAUDE.md §10) como puerta.
# Lint sobre lo que CAMBIÓ en el árbol de los cuatro repos — no solo lo editado con
# Edit/Write, porque en modo auto se edita con sed y heredocs y eso no pasa por PostToolUse.
# php -l falla -> exit 2 (bloquea; el harness cede tras 8 bloqueos). Blade -> solo avisa.
set -uo pipefail
# Bitácora para poder podar: qué hook, en qué proyecto, con qué resultado. Sin esto,
# «si en un mes no disparó, se revisa» no se puede aplicar porque nadie lo sabe.
bitacora(){ printf '%s | %-22s | %-32s | %s\n' "$(date '+%F %T')" "$1" "$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")" "$2" >> "$HOME/.claude/metodo-claudio.log" 2>/dev/null || true; }
IN="$(cat)"
# evitar bucle: si ya estamos dentro de un Stop bloqueado, no volver a bloquear
[ "$(jq -r '.stop_hook_active // false' <<<"$IN")" = "true" ] && exit 0
BASE="${CLAUDE_PROJECT_DIR:-$(jq -r ".cwd // \".\"" <<<"$IN")}"
sid="$(jq -r ".session_id // \"sin-sesion\"" <<<"$IN")"; marca="/tmp/lint-marca-${sid}"
# Sin marca (sesión anterior al hook): solo lo tocado en los últimos 30 minutos.
[ -f "$marca" ] || { marca="$(mktemp)"; touch -d "30 minutes ago" "$marca"; }
# Repos: el proyecto si es repo, o los repos anidados a un nivel (caso tickets/{backend,crm,...}).
repos="$( [ -d "$BASE/.git" ] && echo "$BASE" || find "$BASE" -mindepth 2 -maxdepth 2 -name .git -type d -printf "%h\n" )"
errores=""; avisos=""
for d in $repos; do
  # sucio en git Y modificado desde que arrancó la sesión: lo que cambió aquí, no lo de hace días
  cambiados="$( (git -C "$d" diff --name-only HEAD; git -C "$d" ls-files --others --exclude-standard) 2>/dev/null | sort -u )"
  [ -n "$cambiados" ] || continue
  while IFS= read -r rel; do
    f="$d/$rel"; [ -f "$f" ] || continue
    [ "$f" -nt "$marca" ] || continue
    case "$f" in
      *.php) out="$(php -l "$f" 2>&1)" || errores="$errores"$'\n'"$out" ;;
    esac
    case "$f" in
      *.blade.php|*/database/migrations/*.php)
        a="$(jq -n --arg p "$f" '{tool_input:{file_path:$p}}' | "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/blade-trampas.sh" | jq -r '.systemMessage // empty')"
        [ -n "$a" ] && avisos="$avisos"$'\n'"$a" ;;
    esac
  done <<<"$cambiados"
done
if [ -n "$errores" ]; then
  echo "No se da por terminado: php -l falla en archivos cambiados:$errores" >&2; bitacora stop-lint "BLOQUEO php -l"; exit 2
fi
if [ -n "$avisos" ]; then
  bitacora stop-lint "AVISO trampas"
  jq -n --arg m "Avisos de trampas en archivos cambiados (no bloquean):$avisos" '{systemMessage: $m}'
else
  bitacora stop-lint "ok"
fi
exit 0
