#!/usr/bin/env bash
# Punto de guardado alrededor de una compactación. Un script, dos eventos:
#   PreCompact  -> qué se estaba tocando (archivos editados, últimas peticiones)
#   PostCompact -> el resumen que escribió el modelo, tal cual
# Escribe en ~/.claude/projects/<proyecto>/compactaciones/<fecha>-<sesión>.md
# Nunca bloquea: cualquier fallo sale 0 en silencio. Solo necesita jq.
set -uo pipefail
bitacora(){ printf '%s | %-22s | %-32s | %s\n' "$(date '+%F %T')" "$1" "$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")" "$2" >> "$HOME/.claude/metodo-claudio.log" 2>/dev/null || true; }
command -v jq >/dev/null || exit 0

IN="$(cat)"
evento="$(jq -r '.hook_event_name // empty' <<<"$IN")"
sesion="$(jq -r '.session_id // "sin-sesion"' <<<"$IN" | cut -c1-8)"
cwd="$(jq -r '.cwd // empty' <<<"$IN")"; [ -n "$cwd" ] || cwd="$PWD"
disparo="$(jq -r '.trigger // .matcher // "?"' <<<"$IN")"
transcript="$(jq -r '.transcript_path // empty' <<<"$IN")"

# misma clave de proyecto que usa Claude Code para ~/.claude/projects/
clave="$(sed 's#[/_.]#-#g' <<<"$cwd")"
dir="$HOME/.claude/projects/$clave/compactaciones"; mkdir -p "$dir"
out="$dir/$(date +%Y%m%d)-$sesion.md"
ahora="$(date '+%Y-%m-%d %H:%M')"

case "$evento" in
  PreCompact)
    {
      echo "# Compactación $ahora — sesión $sesion ($disparo)"
      echo; echo "Proyecto: \`$cwd\`"
      if [ -n "$transcript" ] && [ -r "$transcript" ]; then
        echo; echo "## Archivos tocados en la sesión"
        jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use")
               | select(.name=="Edit" or .name=="Write" or .name=="NotebookEdit")
               | .input.file_path // empty' "$transcript" 2>/dev/null | sort -u | sed 's/^/- /'
        echo; echo "## Últimas peticiones del usuario"
        jq -r 'select(.type=="user") | .message.content
               | if type=="string" then . else (.[]? | select(.type=="text") | .text) end' "$transcript" 2>/dev/null \
          | grep -v '^\s*$' | grep -v '^<' | grep -v -i 'another Claude session\|cross-session' | tail -n 3 | cut -c1-300 | sed 's/^/> /'
      fi
      echo
    } >> "$out"
    ;;
  PostCompact)
    {
      echo "## Resumen que quedó en la ventana ($ahora)"
      echo
      jq -r '.summary // .compact_summary // .compaction_summary // empty' <<<"$IN"
      # si el campo se llama distinto en esta versión, guarda el sobre entero sin el transcript
      if [ -z "$(jq -r '.summary // .compact_summary // .compaction_summary // empty' <<<"$IN")" ]; then
        jq 'del(.transcript_path)' <<<"$IN"
      fi
      echo
    } >> "$out"
    ;;
esac
bitacora compactacion "$evento $disparo -> $(basename "$out")"
exit 0
