#!/usr/bin/env bash
# PreToolUse con if: "Bash(git commit*)". Bloquea el commit si el índice trae archivos
# que suelen ser credenciales. Caso real: tres proyectos lo documentan a mano
# (.env, JSON de cuenta de servicio, xlsx con datos). Exit 2 = bloquea y explica.
set -uo pipefail
cd "$(jq -r '.cwd // "."' 2>/dev/null || echo .)" 2>/dev/null || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
sospechosos="$(git diff --cached --name-only 2>/dev/null | grep -E '(^|/)\.env(\.|$)|service-account|credential|\.pem$|\.key$|\.p12$|secrets?\.(json|ya?ml)$' || true)"
if [ -n "$sospechosos" ]; then
  echo "El índice trae archivos con pinta de credencial; no se commitea hasta que los saques:" >&2
  echo "$sospechosos" | sed 's/^/  - /' >&2
  echo "git restore --staged <archivo>   y añádelo a .gitignore si no está." >&2
  exit 2
fi
exit 0
