# forma-de-trabajo

Una metodología para trabajar con Claude Code, en un repo que se instala solo.
Es **un** archivo markdown que Claude Code lee al arrancar cada sesión; no es
una herramienta ni depende de ninguna.

En corto: subagentes efímeros por defecto, la continuidad en archivos y no en
chats, encargos densos con informes delgados, roles con memoria propia, y una
lista corta de lo que siempre necesita autorización. Con los números que lo
justifican.

## Instalar — la forma corta

Clona el repo, abre una sesión de Claude Code **dentro de la carpeta** y dile:

> instala esto

El `CLAUDE.md` del repo le explica qué es y qué hacer. Después abre un chat
nuevo.

## Instalar — a mano

```bash
git clone https://github.com/dheidecker/forma-de-trabajo.git
forma-de-trabajo/instalar.sh
```

Si `~/.claude/CLAUDE.md` no existe, lo crea como enlace a `METODOLOGIA.md`. Si
ya tienes reglas propias ahí, **se conservan**: el instalador añade una línea
`@ruta/METODOLOGIA.md`, que Claude Code resuelve al cargar. Siempre respalda.
Idempotente: correrlo dos veces no duplica nada.

## Comprobar que llegó

En el chat nuevo, pega el prompt de calibración de `METODOLOGIA.md` §6. Si
responde «subagentes efímeros, `Explore` para leer, roles del proyecto, nada de
push ni despliegues sin tu OK», está instalado.

## Editar

Edita `METODOLOGIA.md` **aquí** y commitea. Un `git pull` en cada máquina
actualiza la metodología entera. Nunca edites a través del enlace ni lo
reemplaces por una copia: dejaría de actualizarse.

## La trampa

Si se borra esta carpeta, el enlace queda colgando y las sesiones dejan de
recibir la metodología **sin avisar**. Por eso vive en un repo propio, sin
mezclarse con ninguna herramienta ni proyecto que se pueda descartar.

## Lo que NO viaja

- El `CLAUDE.md` de cada proyecto, sus roles (`.claude/agents/`) y la memoria de
  esos roles (`.claude/agent-memory/`): viajan con el repo de cada proyecto.
- Las memorias de Claude por proyecto (`~/.claude/projects/*/memory/`): son
  personales y por máquina.
