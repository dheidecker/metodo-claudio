#!/usr/bin/env bash
# Deja METODOLOGIA.md donde Claude Code lo lee al arrancar. Idempotente.
#
# Si ~/.claude/CLAUDE.md no existe, lo crea como enlace a METODOLOGIA.md.
# Si ya existe con reglas propias, NO lo reemplaza: le añade una línea de
# importación (@ruta), que Claude Code resuelve al cargar. Así conviven las
# reglas de quien instala con la metodología, y `git pull` sigue actualizándola.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGEN="$AQUI/METODOLOGIA.md"
DESTINO="$HOME/.claude/CLAUDE.md"
IMPORT="@$ORIGEN"
STAMP="$(date +%Y%m%d-%H%M%S)"

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
  ln -s "$ORIGEN" "$DESTINO"
  echo "  era un enlace colgante a $(readlink "$DESTINO.$STAMP.bak"): re-enlazado aquí"

elif [ -L "$DESTINO" ]; then
  # Enlace a otro sitio que sí existe: se conserva lo que importaba y se suma esto.
  VIEJO="$(readlink -f "$DESTINO")"
  mv "$DESTINO" "$DESTINO.$STAMP.bak"
  { echo "@$VIEJO"; echo "$IMPORT"; } > "$DESTINO"
  echo "  era un enlace a $VIEJO: ahora es un archivo que importa ambos"
  echo "  respaldo:       $DESTINO.$STAMP.bak"

elif [ -f "$DESTINO" ]; then
  if grep -qxF "$IMPORT" "$DESTINO"; then
    echo "  ya importa la metodología: $DESTINO"
  else
    cp "$DESTINO" "$DESTINO.$STAMP.bak"
    { echo; echo "# Metodología compartida (metodo-claudio)"; echo "$IMPORT"; } >> "$DESTINO"
    echo "  tenía reglas propias: se conservan, y se añade la importación"
    echo "  respaldo:       $DESTINO.$STAMP.bak"
  fi

else
  ln -s "$ORIGEN" "$DESTINO"
  echo "  enlazado:       $DESTINO -> $ORIGEN"
fi

# Versiones anteriores de este repo enlazaban también ~/Proyectos/CLAUDE.md.
VIEJO_P="$HOME/Proyectos/CLAUDE.md"
if [ -L "$VIEJO_P" ] && [[ "$(readlink "$VIEJO_P")" == "$AQUI/"* ]] && [ ! -e "$VIEJO_P" ]; then
  rm "$VIEJO_P"; echo "  retirado enlace colgante: $VIEJO_P"
fi

echo "  verificado:     $(grep -c 'Metodología de trabajo con Claude Code' "$ORIGEN") archivo, legible"
# El snippet de hooks lleva la ruta real de este clon, sea cual sea.
sed "s#~/Proyectos/metodo-claudio#$AQUI#g" "$AQUI/hooks/settings-hooks.json" > "$AQUI/hooks/settings-hooks.local.json"
echo "  hooks:          hooks/settings-hooks.local.json generado con la ruta de este clon"

echo
echo "Listo. Abre un chat NUEVO de Claude Code: los CLAUDE.md se leen al arrancar."
echo "En el chat nuevo, Claude se presenta solo en tres líneas. Si no lo hace, mira $DESTINO."

echo
echo "Opcional, lo aplicas tú (Claude no puede tocar tu settings.json):"
echo "  guardarraíles + hook de compactación, en un solo paso:"
echo "  jq -s '.[0] * .[1] * {permissions: {deny: ((.[0].permissions.deny // []) + .[2].permissions.deny | unique), ask: ((.[0].permissions.ask // []) + .[2].permissions.ask | unique)}}' ~/.claude/settings.json $AQUI/hooks/settings-hooks.local.json $AQUI/guardarrailes.json > /tmp/settings.new && mv /tmp/settings.new ~/.claude/settings.json"
