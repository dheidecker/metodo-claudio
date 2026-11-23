#!/usr/bin/env bash
# Deshace exactamente lo que hizo instalar.sh, y nada más. Idempotente.
#
# - Si ~/.claude/CLAUDE.md es nuestro enlace, lo quita.
# - Si es un archivo del usuario con nuestra línea @, quita solo esa línea
#   (y su cabecera). Las reglas propias del usuario quedan intactas.
# - Si el archivo queda vacío después (o solo con la cabecera), lo respalda y lo borra.
# - Quita ~/.local/bin/mecanismo solo si es el enlace a ESTE clon. Va primero: así corre
#   siempre, aunque el paso de CLAUDE.md fallara.
# - Desactiva y borra las units del recolector semanal (mecanismo-recolectar.{service,timer})
#   solo si su ExecStart es nuestro: un */mecanismo/bin/recolectar-semanal o el script a
#   mano ~/.claude/mecanismo/recolectar-semanal.sh. Unas ajenas con el mismo nombre se quedan.
# No toca los respaldos *.bak: quedan para quien los quiera.
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGEN="$AQUI/METODOLOGIA.md"
DESTINO="$HOME/.claude/CLAUDE.md"
IMPORT="@$ORIGEN"
CABECERA="# Metodología compartida (metodo-claudio)"
STAMP="$(date +%Y%m%d-%H%M%S)"
TMP="$DESTINO.tmp"
# Nunca queda un .tmp, ni si algo falla a medias; y nunca se sale con error sin decirlo.
trap 'rm -f "$TMP"' EXIT
trap 'echo "metodo-claudio: desinstalar falló en la línea $LINENO" >&2' ERR

echo "metodo-claudio: desinstalando"

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

# --- recolector semanal. MECANISMO_SYSTEMCTL: las pruebas pasan uno falso, porque
# `systemctl --user` habla con el systemd real aunque se cambie HOME.
SYSTEMCTL="${MECANISMO_SYSTEMCTL:-systemctl}"
UNIDADES="$HOME/.config/systemd/user"
SERVICIO="$UNIDADES/mecanismo-recolectar.service"
TIMER="$UNIDADES/mecanismo-recolectar.timer"
EXEC=""
if [ -f "$SERVICIO" ]; then
  # Primera línea ExecStart=, sin prefijos de systemd (-@:+!) ni comillas; %h y %% resueltos.
  EXEC="$(sed -n 's/^[[:space:]]*ExecStart=[-@:+!]*//p' "$SERVICIO" | head -1)"
  EXEC="${EXEC%\"}"; EXEC="${EXEC#\"}"; EXEC="${EXEC//%h/$HOME}"; EXEC="${EXEC//%%/%}"
fi
case "$EXEC" in
  */mecanismo/bin/recolectar-semanal|"$HOME/.claude/mecanismo/recolectar-semanal.sh")
    HAY_SYSTEMD=0
    command -v "$SYSTEMCTL" >/dev/null 2>&1 && "$SYSTEMCTL" --user show-environment >/dev/null 2>&1 && HAY_SYSTEMD=1
    [ "$HAY_SYSTEMD" = 0 ] || "$SYSTEMCTL" --user disable --now mecanismo-recolectar.timer >/dev/null 2>&1 || true
    rm -f "$SERVICIO" "$TIMER"
    # Sin systemd que lo haga, el enlace de `enable` quedaría colgando.
    WANTS="$UNIDADES/timers.target.wants/mecanismo-recolectar.timer"
    [ ! -L "$WANTS" ] || rm -f "$WANTS"
    [ "$HAY_SYSTEMD" = 0 ] || "$SYSTEMCTL" --user daemon-reload >/dev/null 2>&1 || true
    echo "  recolector:     timer desactivado y units quitadas de $UNIDADES" ;;
  "")
    if [ -e "$SERVICIO" ] || [ -e "$TIMER" ]; then
      echo "  recolector:     $UNIDADES/mecanismo-recolectar.* sin ExecStart reconocible: no se toca"
    else
      echo "  no hay recolector programado"
    fi ;;
  *)
    echo "  recolector:     $SERVICIO apunta a $EXEC, no es nuestro: no se toca" ;;
esac

if [ ! -e "$DESTINO" ] && [ ! -L "$DESTINO" ]; then
  echo "  no hay nada instalado en $DESTINO"

elif [ -L "$DESTINO" ] && [ "$(readlink -f "$DESTINO")" = "$ORIGEN" ]; then
  rm "$DESTINO"
  echo "  enlace quitado: $DESTINO"

elif [ -f "$DESTINO" ] && grep -qxF "$IMPORT" "$DESTINO"; then
  # Quita la línea @ y la cabecera que puso el instalador, y las líneas vacías finales.
  # awk y no `grep -v | grep -v`: si no queda ninguna línea, grep sale 1 y, con
  # pipefail, abortaba sin mensaje dejando el .tmp y la importación puesta.
  IMPORT="$IMPORT" CABECERA="$CABECERA" awk '
    $0 == ENVIRON["IMPORT"] || $0 == ENVIRON["CABECERA"] { next }
    { l[++n] = $0; if ($0 ~ /[^ \t\r]/) u = n }
    END { for (i = 1; i <= u; i++) print l[i] }
  ' "$DESTINO" > "$TMP"
  if [ -s "$TMP" ]; then
    mv "$TMP" "$DESTINO"
    echo "  importación quitada; tus reglas propias siguen en $DESTINO"
  else
    mv "$DESTINO" "$DESTINO.$STAMP.bak"
    rm -f "$TMP"
    echo "  importación quitada; el archivo no tenía nada más y se retiró"
    echo "  respaldo:       $DESTINO.$STAMP.bak"
  fi

else
  echo "  $DESTINO no es nuestro: no se toca"
fi

echo
echo "Listo. Abre un chat NUEVO: el cambio se aplica al arrancar la sesión."
echo "Los respaldos *.bak que dejó la instalación siguen en ~/.claude/, por si quieres volver."
