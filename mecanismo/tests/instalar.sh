#!/usr/bin/env bash
# Prueba de instalación (frente E). SIEMPRE con un HOME temporal: nunca toca el ~ real.
#   bash mecanismo/tests/instalar.sh
# Comprueba: dos corridas (la 2.ª «sin cambios», sin respaldos nuevos), respaldo de un
# archivo ajeno, enlace colgante rehecho, desinstalar solo quita lo suyo, sin rutas a mano,
# init idempotente y shims silenciosos sin mecanismo en el PATH.
set -uo pipefail

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
HOME_REAL="$HOME"
T="$(mktemp -d)"
export HOME="$T/home"
export CLAUDE_HOME="$HOME/.claude" MECANISMO_BITACORA="$T/bitacora.log"
unset CLAUDE_PROJECT_DIR MECANISMO_HOME
mkdir -p "$HOME"
trap 'rm -rf "$T"' EXIT

# Guardarraíl de la propia prueba: si el HOME no es el temporal, no se corre nada.
case "$HOME" in "$T"/*) ;; *) echo "ABORTO: HOME no es temporal ($HOME)"; exit 1 ;; esac
[ "$HOME" != "$HOME_REAL" ] || { echo "ABORTO: HOME real"; exit 1; }

N=0; FALLOS=0
ok()  { N=$((N+1)); echo "ok   - $1"; }
mal() { N=$((N+1)); FALLOS=$((FALLOS+1)); echo "MAL  - $1"; }
chk() { local d="$1"; shift; if "$@"; then ok "$d"; else mal "$d"; fi; }

BIN="$HOME/.local/bin/mecanismo"
ORIGEN_BIN="$REPO/mecanismo/bin/mecanismo"
baks() { find "$HOME" -name '*.bak' | wc -l; }
apunta_aqui() { [ -L "$BIN" ] && [ "$(readlink "$BIN")" = "$ORIGEN_BIN" ]; }

# --- 1. dos corridas
out1="$("$REPO/instalar.sh" 2>&1)"; rc1=$?
chk "primera corrida sale 0" test "$rc1" = 0
chk "enlace ~/.local/bin/mecanismo -> este clon" apunta_aqui
chk "~/.claude/CLAUDE.md enlazado a METODOLOGIA.md" test "$(readlink "$HOME/.claude/CLAUDE.md")" = "$REPO/METODOLOGIA.md"
chk "el jq impreso trae las reglas allow de mecanismo" grep -qF 'Bash(mecanismo trampas*)' <<<"$out1"
chk "el jq impreso trae Bash(chrome-devtools *)" grep -qF 'Bash(chrome-devtools *)' <<<"$out1"
chk "imprime el snippet del canario en los 3 eventos" bash -c 'for e in PermissionRequest PermissionDenied Notification; do grep -q "hooks.$e" <<<"$1" || exit 1; done' _ "$out1"
chk "avisa si ~/.local/bin no está en el PATH" grep -q 'no está en tu PATH' <<<"$out1"
chk "primera corrida no dice «sin cambios»" bash -c '! grep -q "sin cambios" <<<"$1"' _ "$out1"
b0="$(baks)"
out2="$("$REPO/instalar.sh" 2>&1)"; rc2=$?
chk "segunda corrida sale 0" test "$rc2" = 0
chk "segunda corrida dice «sin cambios»" grep -q 'sin cambios' <<<"$out2"
chk "segunda corrida no crea respaldos nuevos ($b0 -> $(baks))" test "$(baks)" = "$b0"

# --- 1b. los comandos jq impresos son válidos y aplican sobre un settings.json falso
if command -v jq >/dev/null; then
  echo '{"permissions":{"allow":["Bash(ls*)"]},"hooks":{"Notification":[{"hooks":[{"type":"command","command":"otro"}]}]}}' > "$HOME/.claude/settings.json"
  for linea in "jq -s" "jq 'def sin_canario"; do
    cmd="$(grep -F "  $linea" <<<"$out2" | head -1 | sed 's#/tmp/settings.new#'"$T"'/settings.new#g')"
    chk "aplica el comando «$linea…» impreso" bash -c "$cmd"
  done
  chk "allow fusionado sin perder lo previo" jq -e '(.permissions.allow | index("Bash(ls*)")) and (.permissions.allow | index("Bash(mecanismo verificar*)"))' "$HOME/.claude/settings.json" >/dev/null
  chk "canario en Notification sin pisar el hook previo" jq -e '[.hooks.Notification[].hooks[].command] == ["otro","mecanismo hook canario-permisos"]' "$HOME/.claude/settings.json" >/dev/null
  rm -f "$HOME/.claude/settings.json"
fi

# --- 2. archivo ajeno en ~/.local/bin/mecanismo: se respalda
rm "$BIN"; echo 'echo ajeno' > "$BIN"; chmod +x "$BIN"
out3="$("$REPO/instalar.sh" 2>&1)"
chk "archivo ajeno: re-enlazado aquí" apunta_aqui
chk "archivo ajeno: respaldado con su contenido" bash -c 'grep -qx "echo ajeno" "$1".*.bak' _ "$BIN"
chk "archivo ajeno: lo dice" grep -q 'había algo ajeno' <<<"$out3"

# --- 3. enlace colgante: se rehace (sin respaldo de un enlace roto)
rm "$BIN"; ln -s "$T/clon-borrado/mecanismo/bin/mecanismo" "$BIN"
b1="$(baks)"
out4="$("$REPO/instalar.sh" 2>&1)"
chk "colgante: re-enlazado aquí" apunta_aqui
chk "colgante: lo dice" grep -q 'enlace colgante' <<<"$out4"
chk "colgante: sin respaldo nuevo" test "$(baks)" = "$b1"

# --- 4. desinstalar solo quita lo suyo
"$REPO/desinstalar.sh" >/dev/null 2>&1
chk "desinstalar quita nuestro enlace" test ! -e "$BIN" -a ! -L "$BIN"
chk "desinstalar quita nuestro CLAUDE.md" test ! -e "$HOME/.claude/CLAUDE.md"
echo 'echo ajeno' > "$BIN"; ln -s /usr/bin/true "$HOME/.local/bin/otro"
out5="$("$REPO/desinstalar.sh" 2>&1)"
chk "desinstalar no toca un mecanismo ajeno" grep -qx 'echo ajeno' "$BIN"
chk "desinstalar lo dice" grep -q 'no apunta a este clon' <<<"$out5"
rm "$BIN"; ln -s "$T/otro-clon/mecanismo/bin/mecanismo" "$BIN"
"$REPO/desinstalar.sh" >/dev/null 2>&1
chk "desinstalar no toca un enlace a otro clon" test -L "$BIN"
chk "desinstalar no toca otros binarios" test -L "$HOME/.local/bin/otro"
rm -f "$BIN"

# --- 5. sin rutas a mano
rutas="$(cd "$REPO" && grep -rnIE --exclude-dir=__pycache__ '/home/[a-z]|/Users/[A-Za-z]' instalar.sh desinstalar.sh mecanismo/bin mecanismo/lib/init \
  plantilla-proyecto/.claude/hooks/mecanismo-*.sh plantilla-proyecto/.claude/hooks/stop-evidencia.sh)"
chk "grep de rutas a mano vacío" test -z "$rutas"
[ -z "$rutas" ] || echo "$rutas"

# --- 6. mecanismo init --tipo mcp dos veces
"$REPO/instalar.sh" >/dev/null 2>&1
P="$T/proyecto"; mkdir -p "$P"; git -C "$P" init -q
foto() { (cd "$P" && find . -path ./.git -prune -o -print0 | sort -z | xargs -0 stat -c '%n %a %s %Y' ; find . -path ./.git -prune -o -type f -print0 | sort -z | xargs -0 sha256sum); }
(cd "$P" && "$BIN" init --tipo mcp >/dev/null); rc=$?
chk "init --tipo mcp sale 0" test "$rc" = 0
chk "init dejó mecanismo.yml con puerta: aviso" grep -qx 'puerta: aviso' "$P/.claude/mecanismo.yml"
chk "init dejó .claude/evidencia/ en .gitignore" grep -qx '.claude/evidencia/' "$P/.gitignore"
chk "init no creó settings.json" test ! -e "$P/.claude/settings.json"
f1="$(foto)"
o="$(cd "$P" && "$BIN" init --tipo mcp)"
chk "init segunda vez: «sin cambios»" grep -q 'sin cambios' <<<"$o"
chk "init segunda vez: el árbol no cambió" test "$f1" = "$(foto)"

# --- 7. shims sin mecanismo en el PATH: exit 0 y nada impreso
for s in mecanismo-trampas.sh stop-evidencia.sh; do
  salida="$(echo '{"session_id":"x"}' | PATH=/usr/bin:/bin "$P/.claude/hooks/$s" --stop 2>&1)"; rc=$?
  chk "shim $s sin mecanismo: exit 0 y silencio" test "$rc" = 0 -a -z "$salida"
done
# ...y con mecanismo en el PATH pero sin el hook (frente aún no integrado): tampoco rompe
salida="$(echo '{}' | PATH="$HOME/.local/bin:/usr/bin:/bin" "$P/.claude/hooks/mecanismo-trampas.sh" 2>/dev/null)"; rc=$?
chk "shim con mecanismo pero sin el hook: exit 0 (rc=$rc)" test "$rc" = 0

# --- 8. bash -n
for f in "$REPO/instalar.sh" "$REPO/desinstalar.sh" "$ORIGEN_BIN" "$REPO/mecanismo/tests/instalar.sh" \
         "$REPO/plantilla-proyecto/.claude/hooks/mecanismo-trampas.sh" "$REPO/plantilla-proyecto/.claude/hooks/stop-evidencia.sh"; do
  chk "bash -n ${f#$REPO/}" bash -n "$f"
done
chk "jq . plantilla settings.json" bash -c 'jq . "$1" >/dev/null' _ "$REPO/plantilla-proyecto/.claude/settings.json"

# --- y nada de esto tocó el HOME real
chk "el ~/.local/bin/mecanismo real no apunta a la carpeta temporal" bash -c '! [[ "$(readlink "$1/.local/bin/mecanismo" 2>/dev/null)" == "$2"* ]]' _ "$HOME_REAL" "$T"

echo
if [ "$FALLOS" = 0 ]; then echo "TODO VERDE: $N comprobaciones"; else echo "FALLAN $FALLOS de $N"; exit 1; fi
