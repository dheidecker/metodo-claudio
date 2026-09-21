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

echo "forma-de-trabajo: instalando desde $AQUI"
mkdir -p "$(dirname "$DESTINO")"

if [ -L "$DESTINO" ] && [ "$(readlink -f "$DESTINO")" = "$ORIGEN" ]; then
  echo "  ya apunta aquí: $DESTINO"

elif [ -L "$DESTINO" ]; then
  # Enlace a otro sitio: se conserva lo que importaba y se suma esto.
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
    { echo; echo "# Metodología compartida (forma-de-trabajo)"; echo "$IMPORT"; } >> "$DESTINO"
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
echo
echo "Listo. Abre un chat NUEVO de Claude Code: los CLAUDE.md se leen al arrancar."
echo "En el chat nuevo, Claude se presenta solo en tres líneas. Si no lo hace, mira $DESTINO."
