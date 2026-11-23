#!/usr/bin/env bash
# Prueba de instalación (frente E). SIEMPRE con un HOME temporal: nunca toca el ~ real.
#   bash mecanismo/tests/instalar.sh
# Comprueba: dos corridas (la 2.ª «sin cambios», sin respaldos nuevos), respaldo de un
# archivo ajeno, enlace colgante rehecho (y respaldado si era de otra herramienta), deny
# sugerido, desinstalar solo quita lo suyo (también con un CLAUDE.md que solo importa),
# sin rutas a mano, init idempotente y shims silenciosos sin mecanismo en el PATH; y el
# recolector semanal (units de systemd --user, crontab sin systemd, --sin-recolector).
# systemctl SIEMPRE falso (MECANISMO_SYSTEMCTL): el real habla con el systemd del usuario
# aunque HOME sea temporal.
set -uo pipefail

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
HOME_REAL="$HOME"
T="$(mktemp -d -p /var/tmp)"
export HOME="$T/home"
export CLAUDE_HOME="$HOME/.claude" MECANISMO_BITACORA="$T/bitacora.log"
unset CLAUDE_PROJECT_DIR MECANISMO_HOME
mkdir -p "$HOME"
trap 'rm -rf "$T"' EXIT

# systemctl falso: anota cada llamada en $T/systemctl.log. Sin $T/sin-systemd responde como
# un systemd de usuario vivo; is-enabled mira $T/timer-activo (enable lo crea, disable lo borra).
mkdir -p "$T/falsos"
cat > "$T/falsos/systemctl" <<FALSO
#!/usr/bin/env bash
echo "\$*" >> "$T/systemctl.log"
[ ! -e "$T/sin-systemd" ] || exit 1
case "\$*" in
  *" enable "*) touch "$T/timer-activo" ;;
  *" disable "*) rm -f "$T/timer-activo" ;;
  *" is-enabled "*) [ -e "$T/timer-activo" ] || exit 1 ;;
esac
exit 0
FALSO
chmod +x "$T/falsos/systemctl"
export MECANISMO_SYSTEMCTL="$T/falsos/systemctl"
SYSD_REAL="$HOME_REAL/.config/systemd/user"
foto_sysd() { find "$SYSD_REAL" -printf '%p %T@ %s\n' 2>/dev/null | sort; }
SYSD_ANTES="$(foto_sysd)"

