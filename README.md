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
cd ~/Proyectos/forma-de-trabajo
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

Ajusta las reglas a tu stack antes de aplicarlas: las de `php artisan` y
`gcloud` son ejemplos de un proyecto Laravel en Cloud Run.

## Punto de guardado al compactar (opcional)

`hooks/compactacion.sh` se engancha a `PreCompact` y `PostCompact` (el
`instalar.sh` genera `hooks/settings-hooks.local.json` con la ruta real del clon): antes de
compactar anota archivos tocados y últimas peticiones; después guarda el
resumen. Un archivo por compactación en
`~/.claude/projects/<proyecto>/compactaciones/`. Solo necesita `jq`; nunca
bloquea. Como los guardarraíles, **lo aplicas tú**:

```bash
cd ~/Proyectos/forma-de-trabajo
jq -s '.[0] * .[1]' ~/.claude/settings.json hooks/settings-hooks.local.json > /tmp/settings.new && mv /tmp/settings.new ~/.claude/settings.json
```

Si ya tenías hooks `PreCompact`/`PostCompact`, este comando los reemplaza por
los del repo: fusiónalos a mano en ese caso. Después, chat nuevo. Para
probarlo, `/compact` en un chat y mira el directorio.

## Plantilla para un proyecto nuevo

```bash
cp -r ~/Proyectos/forma-de-trabajo/plantilla-proyecto/.claude  <proyecto>/
```

Trae `settings.json` con tres hooks —`php -l`/`node --check` tras cada edición,
linter de trampas Blade/migraciones que avisa, y una puerta `Stop` que bloquea
si `php -l` falla en lo cambiado durante la sesión— y un rol `desarrollador`
genérico con `memory: project`. Todo relativo a `CLAUDE_PROJECT_DIR`: sin rutas
escritas. Especialízalo con las trampas del proyecto; los hooks de PHP/Blade
sobran si el proyecto no es PHP — bórralos del `settings.json`.

## Comprobar que llegó

En el chat nuevo, pega el prompt de calibración de `METODOLOGIA.md` §6. Si
responde «subagentes efímeros, `Explore` para leer, roles del proyecto, nada de
push ni despliegues sin tu OK», está instalado.

## Quitar

```bash
~/Proyectos/forma-de-trabajo/desinstalar.sh
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
