# metodo-claudio

Una metodología para trabajar con Claude Code, en un repo que se instala solo.
Es **un** archivo markdown que Claude Code lee al arrancar cada sesión; no es
una herramienta ni depende de ninguna.

En corto: subagentes efímeros por defecto, la continuidad en archivos y no en
chats, encargos densos con informes delgados, roles con memoria propia, y una
lista corta de lo que siempre necesita autorización. Con los números que lo
justifican.

## Qué hay en el repo

```
METODOLOGIA.md              lo que carga cada sesión (~190 líneas): la metodología entera
CLAUDE.md                   lo que Claude lee al abrir esta carpeta: cómo instalarse
instalar.sh / desinstalar.sh
guardarrailes.json          permissions.deny / ask para lo irreversible
hooks/
  compactacion.sh           PreCompact + PostCompact: punto de guardado al compactar
  precommit-credenciales.sh PreToolUse en git commit: bloquea .env, claves, cuentas de servicio
  statusline.sh             % de contexto con semáforo (solo CLI)
  informe.sh                resume la bitácora de hooks para podar
  settings-hooks.json       el snippet de settings.json con todo lo anterior
plantilla-proyecto/.claude/ lo que se copia a un proyecto nuevo:
  settings.json             los hooks del proyecto, sin rutas escritas (CLAUDE_PROJECT_DIR)
  hooks/lint-editado.sh     php -l / node --check tras cada edición, en el mismo turno
  hooks/blade-trampas.sh    trampas Blade/migraciones en las líneas cambiadas; avisa
  hooks/stop-lint.sh        puerta Stop: bloquea si php -l falla en lo cambiado en la sesión
  hooks/session-marca.sh    marca de inicio de sesión para que stop-lint solo mire lo de hoy
  hooks/mecanismo-trampas.sh  shim: trampas como datos (Edit|Write y Stop); mudo sin mecanismo
  hooks/stop-evidencia.sh   shim: puerta Stop de evidencia; mudo sin mecanismo
  agents/desarrollador.md   rol genérico con memory: project, para especializar
mecanismo/                  el ciclo que mantiene vivas las reglas (Python, se desarrolla aquí)
  CONTRATO.md               la ley entre piezas: formatos, CLI, exit codes
  PLAN.md                   el porqué
  bin/mecanismo             la CLI; instalar.sh la enlaza en ~/.local/bin
  lib/                      un paquete por subcomando; lib/comun.py congelado
  hooks/                    los hooks Python que llaman los shims
  tests/                    unittest + tests/instalar.sh (instalador con HOME falso)
```

Dos capas: lo **global** (`METODOLOGIA.md`, `guardarrailes.json`, `hooks/`) se
instala una vez por máquina; lo de **proyecto** (`plantilla-proyecto/`) se copia
a cada repo y se especializa con sus trampas.

## Instalar — la forma corta

Clona el repo, abre una sesión de Claude Code **dentro de la carpeta** y dile:

> instala esto

El `CLAUDE.md` del repo le explica qué es y qué hacer. Después abre un chat
nuevo.

## Instalar — a mano

```bash
git clone https://github.com/dheidecker/metodo-claudio.git
metodo-claudio/instalar.sh
```

Si `~/.claude/CLAUDE.md` no existe, lo crea como enlace a `METODOLOGIA.md`. Si
ya tienes reglas propias ahí, **se conservan**: el instalador añade una línea
`@ruta/METODOLOGIA.md`, que Claude Code resuelve al cargar. Siempre respalda.
Idempotente: correrlo dos veces no duplica nada.

## Los dos clics que no se pueden automatizar

Son de seguridad de Claude Code, y está bien que existan:

1. **Confiar en la carpeta.** La primera vez que Claude Code abre un directorio
   nuevo pregunta si confías en él antes de leer su `CLAUDE.md`. Di sí, o
   «instala esto» no hace nada.
2. **Aprobar la importación**, solo si ya tenías reglas propias: cuando un
   `CLAUDE.md` importa un archivo de fuera de `~/.claude`, Claude Code lo
   muestra y pide aprobarlo una vez. Si el instalador creó un enlace (no tenías
   archivo), este paso no aparece.

## Guardarraíles (opcional, recomendado)

`guardarrailes.json` trae reglas `permissions.deny` / `permissions.ask` para lo
irreversible: `push`, despliegues, `rm -rf`, migraciones destructivas. Son
nativas de Claude Code y se imponen incluso en modo `auto`. **Las aplicas tú**,
fusionándolas en `~/.claude/settings.json` — Claude no puede tocar sus propios
permisos, por diseño:

```bash
cd ~/Proyectos/metodo-claudio
jq -s '.[0] * {permissions: {deny: ((.[0].permissions.deny // []) + .[1].permissions.deny | unique), ask: ((.[0].permissions.ask // []) + .[1].permissions.ask | unique)}}' \
  ~/.claude/settings.json guardarrailes.json > /tmp/settings.new && mv /tmp/settings.new ~/.claude/settings.json
```

**Qué garantiza cada lista, medido:** `deny` bloquea el comando antes de
ejecutarse — comprobado en `auto` con `php artisan migrate:fresh --help`, que
ningún chequeo incorporado cubre. `ask` fuerza un diálogo que ve el **usuario** —
comprobado en `auto` con `git push --dry-run`: apareció el diálogo y el usuario
decidió. Desde dentro de la sesión no se distingue «aprobado» de «no preguntó»,
así que esa comprobación la hace quien instala, una vez. En `bypassPermissions` los `ask` no preguntan, por definición.

