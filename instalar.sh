#!/usr/bin/env bash
# Deja METODOLOGIA.md donde Claude Code lo lee al arrancar. Idempotente.
#
# Si ~/.claude/CLAUDE.md no existe, lo crea como enlace a METODOLOGIA.md.
# Si ya existe con reglas propias, NO lo reemplaza: le añade una línea de
# importación (@ruta), que Claude Code resuelve al cargar. Así conviven las
# reglas de quien instala con la metodología, y `git pull` sigue actualizándola.
#
# También enlaza la CLI de mecanismo en ~/.local/bin/mecanismo. Nunca toca
# settings.json: imprime el comando jq para que lo apliques tú.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGEN="$AQUI/METODOLOGIA.md"
DESTINO="$HOME/.claude/CLAUDE.md"
IMPORT="@$ORIGEN"
STAMP="$(date +%Y%m%d-%H%M%S)"
CAMBIOS=0   # pasa a 1 en cuanto algo se crea, mueve o reescribe: la segunda corrida dice «sin cambios»

echo "metodo-claudio: instalando desde $AQUI"
mkdir -p "$(dirname "$DESTINO")"

if [ -L "$DESTINO" ] && [ "$(readlink "$DESTINO")" = "$ORIGEN" ]; then
  echo "  ya apunta aquí: $DESTINO"

elif [ -L "$DESTINO" ] && [ ! -e "$DESTINO" ]; then
  # Enlace colgante: el caso de un repo renombrado o movido. No hay nada que
  # conservar del destino viejo — se respalda el enlace y se apunta aquí.
  # (readlink -f sobre un colgante cuya carpeta ya no existe devuelve vacío y
  # exit 1: con set -e mataba el instalador justo cuando más falta hacía.)
  mv "$DESTINO" "$DESTINO.$STAMP.bak"
  ln -s "$ORIGEN" "$DESTINO"; CAMBIOS=1
  echo "  era un enlace colgante a $(readlink "$DESTINO.$STAMP.bak"): re-enlazado aquí"

elif [ -L "$DESTINO" ]; then
  # Enlace a otro sitio que sí existe: se conserva lo que importaba y se suma esto.
  VIEJO="$(readlink -f "$DESTINO")"
  mv "$DESTINO" "$DESTINO.$STAMP.bak"
  { echo "@$VIEJO"; echo "$IMPORT"; } > "$DESTINO"; CAMBIOS=1
  echo "  era un enlace a $VIEJO: ahora es un archivo que importa ambos"
  echo "  respaldo:       $DESTINO.$STAMP.bak"

elif [ -f "$DESTINO" ]; then
  if grep -qxF "$IMPORT" "$DESTINO"; then
    echo "  ya importa la metodología: $DESTINO"
  else
    cp "$DESTINO" "$DESTINO.$STAMP.bak"
    { echo; echo "# Metodología compartida (metodo-claudio)"; echo "$IMPORT"; } >> "$DESTINO"; CAMBIOS=1
    echo "  tenía reglas propias: se conservan, y se añade la importación"
    echo "  respaldo:       $DESTINO.$STAMP.bak"
  fi

else
  ln -s "$ORIGEN" "$DESTINO"; CAMBIOS=1
  echo "  enlazado:       $DESTINO -> $ORIGEN"
fi

# Versiones anteriores de este repo enlazaban también ~/Proyectos/CLAUDE.md.
VIEJO_P="$HOME/Proyectos/CLAUDE.md"
if [ -L "$VIEJO_P" ] && [[ "$(readlink "$VIEJO_P")" == "$AQUI/"* ]] && [ ! -e "$VIEJO_P" ]; then
  rm "$VIEJO_P"; CAMBIOS=1; echo "  retirado enlace colgante: $VIEJO_P"
fi

echo "  verificado:     $(grep -c 'Metodología de trabajo con Claude Code' "$ORIGEN") archivo, legible"
# El snippet de hooks lleva la ruta real de este clon, sea cual sea.
# Solo se reescribe si cambió: así una segunda corrida puede decir «sin cambios».
LOCAL_HOOKS="$AQUI/hooks/settings-hooks.local.json"
sed "s#~/Proyectos/metodo-claudio#$AQUI#g" "$AQUI/hooks/settings-hooks.json" > "$LOCAL_HOOKS.tmp"
if cmp -s "$LOCAL_HOOKS.tmp" "$LOCAL_HOOKS"; then
  rm -f "$LOCAL_HOOKS.tmp"
  echo "  hooks:          hooks/settings-hooks.local.json ya al día"
else
  mv "$LOCAL_HOOKS.tmp" "$LOCAL_HOOKS"; CAMBIOS=1
  echo "  hooks:          hooks/settings-hooks.local.json generado con la ruta de este clon"
fi

# --- mecanismo: la CLI en ~/.local/bin, enlazada a este clon (nunca una copia).
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/mecanismo"
BIN_ORIGEN="$AQUI/mecanismo/bin/mecanismo"
[ -d "$BIN_DIR" ] || { mkdir -p "$BIN_DIR"; CAMBIOS=1; }