# Guardarraíl de la propia prueba: si el HOME no es el temporal, no se corre nada.
case "$HOME" in "$T"/*) ;; *) echo "ABORTO: HOME no es temporal ($HOME)"; exit 1 ;; esac
[ "$HOME" != "$HOME_REAL" ] || { echo "ABORTO: HOME real"; exit 1; }
case "$MECANISMO_SYSTEMCTL" in "$T"/*) ;; *) echo "ABORTO: systemctl no es el falso"; exit 1 ;; esac

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
for d in 'Bash(mecanismo aprobar*)' 'Bash(mecanismo rechazar*)' 'Bash(mecanismo confiar*)' 'Bash(script *)'; do
  chk "el jq impreso trae el deny $d" grep -qF "$d" <<<"$(grep -F '  jq -s' <<<"$out1")"
done
chk "explica que el deny es la frontera contra la auto-aprobación" grep -q 'frontera real.*§11' <<<"$out1"
chk "--help lista confiar" bash -c '"$1" --help | grep -q "^  confiar "' _ "$BIN"
chk "imprime el snippet del canario en los 3 eventos" bash -c 'for e in PermissionRequest PermissionDenied Notification; do grep -q "hooks.$e" <<<"$1" || exit 1; done' _ "$out1"
chk "imprime el snippet del juez (PermissionRequest, matcher Bash, timeout 90)" bash -c 'grep -F "jq '"'"'.hooks.PermissionRequest" <<<"$1" | grep -F "\"matcher\": \"Bash\"" | grep -F "mecanismo hook juez-permisos" | grep -qF "\"timeout\": 90"' _ "$out1"
chk "explica que las reglas ask de deploy y rm -rf se mantienen" grep -q 'gcloud run jobs execute y rm -rf se mantienen' <<<"$out1"
chk "--help lista juez" bash -c '"$1" --help | grep -q "^  juez "' _ "$BIN"
chk "avisa si ~/.local/bin no está en el PATH" grep -q 'no está en tu PATH' <<<"$out1"
chk "primera corrida no dice «sin cambios»" bash -c '! grep -q "sin cambios" <<<"$1"' _ "$out1"
b0="$(baks)"
out2="$("$REPO/instalar.sh" 2>&1)"; rc2=$?
chk "segunda corrida sale 0" test "$rc2" = 0
chk "segunda corrida dice «sin cambios»" grep -q 'sin cambios' <<<"$out2"
chk "segunda corrida no crea respaldos nuevos ($b0 -> $(baks))" test "$(baks)" = "$b0"

# --- 1b. los comandos jq impresos son válidos y aplican sobre un settings.json falso
if command -v jq >/dev/null; then
  # jq -e callado aquí dentro: un `>/dev/null` al final de la línea de chk se tragaba el ok/MAL.
  jqe() { jq -e "$@" >/dev/null; }
  echo '{"permissions":{"allow":["Bash(ls*)"]},"hooks":{"Notification":[{"hooks":[{"type":"command","command":"otro"}]}]}}' > "$HOME/.claude/settings.json"
  for linea in "jq -s" "jq 'def sin_canario" "jq '.hooks.PermissionRequest"; do
    cmd="$(grep -F "  $linea" <<<"$out2" | head -1 | sed 's#/tmp/settings.new#'"$T"'/settings.new#g')"
    chk "aplica el comando «$linea…» impreso" bash -c "$cmd"
  done
  chk "deny fusionado con los 4 de mecanismo y los de guardarrailes" jqe --slurpfile g "$REPO/guardarrailes.json" '.permissions.deny as $d | (["Bash(mecanismo aprobar*)","Bash(mecanismo rechazar*)","Bash(mecanismo confiar*)","Bash(script *)"] + ($g[0].permissions.deny // [])) | all(. as $x | $d | index([$x]))' "$HOME/.claude/settings.json"
  chk "allow fusionado sin perder lo previo" jqe '(.permissions.allow | index("Bash(ls*)")) and (.permissions.allow | index("Bash(mecanismo verificar*)"))' "$HOME/.claude/settings.json"
  chk "juez en PermissionRequest junto al canario" jqe '[.hooks.PermissionRequest[] | {m: .matcher, c: .hooks[0].command, t: .hooks[0].timeout}] == [{m: null, c: "mecanismo hook canario-permisos", t: 5}, {m: "Bash", c: "mecanismo hook juez-permisos", t: 90}]' "$HOME/.claude/settings.json"
  cmd="$(grep -F "  jq '.hooks.PermissionRequest" <<<"$out2" | head -1 | sed 's#/tmp/settings.new#'"$T"'/settings.new#g')"
  bash -c "$cmd"
  chk "aplicar el juez dos veces no lo duplica" jqe '[.hooks.PermissionRequest[].hooks[].command | select(test("juez"))] | length == 1' "$HOME/.claude/settings.json"
  chk "canario en Notification sin pisar el hook previo" jqe '[.hooks.Notification[].hooks[].command] == ["otro","mecanismo hook canario-permisos"]' "$HOME/.claude/settings.json"
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

# --- 3b. colgante a OTRA herramienta (no */mecanismo/bin/mecanismo): se respalda, no se borra
rm "$BIN"; ln -s "$T/otra-herramienta/bin/mec" "$BIN"
out4b="$("$REPO/instalar.sh" 2>&1)"
chk "colgante ajeno: re-enlazado aquí" apunta_aqui
chk "colgante ajeno: respaldado como enlace con su destino" bash -c 'for b in "$1".*.bak; do [ -L "$b" ] && [ "$(readlink "$b")" = "$2" ] && exit 0; done; exit 1' _ "$BIN" "$T/otra-herramienta/bin/mec"
chk "colgante ajeno: lo dice como ajeno" grep -q 'había algo ajeno' <<<"$out4b"
rm -f "$BIN".*.bak

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

