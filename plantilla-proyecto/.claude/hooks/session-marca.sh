#!/usr/bin/env bash
# SessionStart. Deja una marca de tiempo por sesión para que stop-lint.sh solo mire lo que
# cambió DESDE que arrancó esta sesión, y no todo lo que el usuario tiene sucio en el árbol
# (caso real: la primera versión avisaba cada turno sobre nueve Blade sucios de hace días).
bitacora(){ printf '%s | %-22s | %-32s | %s\n' "$(date '+%F %T')" "$1" "$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")" "$2" >> "$HOME/.claude/metodo-claudio.log" 2>/dev/null || true; }
sid="$(jq -r '.session_id // "sin-sesion"' 2>/dev/null)"; touch "/tmp/lint-marca-${sid}"; bitacora session-marca "inicio $sid"; exit 0