**Límite de las reglas por prefijo:** `Bash(git push*)` casa con comandos que
*empiezan* por `git push`. `git -C <dir> push` o `cd x && git push` pueden no
casar según la versión. Para lo que de verdad no debe pasar, `deny` y
comandos simples; y no confíes en que un `ask` atrape todas las variantes.

**Y un hook que las reglas por patrón no pueden hacer:** `hooks/precommit-credenciales.sh`
corre antes de cada `git commit` (`PreToolUse` con `if: Bash(git commit*)`) y
bloquea si el índice trae `.env`, cuentas de servicio, claves `.pem`/`.key` o
`secrets.*`. Va en el mismo snippet que el resto de hooks.

Ajusta las reglas a tu stack antes de aplicarlas: las de `php artisan` y
`gcloud` son ejemplos de un proyecto Laravel en Cloud Run.

## mecanismo: trampas, evidencia y permisos con datos

`mecanismo/` es la parte que **sí** se desarrolla: el ciclo que convierte lo que se
repite en reglas ejecutables y que pide evidencia de que lo cambiado funciona. La
confianza sale de verificar después, no de aprobar antes. El porqué está en
`mecanismo/PLAN.md`; los formatos, en `mecanismo/CONTRATO.md`.

`instalar.sh` enlaza la CLI en `~/.local/bin/mecanismo` (necesita python3 3.12 y
PyYAML: `apt install python3-yaml`) e imprime las reglas `allow` para que sus
lecturas no pidan permiso. En un proyecto:

```bash
cd <proyecto> && mecanismo init --tipo mcp   # o web, o lib
```

Deja `.claude/mecanismo.yml` (puerta en `aviso`), un `mapa-funciones.yml` de
ejemplo, las carpetas de trampas y verificación, los dos shims y
`.claude/evidencia/` en el `.gitignore`. No pisa nada que exista y **no toca
`settings.json`**: imprime el comando `jq` que engancha los shims. Los shims
salen en silencio en una máquina sin `mecanismo`.

Pruebas:

```bash
cd mecanismo && python3 -m unittest discover -s tests -t .
bash mecanismo/tests/instalar.sh    # el instalador, con un HOME temporal
```

## Punto de guardado al compactar (opcional)

`hooks/compactacion.sh` se engancha a `PreCompact` y `PostCompact` (el
`instalar.sh` genera `hooks/settings-hooks.local.json` con la ruta real del clon): antes de
compactar anota archivos tocados y últimas peticiones; después guarda el
resumen. Un archivo por compactación en
`~/.claude/projects/<proyecto>/compactaciones/`. Solo necesita `jq`; nunca
bloquea. Como los guardarraíles, **lo aplicas tú**:

```bash
cd ~/Proyectos/metodo-claudio
jq -s '.[0] * .[1]' ~/.claude/settings.json hooks/settings-hooks.local.json > /tmp/settings.new && mv /tmp/settings.new ~/.claude/settings.json
```

Si ya tenías hooks `PreCompact`/`PostCompact`, este comando los reemplaza por
los del repo: fusiónalos a mano en ese caso. Después, chat nuevo. Para
probarlo, `/compact` en un chat y mira el directorio.

## Plantilla para un proyecto nuevo

```bash
cp -r ~/Proyectos/metodo-claudio/plantilla-proyecto/.claude  <proyecto>/
```

Trae `settings.json` con tres hooks —`php -l`/`node --check` tras cada edición,
linter de trampas Blade/migraciones que avisa, y una puerta `Stop` que bloquea
si `php -l` falla en lo cambiado durante la sesión—, los dos shims de
`mecanismo` (mudos si no está instalado) y un rol `desarrollador`
genérico con `memory: project`. Todo relativo a `CLAUDE_PROJECT_DIR`: sin rutas
escritas. Especialízalo con las trampas del proyecto; los hooks de PHP/Blade
sobran si el proyecto no es PHP — bórralos del `settings.json`.

## La statusline es solo para la terminal

`hooks/statusline.sh` dibuja el % de contexto con semáforo bajo el prompt del
**CLI** (`claude` en una terminal). **En Claude Desktop no se muestra**: la app
trae su propio indicador — «Ventana de contexto N / 1M (x%)» en el desglose de
uso, arriba a la derecha — que cubre lo mismo. Si solo usas Desktop, puedes
quitar `statusLine` del snippet antes de aplicarlo; no hace daño dejarlo.

## Bitácora de hooks, para podar con datos

Cada hook deja una línea en `~/.claude/metodo-claudio.log`: fecha, hook,
proyecto y resultado (`ok`, `AVISO`, `BLOQUEO`, `silencio`). `hooks/informe.sh
[días]` la resume: cuántas veces disparó cada uno y con qué resultado. La
regla de poda — «un hook que en un mes no disparó se revisa» — solo se puede
aplicar si alguien lo sabe.

## Comprobar que llegó

En el chat nuevo, pega el prompt de calibración de `METODOLOGIA.md` §6. Si
responde «subagentes efímeros, `Explore` para leer, roles del proyecto, nada de
push ni despliegues sin tu OK», está instalado.

## Quitar

```bash
~/Proyectos/metodo-claudio/desinstalar.sh
```

Deshace exactamente lo que hizo el instalador: quita el enlace, o quita solo
la línea de importación dejando tus reglas intactas. Los respaldos se quedan.
Idempotente. Después, chat nuevo.

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