# --- 4b. CLAUDE.md con solo nuestra importación (o con la cabecera y blancos): se retira entero
for variante in solo cabecera; do
  "$REPO/instalar.sh" >/dev/null 2>&1
  rm -f "$HOME/.claude/CLAUDE.md"
  if [ "$variante" = solo ]; then
    printf '%s\n' "@$REPO/METODOLOGIA.md" > "$HOME/.claude/CLAUDE.md"
  else
    printf '\n\n# Metodología compartida (metodo-claudio)\n%s\n\n' "@$REPO/METODOLOGIA.md" > "$HOME/.claude/CLAUDE.md"
  fi
  rm -f "$HOME/.claude/CLAUDE.md".*.bak
  out6="$("$REPO/desinstalar.sh" 2>&1)"; rc=$?
  chk "[$variante] desinstalar sale 0 (rc=$rc)" test "$rc" = 0
  chk "[$variante] no queda CLAUDE.md.tmp" test ! -e "$HOME/.claude/CLAUDE.md.tmp"
  chk "[$variante] CLAUDE.md retirado" test ! -e "$HOME/.claude/CLAUDE.md"
  chk "[$variante] CLAUDE.md respaldado con la importación" bash -c 'grep -qxF "$2" "$1".*.bak' _ "$HOME/.claude/CLAUDE.md" "@$REPO/METODOLOGIA.md"
  chk "[$variante] enlace de mecanismo quitado" test ! -e "$BIN" -a ! -L "$BIN"
  chk "[$variante] lo dice" grep -q 'importación quitada' <<<"$out6"
  rm -f "$HOME/.claude/CLAUDE.md".*.bak
done
# ...y con reglas propias: se conservan, sin la cabecera ni la importación
"$REPO/instalar.sh" >/dev/null 2>&1
rm -f "$HOME/.claude/CLAUDE.md"; printf '# mis reglas\nno toques prod\n' > "$HOME/.claude/CLAUDE.md"
"$REPO/instalar.sh" >/dev/null 2>&1
"$REPO/desinstalar.sh" >/dev/null 2>&1; rc=$?
chk "reglas propias: desinstalar sale 0" test "$rc" = 0
chk "reglas propias: quedan exactas" test "$(cat "$HOME/.claude/CLAUDE.md")" = $'# mis reglas\nno toques prod'
chk "reglas propias: no queda .tmp" test ! -e "$HOME/.claude/CLAUDE.md.tmp"
rm -f "$HOME/.claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md".*.bak

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

# --- 9. recolector semanal (HOME propio para no arrastrar lo de arriba)
export HOME="$T/home-rec"; mkdir -p "$HOME"
U="$HOME/.config/systemd/user"; SRV="$U/mecanismo-recolectar.service"; TIM="$U/mecanismo-recolectar.timer"
LOGS="$T/systemctl.log"; REC="$REPO/mecanismo/bin/recolectar-semanal"
llamadas() { cat "$LOGS" 2>/dev/null | grep -c -- "$1"; }
reset_sysd() { rm -rf "$HOME" "$LOGS" "$T/timer-activo" "$T/sin-systemd"; mkdir -p "$HOME"; }
TIMER_ESPERADO='[Unit]
Description=mecanismo: recolector cada domingo 12:00

[Timer]
OnCalendar=Sun *-*-* 12:00:00
Persistent=false
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target'

# 9.1 con systemd: escribe las units y activa el timer
reset_sysd
o="$("$REPO/instalar.sh" 2>&1)"; rc=$?
chk "recolector: sale 0" test "$rc" = 0
chk "recolector: ExecStart al bin de este clon" grep -qxF "ExecStart=$REC" "$SRV"
chk "recolector: service oneshot con TimeoutStartSec=30min" bash -c 'grep -qx "Type=oneshot" "$1" && grep -qx "TimeoutStartSec=30min" "$1"' _ "$SRV"
chk "recolector: timer idéntico a la referencia (domingo 12:00, Persistent=false)" test "$(cat "$TIM")" = "$TIMER_ESPERADO"
chk "recolector: daemon-reload" grep -qx -- '--user daemon-reload' "$LOGS"
chk "recolector: enable --now del timer" grep -qx -- '--user enable --now mecanismo-recolectar.timer' "$LOGS"
chk "recolector: dice qué corre, cuándo y el coste" bash -c 'grep -F "programado (systemd --user)" <<<"$1" | grep -F "domingo 12:00" | grep -qF "≤1 USD (normalmente ~0,15)"' _ "$o"
chk "recolector: dice cómo desactivarlo" grep -qF 'systemctl --user disable --now mecanismo-recolectar.timer' <<<"$o"

# 9.2 segunda corrida: «sin cambios», sin volver a llamar a enable
en0="$(llamadas ' enable ')"; f0="$(stat -c %Y "$SRV" "$TIM")"
o="$("$REPO/instalar.sh" 2>&1)"
chk "recolector 2.ª: «sin cambios»" grep -q 'sin cambios' <<<"$o"
chk "recolector 2.ª: no vuelve a llamar a enable ($en0 -> $(llamadas ' enable '))" test "$(llamadas ' enable ')" = "$en0"
chk "recolector 2.ª: units sin reescribir" test "$(stat -c %Y "$SRV" "$TIM")" = "$f0"
chk "recolector 2.ª: dice «ya programado»" grep -q 'ya programado' <<<"$o"

