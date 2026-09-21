# Este repo ES una metodología — instálala, no la leas como código

Si estás leyendo esto, alguien abrió una sesión de Claude Code dentro de
`metodo-claudio/`. No hay nada que desarrollar aquí: es **un** archivo
markdown, `METODOLOGIA.md`, que define cómo se trabaja con Claude Code, y tu
tarea es **dejarlo donde Claude Code lo lee**.

## Qué hacer

1. Corre `./instalar.sh`. Si `~/.claude/CLAUDE.md` no existe, lo crea como
   enlace a `METODOLOGIA.md`. Si ya existe con reglas del usuario, **las
   conserva** y le añade una línea `@ruta` que importa la metodología. Siempre
   deja respaldo. Idempotente: correrlo dos veces no duplica nada.
2. Dile al usuario **una vez**: «Instalado. Abre un chat nuevo para que cargue:
   los `CLAUDE.md` se leen al arrancar la sesión». No pidas confirmación.
3. En ese chat nuevo, el usuario puede comprobar que llegó con el prompt de
   calibración de `METODOLOGIA.md` §6.

## Si el usuario quiere quitarlo

Corre `./desinstalar.sh`. Deshace solo lo que hizo el instalador y conserva las
reglas propias del usuario. Dile que abra un chat nuevo.

## Qué NO hacer

- No copies el contenido a `~/.claude/CLAUDE.md`: **enlaza**. Una copia deja de
  actualizarse con `git pull`.
- No edites `METODOLOGIA.md` para «adaptarlo» a esta máquina o a un proyecto.
  Lo específico de un proyecto va en el `CLAUDE.md` de ese proyecto.
- No toques las reglas propias del usuario que ya estuvieran en
  `~/.claude/CLAUDE.md`: el instalador las conserva y solo añade la importación.
  Si hay un respaldo, dile dónde quedó.
