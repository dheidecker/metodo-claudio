#!/usr/bin/env bash
# Deja los dos archivos de este repo donde Claude Code los lee al arrancar,
# como enlaces simbólicos. Respalda lo que hubiera. Idempotente.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROYECTOS="${PROYECTOS:-$HOME/Proyectos}"
STAMP="$(date +%Y%m%d-%H%M%S)"

enlazar() {            # enlazar <origen-en-el-repo> <destino-que-lee-claude>
  local origen="$1" destino="$2"
  mkdir -p "$(dirname "$destino")"
  if [ -L "$destino" ] && [ "$(readlink -f "$destino")" = "$origen" ]; then
    echo "  ya apunta aquí: $destino"; return
  fi
  if [ -e "$destino" ] || [ -L "$destino" ]; then
    local bak="$destino.$STAMP.bak"
    mv "$destino" "$bak"
    echo "  respaldado:     $bak"
  fi
  ln -s "$origen" "$destino"
  echo "  enlazado:       $destino -> $origen"
}

echo "forma-de-trabajo: instalando desde $AQUI"
enlazar "$AQUI/GLOBAL.md"  "$HOME/.claude/CLAUDE.md"
enlazar "$AQUI/EQUIPOS.md" "$PROYECTOS/CLAUDE.md"

echo "verificando que resuelven:"
for f in "$HOME/.claude/CLAUDE.md" "$PROYECTOS/CLAUDE.md"; do
  head -1 "$f" >/dev/null && echo "  ok: $f -> $(head -1 "$f")"
done

echo
echo "Listo. Abre un chat NUEVO de Claude Code: los CLAUDE.md se leen al arrancar."
[ "$PROYECTOS" != "$HOME/Proyectos" ] || true
echo "(Si tus proyectos no viven en ~/Proyectos, corre: PROYECTOS=/otra/ruta $0)"