# 9.3 el usuario lo desactivó: no se reactiva
"$MECANISMO_SYSTEMCTL" --user disable --now mecanismo-recolectar.timer
o="$("$REPO/instalar.sh" 2>&1)"
chk "desactivado a mano: no llama a enable" test "$(llamadas ' enable ')" = "$en0"
chk "desactivado a mano: lo dice" grep -q 'no se reactiva' <<<"$o"

# 9.4 units viejas a mano (como las de hoy): se reescriben, con respaldo
reset_sysd; mkdir -p "$U"
printf '[Unit]\nDescription=mecanismo: recolector semanal de propuestas (metodo-claudio)\n\n[Service]\nType=oneshot\nExecStart=%%h/.claude/mecanismo/recolectar-semanal.sh\nTimeoutStartSec=30min\n' > "$SRV"
printf '%s\n' "$TIMER_ESPERADO" > "$TIM"
o="$("$REPO/instalar.sh" 2>&1)"
chk "units a mano: ExecStart reescrito" grep -qxF "ExecStart=$REC" "$SRV"
chk "units a mano: lo dice" grep -q 'mecanismo-recolectar.service era distinto: reescrito' <<<"$o"
chk "units a mano: respaldo del service viejo" bash -c 'grep -qF "%h/.claude/mecanismo/recolectar-semanal.sh" "$1".*.bak' _ "$SRV"
chk "units a mano: el timer igual no se toca" test ! -e "$(ls "$TIM".*.bak 2>/dev/null | head -1)"
chk "units a mano: enable --now" grep -qx -- '--user enable --now mecanismo-recolectar.timer' "$LOGS"
chk "units a mano: no dice «sin cambios»" bash -c '! grep -q "sin cambios" <<<"$1"' _ "$o"

# 9.5 sin systemd de usuario: imprime la línea de crontab y no escribe units
reset_sysd; touch "$T/sin-systemd"
o="$("$REPO/instalar.sh" 2>&1)"; rc=$?
chk "sin systemd: sale 0" test "$rc" = 0
chk "sin systemd: imprime la línea de crontab" grep -qxF "    0 12 * * 0 $REC" <<<"$o"
chk "sin systemd: no escribe units" test ! -e "$SRV" -a ! -e "$TIM"
chk "sin systemd: no llama a enable" test "$(llamadas ' enable ')" = 0
o="$(MECANISMO_SYSTEMCTL="$T/no-existe/systemctl" "$REPO/instalar.sh" 2>&1)"
chk "sin systemctl en absoluto: imprime la línea de crontab" grep -qxF "    0 12 * * 0 $REC" <<<"$o"
o="$("$REPO/instalar.sh" 2>&1)"
chk "sin systemd 2.ª: «sin cambios»" grep -q 'sin cambios' <<<"$o"

# 9.6 --sin-recolector: no lo instala, y si ya estaba no lo quita
reset_sysd
o="$("$REPO/instalar.sh" --sin-recolector 2>&1)"; rc=$?
chk "--sin-recolector: sale 0" test "$rc" = 0
chk "--sin-recolector: no escribe units" test ! -e "$SRV" -a ! -e "$TIM"
chk "--sin-recolector: no llama a systemctl" test ! -s "$LOGS"
chk "--sin-recolector: lo dice" grep -q 'omitido (--sin-recolector)' <<<"$o"
"$REPO/instalar.sh" >/dev/null 2>&1; : > "$LOGS"
"$REPO/instalar.sh" --sin-recolector >/dev/null 2>&1
chk "--sin-recolector con timer ya puesto: units intactas" grep -qxF "ExecStart=$REC" "$SRV"
chk "--sin-recolector con timer ya puesto: no lo desactiva" test ! -s "$LOGS"
"$REPO/instalar.sh" --otra >/dev/null 2>&1; rc=$?
chk "argumento desconocido: exit 2" test "$rc" = 2

