# forma-de-trabajo

Cómo trabaja Derek con Claude Code, en un repo que se instala solo. Son dos
archivos markdown que Claude Code lee al arrancar cada sesión; no es una
herramienta ni depende de ninguna.

## Instalar — la forma corta

Clona el repo, abre una sesión de Claude Code **dentro de la carpeta** y dile:

> instala esto

El `CLAUDE.md` del repo le explica qué es y qué hacer; corre `instalar.sh`,
que enlaza los archivos donde Claude Code los lee y respalda lo que hubiera.
Después abre un chat nuevo.

## Instalar — a mano

```bash
git clone https://github.com/dheidecker/forma-de-trabajo.git ~/Proyectos/forma-de-trabajo
~/Proyectos/forma-de-trabajo/instalar.sh
```

Si tus proyectos no viven en `~/Proyectos`:
`PROYECTOS=/tu/ruta ~/Proyectos/forma-de-trabajo/instalar.sh`

## Qué instala

| Archivo | Enlace que crea | Quién lo carga |
|---|---|---|
| `GLOBAL.md` | `~/.claude/CLAUDE.md` | **toda** sesión de la máquina |
| `EQUIPOS.md` | `~/Proyectos/CLAUDE.md` | toda sesión bajo `~/Proyectos/` |

## Comprobar que llegó

En el chat nuevo, pega el prompt de calibración que está al final de
`CLAUDE.md`. Si responde «subagentes efímeros, `Explore` para leer, roles del
proyecto, nada de push ni despliegues sin tu OK», está instalado.

## Editar

Edita los archivos **aquí** y commitea. Un `git pull` en cada máquina actualiza
la forma de trabajar entera. Nunca edites a través del enlace ni lo reemplaces
por una copia: dejaría de actualizarse.

## La trampa

Si se borra esta carpeta, los enlaces quedan colgando y las sesiones dejan de
recibir todo esto **sin avisar**. Por eso vive en un repo propio.

## Lo que NO viaja

- Las memorias de Claude por proyecto (`~/.claude/projects/*/memory/`): son
  personales y por máquina.
- El `CLAUDE.md` de cada proyecto y sus roles (`.claude/agents/`): viajan con el
  repo de cada proyecto, si están commiteados.
- `agent-observer`: herramienta opcional, ya fuera del flujo. Las secciones que
  la mencionan dicen que se salten si no está.
