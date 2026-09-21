#!/usr/bin/env bash
# Resume la bitácora de hooks: cuántas veces disparó cada uno y con qué resultado.
# Para podar con datos: un hook que bloqueó 14 veces vale; uno que nunca saltó se revisa.
L="$HOME/.claude/metodo-claudio.log"; [ -f "$L" ] || { echo "sin bitácora todavía ($L)"; exit 0; }
desde="${1:-30}"; corte="$(date -d "$desde days ago" '+%F')"
echo "Hooks en los últimos $desde días (desde $corte):"; echo
awk -F' \\| ' -v c="$corte" '$1 >= c { h=$2; gsub(/ +$/,"",h); r=$4; split(r,a," "); k=h" · "a[1]; n[k]++ } END { for (k in n) printf "  %5d  %s\n", n[k], k }' "$L" | sort -rn
echo; echo "Por proyecto:"; awk -F' \\| ' -v c="$corte" '$1 >= c { p=$3; gsub(/ +$/,"",p); n[p]++ } END { for (p in n) printf "  %5d  %s\n", n[p], p }' "$L" | sort -rn
