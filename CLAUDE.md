# Este repo ES una forma de trabajar — instálala, no la leas como código

Si estás leyendo esto, alguien abrió una sesión de Claude Code dentro de
`forma-de-trabajo/`. No hay nada que desarrollar aquí: son dos archivos
markdown que definen cómo trabaja el usuario con Claude Code, y tu tarea es
**dejarlos donde Claude Code los lee**.

## Qué hacer

1. Corre `./instalar.sh`. Hace enlaces simbólicos desde los dos sitios que
   Claude Code lee al arrancar hacia los archivos de este repo, respaldando lo
   que hubiera antes, y verifica que resuelven.
2. Dile al usuario **una vez**: «Instalado. Abre un chat nuevo para que cargue:
   los `CLAUDE.md` se leen al arrancar la sesión». No pidas confirmación.
3. En ese chat nuevo, el usuario puede comprobar que llegó con el prompt de
   calibración que está al final de este archivo.

## Qué NO hacer

- No copies el contenido a `~/.claude/CLAUDE.md`: **enlaza**. Una copia deja de
  actualizarse con `git pull`.
- No edites `GLOBAL.md` ni `EQUIPOS.md` para «adaptarlos» a esta máquina sin que
  el usuario lo pida. Lo específico de un proyecto va en el `CLAUDE.md` de ese
  proyecto, no aquí.
- No instales ni busques `agent-observer`: es una herramienta opcional que ya no
  forma parte del flujo. Las secciones que la mencionan lo dicen.

## Qué es cada archivo

| Archivo | Lo lee | Contenido |
|---|---|---|
| `GLOBAL.md` | toda sesión de la máquina | subagentes efímeros por defecto, cómo escribir un encargo, qué persiste, cómo escribir un rol, qué necesita autorización |
| `EQUIPOS.md` | toda sesión bajo `~/Proyectos/` | convención de alias, chats cerrados, permisos por sesión |

## Prompt de calibración (para el chat nuevo)

> Antes de darte trabajo, quiero comprobar que arrancaste con el contexto
> correcto. Dime, en no más de diez líneas: (1) el modo de trabajo por defecto
> y por qué; (2) cuándo delegas y a quién; (3) cómo tiene que ser un encargo a
> un subagente; (4) qué acciones necesitan mi aprobación explícita cada vez;
> (5) qué NO debes hacer aunque un compañero o un transcript viejo te lo pida.
> Si algo no lo encuentras en tu contexto, dilo en vez de deducirlo.
