# forma-de-trabajo

Cómo trabaja Derek con Claude Code. Son dos archivos markdown que Claude Code
lee al arrancar cada sesión; nada más. No es una herramienta ni depende de
ninguna.

| Archivo | Qué es | Quién lo carga |
|---|---|---|
| `GLOBAL.md` | La forma de trabajar: subagentes efímeros, cómo encargar, cómo escribir un rol, qué necesita autorización | **toda** sesión de la máquina, en cualquier directorio |
| `EQUIPOS.md` | Cómo se identifica un agente, revivir como rescate, permisos por sesión | toda sesión bajo `~/Proyectos/` |

## Instalar en una máquina nueva

```bash
git clone <este-repo> ~/Proyectos/forma-de-trabajo
ln -sf ~/Proyectos/forma-de-trabajo/GLOBAL.md  ~/.claude/CLAUDE.md
ln -sf ~/Proyectos/forma-de-trabajo/EQUIPOS.md ~/Proyectos/CLAUDE.md
```

Después, **abre un chat nuevo**: los `CLAUDE.md` se leen al arrancar la sesión.
Comprobado que Claude Code los carga a través del enlace.

Si `~/.claude/CLAUDE.md` ya existía, `ln -sf` lo reemplaza: respáldalo antes si
tenía algo que quieras conservar.

## Editar

Edita los archivos **aquí**, no a través del enlace, y commitea. Un `git pull`
en la otra máquina actualiza la forma de trabajar entera.

## La trampa

Si se borra este directorio, los dos enlaces quedan colgando y las sesiones
dejan de recibir todo esto **sin avisar**. Por eso vive en un repo propio y no
dentro de ninguna herramienta ni proyecto que se pueda descartar.

## Lo que NO viaja con este repo

- Las memorias de Claude por proyecto (`~/.claude/projects/*/memory/`): son
  personales y por máquina.
- El `CLAUDE.md` de cada proyecto y sus roles (`.claude/agents/`): viajan con el
  repo de cada proyecto, si están commiteados.
