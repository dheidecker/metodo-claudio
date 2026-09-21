# Este repo ES una metodología — instálala, no la leas como código

Si estás leyendo esto, alguien abrió una sesión de Claude Code dentro de
`forma-de-trabajo/`. No hay nada que desarrollar aquí: es **un** archivo
markdown, `METODOLOGIA.md`, que define cómo se trabaja con Claude Code, y tu
tarea es **dejarlo donde Claude Code lo lee**.

## Qué hacer

1. Corre `./instalar.sh`. Enlaza `~/.claude/CLAUDE.md` a `METODOLOGIA.md`,
   respaldando lo que hubiera, y verifica que resuelve.
2. Dile al usuario **una vez**: «Instalado. Abre un chat nuevo para que cargue:
   los `CLAUDE.md` se leen al arrancar la sesión». No pidas confirmación.
3. En ese chat nuevo, el usuario puede comprobar que llegó con el prompt de
   calibración de `METODOLOGIA.md` §6.

## Qué NO hacer

- No copies el contenido a `~/.claude/CLAUDE.md`: **enlaza**. Una copia deja de
  actualizarse con `git pull`.
- No edites `METODOLOGIA.md` para «adaptarlo» a esta máquina o a un proyecto.
  Lo específico de un proyecto va en el `CLAUDE.md` de ese proyecto.
- Si el usuario ya tenía un `~/.claude/CLAUDE.md` con reglas propias, el
  instalador lo respalda. Dile dónde quedó, y que lo que quiera conservar puede
  ir al `CLAUDE.md` de sus proyectos.
