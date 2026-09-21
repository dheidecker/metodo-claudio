#!/usr/bin/env bash
# PostToolUse sobre Edit|Write, solo *.blade.php y database/migrations/*.php.
# Cuatro trampas con caso real en tickets/CLAUDE.md §10 que ningún linter ve.
# AVISA (exit 0 + JSON): los greps pueden dar falsos positivos y bloquear sería peor.
set -uo pipefail
command -v jq >/dev/null || exit 0
f="$(jq -r '.tool_input.file_path // .tool_response.filePath // empty')"
[ -n "$f" ] && [ -f "$f" ] || exit 0
avisos=()
case "$f" in
  *.blade.php)
    # x-init evalúa una EXPRESIÓN: un bloque con ; o { no corre y no avisa (caso: limpieza de localStorage que nunca corrió)
    n=$(grep -n -E 'x-init="[^"]*[;{]' "$f" | head -3 | cut -d: -f1 | tr '\n' ',' | sed 's/,$//')
    [ -n "$n" ] && avisos+=("x-init con bloque (líneas $n): x-init evalúa una expresión; mueve la lógica a un método del x-data y llámalo.")
    # x-show pierde contra d-flex (!important): el elemento sigue visible (caso: 80 filas que no se plegaban)
    n=$(grep -n -E '<[^>]*x-show=[^>]*class="[^"]*\bd-(flex|block|inline)[^>]*>|<[^>]*class="[^"]*\bd-(flex|block|inline)[^"]*"[^>]*x-show=' "$f" | head -3 | cut -d: -f1 | tr '\n' ',' | sed 's/,$//')
    [ -n "$n" ] && avisos+=("x-show junto a d-flex/d-block (líneas $n): la clase !important de Bootstrap gana y no se oculta; pon x-show en un contenedor sin clase de display.")
    # directiva Blade o <script> dentro de un comentario JS //: rompe el <head> y php -l da limpio
    n=$(grep -n -E '^\s*//.*(@section|@if|@yield|@include|@push|<script)' "$f" | head -3 | cut -d: -f1 | tr '\n' ',' | sed 's/,$//')
    [ -n "$n" ] && avisos+=("directiva Blade o <script> dentro de un comentario // (líneas $n): Blade lo procesa igual y rompe el head; usa {{-- --}}.")
    # select/checkbox con wire:model sin .live (caso: tres selectores perdían la selección)
    n=$(awk '/<select|type="checkbox"/{s=NR} s && /wire:model="/{ if ($0 !~ /wire:model\.live/) print NR; s=0 } /<\/select>|\/>/{s=0}' "$f" | head -3 | tr '\n' ',' | sed 's/,$//')
    [ -n "$n" ] && avisos+=("select/checkbox con wire:model sin .live (líneas $n): un re-render lo repinta vacío; regla de las tres cosas: .live, @selected emitido por el servidor, y valor desde el evento si se consume en el mismo gesto.")
    ;;
  */database/migrations/*.php)
    # TIMESTAMP NOT NULL: MySQL le pone ON UPDATE CURRENT_TIMESTAMP al primero (caso: cartera_historial perdió la hora en 5.509 filas)
    n=$(grep -n -E -- '->timestamp\(' "$f" | grep -v -E 'nullable|useCurrent|timestamps\(' | head -3 | cut -d: -f1 | tr '\n' ',' | sed 's/,$//')
    [ -n "$n" ] && avisos+=("->timestamp() sin nullable() (líneas $n): con explicit_defaults_for_timestamp=OFF el primero recibe ON UPDATE y cada UPDATE le pisa la hora; usa dateTime().")
    ;;
esac
[ ${#avisos[@]} -eq 0 ] && exit 0
msg="Trampas conocidas en $(basename "$f"):"; for a in "${avisos[@]}"; do msg="$msg"$'\n'"- $a"; done
jq -n --arg m "$msg" '{systemMessage: $m, hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $m}}'
exit 0
