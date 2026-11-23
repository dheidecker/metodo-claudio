# metodo-claudio — una metodología que se instala, y un mecanismo que se desarrolla

Si estás leyendo esto, alguien abrió una sesión de Claude Code dentro de
`metodo-claudio/`. El repo tiene dos partes, y se tratan distinto:

- **`METODOLOGIA.md`, `hooks/` y `plantilla-proyecto/` se instalan, no se
  adaptan.** `METODOLOGIA.md` define cómo se trabaja con Claude Code; tu tarea
  con ellos es **dejarlos donde Claude Code los lee**.
- **`mecanismo/` sí se desarrolla.** Es Python (3.12, stdlib + PyYAML): el ciclo
  de trampas, evidencia y permisos. Ver más abajo.

## Si te piden instalar

1. Corre `./instalar.sh`. Si `~/.claude/CLAUDE.md` no existe, lo crea como
   enlace a `METODOLOGIA.md`. Si ya existe con reglas del usuario, **las
   conserva** y le añade una línea `@ruta` que importa la metodología. Siempre
   deja respaldo. También enlaza `~/.local/bin/mecanismo`. Idempotente: la
   segunda corrida dice «sin cambios».
2. Dile al usuario **una vez**: «Instalado. Abre un chat nuevo para que cargue:
   los `CLAUDE.md` se leen al arrancar la sesión». No pidas confirmación.
3. En ese chat nuevo, el usuario puede comprobar que llegó con el prompt de
   calibración de `METODOLOGIA.md` §6.

El instalador **imprime** los comandos `jq` para `settings.json` (guardarraíles,
hooks, reglas `allow` de mecanismo, canario): los aplica el usuario, no tú.

## Si el usuario quiere quitarlo

Corre `./desinstalar.sh`. Deshace solo lo que hizo el instalador (incluido el
enlace de `mecanismo`, si apunta a este clon) y conserva las reglas propias del
usuario. Dile que abra un chat nuevo.

## Si te piden trabajar en `mecanismo/`

- **La ley es `mecanismo/CONTRATO.md`.** Formatos, CLI y exit codes. Si algo
  necesita cambiarlo, se propone; no se cambia de paso.
- **`mecanismo/lib/comun.py` está congelado.** Lo que falte va en el paquete
  propio.
- Pruebas, antes de dar algo por terminado:
  `cd mecanismo && python3 -m unittest discover -s tests -t .`
  y, si tocaste el instalador, `bash mecanismo/tests/instalar.sh`.
- Ningún test ni prueba escribe en el `~/.claude` real: `CLAUDE_HOME`,
  `MECANISMO_HOME`, `MECANISMO_BITACORA` o `HOME=$(mktemp -d)`.

## Qué NO hacer

- No copies el contenido a `~/.claude/CLAUDE.md`: **enlaza**. Una copia deja de
  actualizarse con `git pull`.
- No edites `METODOLOGIA.md` para «adaptarlo» a esta máquina o a un proyecto.
  Lo específico de un proyecto va en el `CLAUDE.md` de ese proyecto.
- No toques las reglas propias del usuario que ya estuvieran en
  `~/.claude/CLAUDE.md`: el instalador las conserva y solo añade la importación.
  Si hay un respaldo, dile dónde quedó.
- No toques `hooks/statusline.sh` ni las piezas existentes (`hooks/`,
  `plantilla-proyecto/`, `guardarrailes.json`) salvo encargo.
- No corras `instalar.sh` desde un worktree contra tu `HOME` real: el enlace
  quedaría apuntando a una carpeta temporal.

## Trampas aprendidas

- **En git, `mecanismo` es a la vez rama y carpeta.** `git diff mecanismo` o
  `git merge mecanismo` son ambiguos: usa `refs/heads/mecanismo`, o `--` antes
  de las rutas.
- **`python3 -c` antepone el directorio actual a `sys.path`.** Un proyecto con
  su propio `lib/__init__.py` taparía nuestro paquete `lib`. `bin/mecanismo`
  corre con `python3 -P`; no se lo quites.
- **Los shims corren en cada edición.** `command -v mecanismo || exit 0` es lo
  que garantiza cero fricción en una máquina sin mecanismo, y `mecanismo hook`
  sale 0 si falta el hook: un problema de instalación nunca bloquea una sesión.
