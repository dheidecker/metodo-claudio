#!/usr/bin/env bash
# Deshace exactamente lo que hizo instalar.sh, y nada más. Idempotente.
#
# - Si ~/.claude/CLAUDE.md es nuestro enlace, lo quita.
# - Si es un archivo del usuario con nuestra línea @, quita solo esa línea
#   (y su cabecera). Las reglas propias del usuario quedan intactas.
# - Si el archivo queda vacío después, lo borra.
# - Quita ~/.local/bin/mecanismo solo si es el enlace a ESTE clon.
# No toca los respaldos *.bak: quedan para quien los quiera.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGEN="$AQUI/METODOLOGIA.md"
DESTINO="$HOME/.claude/CLAUDE.md"
IMPORT="@$ORIGEN"

echo "metodo-claudio: desinstalando"

if [ ! -e "$DESTINO" ] && [ ! -L "$DESTINO" ]; then
  echo "  no hay nada instalado en $DESTINO"

elif [ -L "$DESTINO" ] && [ "$(readlink -f "$DESTINO")" = "$ORIGEN" ]; then
  rm "$DESTINO"
  echo "  enlace quitado: $DESTINO"

elif [ -f "$DESTINO" ] && grep -qxF "$IMPORT" "$DESTINO"; then
  # quita la línea @ y la cabecera que puso el instalador
  grep -vxF "$IMPORT" "$DESTINO" | grep -vxF "# Metodología compartida (metodo-claudio)" > "$DESTINO.tmp"
  # colapsa líneas vacías finales
  sed -i -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$DESTINO.tmp"
  if [ -s "$DESTINO.tmp" ] && grep -q '[^[:space:]]' "$DESTINO.tmp"; then
    mv "$DESTINO.tmp" "$DESTINO"
    echo "  importación quitada; tus reglas propias siguen en $DESTINO"
  else
    rm -f "$DESTINO.tmp" "$DESTINO"
    echo "  importación quitada; el archivo quedó vacío y se borró"
  fi

else
  echo "  $DESTINO no es nuestro: no se toca"
fi

BIN="$HOME/.local/bin/mecanismo"
BIN_ORIGEN="$AQUI/mecanismo/bin/mecanismo"
if [ -L "$BIN" ] && [ "$(readlink "$BIN")" = "$BIN_ORIGEN" ]; then
  rm "$BIN"
  echo "  enlace quitado: $BIN"
elif [ -e "$BIN" ] || [ -L "$BIN" ]; then
  echo "  $BIN no apunta a este clon: no se toca"
else
  echo "  no hay mecanismo en $BIN"
fi

echo
echo "Listo. Abre un chat NUEVO: el cambio se aplica al arrancar la sesión."
echo "Los respaldos *.bak que dejó la instalación siguen en ~/.claude/, por si quieres volver."
