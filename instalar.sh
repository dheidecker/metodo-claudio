#!/usr/bin/env bash
# Deja METODOLOGIA.md donde Claude Code lo lee al arrancar, como enlace
# simbólico. Respalda lo que hubiera. Idempotente.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGEN="$AQUI/METODOLOGIA.md"
DESTINO="$HOME/.claude/CLAUDE.md"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "forma-de-trabajo: instalando desde $AQUI"
mkdir -p "$(dirname "$DESTINO")"

if [ -L "$DESTINO" ] && [ "$(readlink -f "$DESTINO")" = "$ORIGEN" ]; then
  echo "  ya apunta aquí: $DESTINO"
else
  if [ -e "$DESTINO" ] || [ -L "$DESTINO" ]; then
    mv "$DESTINO" "$DESTINO.$STAMP.bak"
    echo "  respaldado:     $DESTINO.$STAMP.bak"
  fi
  ln -s "$ORIGEN" "$DESTINO"
  echo "  enlazado:       $DESTINO -> $ORIGEN"
fi

# Versiones anteriores de este repo enlazaban también ~/Proyectos/CLAUDE.md.
# Si ese enlace apunta a un archivo de este repo que ya no existe, se retira.
VIEJO="$HOME/Proyectos/CLAUDE.md"
if [ -L "$VIEJO" ] && [[ "$(readlink "$VIEJO")" == "$AQUI/"* ]] && [ ! -e "$VIEJO" ]; then
  rm "$VIEJO"; echo "  retirado enlace colgante: $VIEJO"
fi

head -1 "$DESTINO" >/dev/null && echo "  ok: $DESTINO -> $(head -1 "$DESTINO")"
echo
echo "Listo. Abre un chat NUEVO de Claude Code: los CLAUDE.md se leen al arrancar."
