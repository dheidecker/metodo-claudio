#!/usr/bin/env bash
# statusLine: el % de contexto siempre a la vista, para «cerrar antes que compactar»
# sin tener que preguntarlo. Lee el JSON que Claude Code manda por stdin.
IN="$(cat)"
pct="$(jq -r '.context_window.used_percentage // empty' <<<"$IN")"
modelo="$(jq -r '.model.display_name // .model.id // empty' <<<"$IN")"
dir="$(basename "$(jq -r '.workspace.current_dir // .cwd // "."' <<<"$IN")")"
if [ -n "$pct" ]; then
  p=${pct%.*}
  if   [ "$p" -ge 70 ]; then sem="🔴"; nota="  cierra y abre otro chat"
  elif [ "$p" -ge 40 ]; then sem="🟡"; nota=""
  else sem="🟢"; nota=""; fi
  printf '%s contexto %s%%%s · %s · %s\n' "$sem" "$p" "$nota" "$modelo" "$dir"
else
  printf '%s · %s\n' "$modelo" "$dir"
fi