if [ -L "$BIN" ] && [ "$(readlink "$BIN")" = "$BIN_ORIGEN" ]; then
  echo "  mecanismo:      ya enlazado: $BIN"

elif [ -L "$BIN" ] && [ ! -e "$BIN" ] && [[ "$(readlink "$BIN")" == */mecanismo/bin/mecanismo ]]; then
  # Colgante a un clon nuestro (movido o borrado): no hay nada que conservar, se rehace.
  VIEJO_BIN="$(readlink "$BIN")"
  rm "$BIN"; ln -s "$BIN_ORIGEN" "$BIN"; CAMBIOS=1
  echo "  mecanismo:      era un enlace colgante a $VIEJO_BIN: re-enlazado aquí"

elif [ -e "$BIN" ] || [ -L "$BIN" ]; then
  # Ajeno: un archivo, un enlace a otro sitio que sí existe, o un colgante a otra
  # herramienta (no a un */mecanismo/bin/mecanismo). Se respalda, no se borra.
  mv "$BIN" "$BIN.$STAMP.bak"
  ln -s "$BIN_ORIGEN" "$BIN"; CAMBIOS=1
  echo "  mecanismo:      había algo ajeno en $BIN: enlazado aquí"
  echo "  respaldo:       $BIN.$STAMP.bak"

else
  ln -s "$BIN_ORIGEN" "$BIN"; CAMBIOS=1
  echo "  mecanismo:      enlazado: $BIN -> $BIN_ORIGEN"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "  aviso:          $BIN_DIR no está en tu PATH: añádelo para que los shims encuentren mecanismo" ;;
esac

# Sin python3/PyYAML se avisa y se sigue: los shims y hooks de mecanismo salen en silencio.
if ! command -v python3 >/dev/null 2>&1; then
  echo "  aviso:          falta python3 (3.12): mecanismo no correrá, los shims salen en silencio"
elif ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
  echo "  aviso:          $(python3 --version 2>&1): mecanismo pide 3.12 o más"
elif ! python3 -c 'import yaml' 2>/dev/null; then
  echo "  aviso:          falta PyYAML: instala python3-yaml (los hooks de mecanismo salen en silencio sin él)"
else
  echo "  python3:        $(python3 --version 2>&1 | cut -d' ' -f2) con PyYAML"
fi

[ "$CAMBIOS" = 1 ] || echo "  sin cambios:    todo ya estaba instalado"

echo
echo "Listo. Abre un chat NUEVO de Claude Code: los CLAUDE.md se leen al arrancar."
echo "En el chat nuevo, Claude se presenta solo en tres líneas. Si no lo hace, mira $DESTINO."

echo
echo "Opcional, lo aplicas tú (Claude no puede tocar tu settings.json):"
echo "  guardarraíles + hook de compactación + allow y deny de mecanismo, en un solo paso:"
# Las lecturas y verificaciones de mecanismo no deben pedir permiso (PLAN §1: cero prompts nuevos).
# `verificar` en allow es seguro: solo ejecuta comandos del yml que confiaste tú (CONTRATO §11).
ALLOW='["Bash(mecanismo trampas*)", "Bash(mecanismo verificar*)", "Bash(mecanismo recolectar*)", "Bash(mecanismo permisos*)", "Bash(chrome-devtools *)"]'
# Lo que decide una persona, nunca un agente: deny vale aunque la sesión corra en modo auto.
DENY='["Bash(mecanismo aprobar*)", "Bash(mecanismo rechazar*)", "Bash(mecanismo confiar*)", "Bash(script *)"]'
echo "  (el deny de aprobar/rechazar/confiar y de \`script\` es la frontera real contra que un agente se auto-apruebe: CONTRATO §11)"
echo "  jq -s '.[0] * .[1] * {permissions: {deny: ((.[0].permissions.deny // []) + .[2].permissions.deny + $DENY | unique), ask: ((.[0].permissions.ask // []) + .[2].permissions.ask | unique), allow: ((.[0].permissions.allow // []) + $ALLOW | unique)}}' ~/.claude/settings.json $AQUI/hooks/settings-hooks.local.json $AQUI/guardarrailes.json > /tmp/settings.new && mv /tmp/settings.new ~/.claude/settings.json"
echo
echo "  canario de permisos (opcional, temporal): anota en la bitácora qué eventos de permiso disparan."
CANARIO='{"hooks": [{"type": "command", "command": "mecanismo hook canario-permisos", "timeout": 5}]}'
FILTRO='def sin_canario: map(select([.hooks[]?.command // ""] | any(test("canario-permisos")) | not));'
for EV in PermissionRequest PermissionDenied Notification; do
  FILTRO="$FILTRO .hooks.$EV = (((.hooks.$EV // []) | sin_canario) + [$CANARIO]) |"
done
echo "  jq '${FILTRO% |}' ~/.claude/settings.json > /tmp/settings.new && mv /tmp/settings.new ~/.claude/settings.json"