# 9.7 desinstalar: quita solo las units nuestras
: > "$LOGS"
o="$("$REPO/desinstalar.sh" 2>&1)"; rc=$?
chk "desinstalar recolector: sale 0" test "$rc" = 0
chk "desinstalar recolector: units quitadas" test ! -e "$SRV" -a ! -e "$TIM"
chk "desinstalar recolector: disable --now" grep -qx -- '--user disable --now mecanismo-recolectar.timer' "$LOGS"
chk "desinstalar recolector: daemon-reload después" bash -c 'tail -1 "$1" | grep -qx -- "--user daemon-reload"' _ "$LOGS"
reset_sysd; mkdir -p "$U"
printf '[Service]\nType=oneshot\nExecStart=%%h/.claude/mecanismo/recolectar-semanal.sh\n' > "$SRV"; printf '%s\n' "$TIMER_ESPERADO" > "$TIM"
mkdir -p "$U/timers.target.wants"; ln -s "$TIM" "$U/timers.target.wants/mecanismo-recolectar.timer"
"$REPO/desinstalar.sh" >/dev/null 2>&1
chk "desinstalar: quita también las units a mano de ~/.claude/mecanismo" test ! -e "$SRV" -a ! -e "$TIM"
chk "desinstalar: no deja el enlace de timers.target.wants" test ! -L "$U/timers.target.wants/mecanismo-recolectar.timer"
reset_sysd; mkdir -p "$U"
printf '[Service]\nType=oneshot\nExecStart=/usr/local/bin/otra-cosa --semanal\n' > "$SRV"; printf '%s\n' "$TIMER_ESPERADO" > "$TIM"
antes="$(cat "$SRV" "$TIM")"
o="$("$REPO/desinstalar.sh" 2>&1)"
chk "desinstalar: units ajenas con el mismo nombre intactas" test "$(cat "$SRV" "$TIM" 2>/dev/null)" = "$antes"
chk "desinstalar: no desactiva el timer ajeno" test "$(llamadas disable)" = 0
chk "desinstalar: dice que no es nuestro" grep -q 'no es nuestro: no se toca' <<<"$o"

# 9.8 recolectar-semanal: llama al mecanismo hermano (no al del PATH), con tope de 1 USD
RS="$T/rs"; mkdir -p "$RS"; cp "$REC" "$RS/recolectar-semanal"
cat > "$RS/mecanismo" <<FALSO
#!/usr/bin/env bash
echo "\$* USD=\$MECANISMO_PRESUPUESTO_USD" >> "$T/mecanismo.log"
[ "\$1" != propuestas ] || printf 'a  pendiente\nb  pendiente\nc  aprobada\n'
FALSO
printf '#!/usr/bin/env bash\necho "$*" >> "%s/aviso.log"\n' "$T" > "$T/falsos/aviso"
chmod +x "$RS/mecanismo" "$T/falsos/aviso"; ln -s "$RS/recolectar-semanal" "$T/enlace-rs"
MECANISMO_NOTIFY="$T/falsos/aviso" "$T/enlace-rs"; rc=$?
chk "recolectar-semanal: sale 0" test "$rc" = 0
chk "recolectar-semanal: history 14 y bitácora 30, top 5, con USD=1" test "$(grep recolectar "$T/mecanismo.log")" = $'recolectar --fuente history --dias 14 --top 5 USD=1\nrecolectar --fuente bitacora --dias 30 --top 5 USD=1'
chk "recolectar-semanal: log en mecanismo/recolectar-semanal.log" grep -q '^=== ' "$CLAUDE_HOME/mecanismo/recolectar-semanal.log"
chk "recolectar-semanal: avisa con las pendientes" grep -qF 'Recolector semanal: 2 propuestas pendientes' "$T/aviso.log"

# --- 8. bash -n
for f in "$REPO/instalar.sh" "$REPO/desinstalar.sh" "$ORIGEN_BIN" "$REPO/mecanismo/bin/recolectar-semanal" "$REPO/mecanismo/tests/instalar.sh" \
         "$REPO/plantilla-proyecto/.claude/hooks/mecanismo-trampas.sh" "$REPO/plantilla-proyecto/.claude/hooks/stop-evidencia.sh"; do
  chk "bash -n ${f#$REPO/}" bash -n "$f"
done
chk "jq . plantilla settings.json" bash -c 'jq . "$1" >/dev/null' _ "$REPO/plantilla-proyecto/.claude/settings.json"

# --- y nada de esto tocó el HOME real
chk "el ~/.config/systemd/user real no cambió (mtime antes y después)" test "$SYSD_ANTES" = "$(foto_sysd)"
chk "el ~/.local/bin/mecanismo real no apunta a la carpeta temporal" bash -c '! [[ "$(readlink "$1/.local/bin/mecanismo" 2>/dev/null)" == "$2"* ]]' _ "$HOME_REAL" "$T"

echo
if [ "$FALLOS" = 0 ]; then echo "TODO VERDE: $N comprobaciones"; else echo "FALLAN $FALLOS de $N"; exit 1; fi
