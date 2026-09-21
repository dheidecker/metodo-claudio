#!/usr/bin/env bash
# SessionStart. Deja una marca de tiempo por sesión para que stop-lint.sh solo mire lo que
# cambió DESDE que arrancó esta sesión, y no todo lo que el usuario tiene sucio en el árbol
# (caso real: la primera versión avisaba cada turno sobre nueve Blade sucios de hace días).
sid="$(jq -r '.session_id // "sin-sesion"' 2>/dev/null)"; touch "/tmp/lint-marca-${sid}"; exit 0
