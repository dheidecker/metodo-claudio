#!/usr/bin/env bash
# Paridad: plantilla-proyecto/.claude/hooks/blade-trampas.sh (original) contra mecanismo/hooks/trampas
# con tests/fixtures/blade/blade.yml. Compara listas (archivo, línea, id) sobre:
#   - los fixtures sin seguimiento (los dos miran el archivo entero), y
#   - un blade y una migración CON seguimiento y ≤3 aciertos por trampa (los dos miran solo lo cambiado).
# Luego mide 20 invocaciones del hook: cada una tiene que tardar < 300 ms.
# Diferencias intencionales (no entran en los fixtures; tienen su test en test_a_motor.py):
#   - el original corta a 3 aciertos ANTES de filtrar líneas cambiadas; el contrato cuenta `max` después.
#   - el awk de wire:model «consume» el bloque con una línea que tiene wire:model=" y .live a la vez;
#     en el contrato esa línea solo no cuenta (`excepto`) y el bloque sigue abierto.
# Nunca toca el ~/.claude real: HOME, CLAUDE_HOME, MECANISMO_HOME y MECANISMO_BITACORA van a un tmp.
set -euo pipefail
AQUI="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
MEC="$(dirname "$AQUI")"; REPO="$(dirname "$MEC")"
ORIG="$REPO/plantilla-proyecto/.claude/hooks/blade-trampas.sh"
HOOK="$MEC/hooks/trampas"
FIX="$AQUI/fixtures/blade"
command -v jq >/dev/null || { echo "falta jq: el original lo necesita" >&2; exit 2; }
[ -f "$ORIG" ] || { echo "no está el original: $ORIG" >&2; exit 2; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export HOME="$T/home" CLAUDE_HOME="$T/home/.claude" MECANISMO_HOME="$T/mecanismo" \
       MECANISMO_BITACORA="$T/home/.claude/metodo-claudio.log"
unset CLAUDE_PROJECT_DIR
mkdir -p "$HOME/.claude"

# Proyecto de prueba: un repo git con los fixtures sin seguimiento y las trampas en .claude/trampas.
P="$T/proyecto"; mkdir -p "$P/.claude/trampas"
cp -r "$FIX/." "$P/"; rm -rf "$P/seguido" "$P/blade.yml"
cp "$FIX/blade.yml" "$P/.claude/trampas/blade.yml"
g(){ git -C "$P" -c user.email=t@t -c user.name=t -c commit.gpgsign=false "$@"; }
g init -q
SB="$P/resources/views/seguido.blade.php"; SM="$P/database/migrations/2026_02_01_000000_seguido.php"
cp "$FIX/seguido/base.blade.php" "$SB"; cp "$FIX/seguido/base_migracion.php" "$SM"
g add "$SB" "$SM"; g commit -qm base
cp "$FIX/seguido/cambiado.blade.php" "$SB"; cp "$FIX/seguido/cambiado_migracion.php" "$SM"

entrada(){ jq -nc --arg p "$1" --arg c "$P" '{tool_input:{file_path:$p}, cwd:$c}'; }

original(){ # rel -> líneas "rel:N:id" según el texto del original (no imprime ids: se mapean por prefijo)
  entrada "$P/$1" | (cd "$P" && bash "$ORIG") | jq -r '.systemMessage // empty' | while IFS= read -r l; do
    case "$l" in
      "- x-init con bloque"*) id=x-init-con-bloque ;;
      "- x-show junto a d-flex"*) id=x-show-con-d-flex ;;
      "- directiva Blade o <script>"*) id=directiva-en-comentario-js ;;
      "- select/checkbox con wire:model"*) id=wire-model-sin-live ;;
      "- ->timestamp() sin nullable()"*) id=timestamp-sin-nullable ;;
      "- "*) echo "prefijo desconocido: $l" >&2; exit 3 ;;
      *) continue ;;
    esac
    sed -E 's/.*\(líneas ([0-9,]+)\).*/\1/' <<<"$l" | tr ',' '\n' | sed "s|^|$1:|; s|\$|:$id|"
  done
}

nuevo(){ # rel -> "rel:N:id" según el systemMessage (o stderr, si bloquea) del hook de mecanismo
  local out rc=0
  out="$(entrada "$P/$1" | (cd "$P" && python3 "$HOOK") 2>&1)" || rc=$?
  [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ] || { echo "hook salió con $rc en $1" >&2; exit 3; }
  { jq -r '.systemMessage // empty' <<<"$out" 2>/dev/null || printf '%s\n' "$out"; } |
    sed -nE 's/^- ([a-z0-9-]+)( \[bloqueo\])? \(líneas ([0-9,]+)\):.*/\1 \3/p' |
    while read -r id ns; do tr ',' '\n' <<<"$ns" | sed "s|^|$1:|; s|\$|:$id|"; done
}

archivos="$(cd "$P" && find . -path ./.git -prune -o -path ./.claude -prune -o -type f -print | sed 's|^\./||' | sort)"
: >"$T/orig"; : >"$T/nuevo"; n=0
while IFS= read -r rel; do
  original "$rel" >>"$T/orig"; nuevo "$rel" >>"$T/nuevo"; n=$((n+1))
done <<<"$archivos"
sort -t: -k1,1 -k3,3 -k2,2n -o "$T/orig" "$T/orig"; sort -t: -k1,1 -k3,3 -k2,2n -o "$T/nuevo" "$T/nuevo"
seguidos="$(grep -c 'seguido' "$T/orig" || true)"
if ! diff -u --label original --label mecanismo "$T/orig" "$T/nuevo"; then
  echo "PARIDAD FALLA: el original y mecanismo difieren (arriba)"; exit 1
fi
[ -s "$T/orig" ] || { echo "PARIDAD VACÍA: ningún acierto, los fixtures no prueban nada"; exit 1; }
for id in x-init-con-bloque x-show-con-d-flex directiva-en-comentario-js wire-model-sin-live timestamp-sin-nullable; do
  grep -q ":$id\$" "$T/orig" || { echo "PARIDAD INCOMPLETA: ningún fixture dispara $id"; exit 1; }
done
echo "paridad ok: $n archivos, $(wc -l <"$T/orig") aciertos idénticos ($seguidos en archivos con seguimiento)"

# Tiempo: 20 invocaciones del hook sobre el blade con seguimiento (el caso con más llamadas a git).
max=0; suma=0
for _ in $(seq 20); do
  t0=$(date +%s%N); entrada "$SB" | (cd "$P" && python3 "$HOOK") >/dev/null 2>&1 || true; t1=$(date +%s%N)
  ms=$(( (t1 - t0) / 1000000 )); suma=$((suma + ms)); [ "$ms" -gt "$max" ] && max=$ms
done
echo "tiempo hook: 20 invocaciones, máx ${max} ms, media $((suma / 20)) ms (límite 300 ms)"
[ "$max" -lt 300 ] || { echo "LENTO: alguna invocación pasó de 300 ms"; exit 1; }
echo "migracion_blade: OK"
