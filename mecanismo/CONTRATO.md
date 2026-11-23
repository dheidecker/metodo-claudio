# Contrato de mecanismo (v1)

Fijado en F0, antes de lanzar los frentes. Lo que está aquí no se cambia dentro de un frente:
si un frente necesita cambiarlo, lo dice en su entrega y lo decide el orquestador en la integración.
El porqué de cada pieza está en `PLAN.md`.

## 1. Disposición y cómo se corre

```
mecanismo/
  bin/mecanismo            dispatcher bash (E)
  lib/__init__.py          vacío
  lib/comun.py             CONGELADO (F0)
  lib/trampas/             (A)  cli.py:main(argv) -> int ; motor.py
  lib/recolector/          (B)  cli.py:main(argv) -> int
  lib/propuestas/          (B)  cli.py:main(argv) -> int   (listar / aprobar / rechazar)
  lib/evidencia/           (C)  cli.py:main(argv) -> int ; adaptadores/{mcp,web,lib}.py
  lib/permisos/            (D)  cli.py:main(argv) -> int
  lib/init/                (E)  cli.py:main(argv) -> int
  hooks/trampas            (A)  python3 ejecutable: PostToolUse Edit|Write y modo --stop
  hooks/stop-evidencia     (C)  python3 ejecutable: Stop
  hooks/canario-permisos   (F0) python3 ejecutable
  esquemas/*.schema.json   F0: trampa, propuesta, evidencia, mecanismo, mapa
  prompts/                 (B)
  tests/                   test_<frente>_*.py ; fixtures/{blade,mcp,web,...}
```

- Solo Python 3.12 stdlib + PyYAML. Bash solo en `bin/mecanismo` y en los shims.
- Todo módulo importa así: `from lib import comun` (la raíz `mecanismo/` va en `sys.path`).
- Tests: `cd mecanismo && python3 -m unittest discover -s tests -t .` Cada frente nombra los
  suyos `tests/test_<a|b|c|d|e>_*.py` para no pisarse.
- Ningún test escribe en el `~/.claude` real: usan `CLAUDE_HOME`, `MECANISMO_HOME` y
  `MECANISMO_BITACORA` apuntando a un `tempfile.mkdtemp()`.
- Sin PyYAML: los hooks salen con `exit 0` y anotan `sin-pyyaml` en la bitácora; la CLI dice
  `instala python3-yaml` y sale con 4.

## 2. Dispatcher y CLI (`bin/mecanismo`, frente E)

`bin/mecanismo` resuelve su ruta real (`readlink -f`), pone `mecanismo/` en `PYTHONPATH` y llama
`python3 -P -c 'import sys; from lib.<x>.cli import main; sys.exit(main(sys.argv[1:]))' "$@"`
(`-P`: sin él, un proyecto con su propio `lib/` tapa el nuestro).

| Subcomando | Paquete | Uso mínimo |
|---|---|---|
| `trampas` | lib.trampas | `--probar [dir]`, `--archivo F`, `--arbol [--sid S]` |
| `recolectar` | lib.recolector | `--fuente history\|transcripts\|bitacora\|gh\|claudemd\|todas`, `--dias N`, `--sin-modelo` |
| `propuestas` | lib.propuestas | sin args lista; `ver ID` |
| `aprobar` / `rechazar` | lib.propuestas | `ID` — exige TTY (`comun.exige_tty`) |
| `verificar` | lib.evidencia | `[--funciones a,b]` |
| `permisos` | lib.permisos | `--dias N`, `--json` |
| `init` | lib.init | `--tipo mcp\|web\|lib [dir]` |
| `hook <nombre>` | `hooks/<nombre>` | lo que llaman los shims; stdin = JSON del hook |

Exit codes de la CLI: 0 ok · 1 la comprobación falló (p. ej. `verificar` con un caso roto) ·
2 uso incorrecto · 3 falta TTY · 4 falta PyYAML.

## 3. Trampa (`.claude/trampas/*.yml`)

Un archivo contiene **una trampa** (mapping) **o una lista** de trampas. `esquemas/trampa.schema.json`.

| Campo | Tipo | Oblig. | Significado |
|---|---|---|---|
| `id` | slug `[a-z0-9-]+` | sí | único en el proyecto |
| `nivel` | `aviso` \| `bloqueo` | sí | toda trampa nace `aviso` |
| `globs` | lista | sí | relativos a la raíz del proyecto; `**` cruza carpetas (`fnmatch` sobre la ruta relativa, más el caso `**/` = cero o más carpetas) |
| `patron` | regex Python | sí | se busca línea a línea (`re.search`) |
| `excepto` | regex | no | si la línea casa, no cuenta |
| `bloque` | `{abre, cierra}` regex | no | `patron` solo cuenta dentro de un bloque: abre en la línea que casa `abre` (incluida), cierra tras la línea que casa `cierra` (incluida). Un bloque reporta **solo su primer acierto**. Un `abre` dentro de un bloque lo reinicia |
| `mensaje` | str | sí | lo que lee Claude |
| `origen` | str | sí | de dónde salió (caso real) |
| `prueba` | `{dispara: str, no_dispara: str}` | sí | `mecanismo trampas --probar` exige que `dispara` dé ≥1 y `no_dispara` dé 0 |
| `max` | int | no (3) | aciertos por archivo y trampa, contados **después** de filtrar líneas cambiadas |

Acierto = `(archivo, línea, id)`. Solo cuentan las líneas de `comun.lineas_cambiadas()`
(None = todo el archivo). Salida del hook: `comun.salida_hook("PostToolUse", msg, bloquear)` con
`bloquear` = alguna trampa `bloqueo` acertó. Bitácora: una línea por trampa acertada
`hook=trampas`, resultado `AVISO <id> <archivo-base>` o `BLOQUEO <id> <archivo-base>`;
sin aciertos `silencio <archivo-base>`.

Modo Stop (`hooks/trampas --stop`): mismo motor sobre `comun.archivos_cambiados(raiz, comun.desde_sesion(sid))`,
solo avisa (`systemMessage`), nunca bloquea; respeta `stop_hook_active`.

## 4. Propuesta

Global: `~/.claude/mecanismo/propuestas/<id>.yml` (`comun.estado_dir()/propuestas`).
Trampa de un proyecto: `<proyecto>/.claude/trampas/propuestas/<id>.yml`.
**Nada se activa solo**: solo `mecanismo aprobar ID` (con TTY) la mueve a su destino.

```yaml
id: orquestar-en-paralelo-3f2a9c1b      # slug + 8 hex de sha256(texto canónico)
estado: pendiente                        # pendiente | aprobada | rechazada
creada: 2026-11-23T11:04:05-03:00
origen: recolector                       # recolector | permisos | bitacora
tipo: regla-metodologia                  # ver tabla
destino: metodologia                     # trampa | metodologia | proyecto | permisos
resumen: "Orquesta varios agentes en paralelo"     # una línea, ya redactada
evidencia:
  ocurrencias: 24
  proyectos: [sempat, tickets, ...]
  dias: 17
  puntuacion: 7344                       # ocurrencias × proyectos × días
  ejemplos: ["...", "..."]               # ≤3, pasados por comun.redactar
contenido: {}                            # según destino (abajo)
nota: "ya documentada en 9e12dd7; vigilar si se repite"
```

| `tipo` | `destino` | `contenido` |
|---|---|---|
| `trampa-nueva` | trampa | `{trampa: <mapping §3, nivel aviso>, proyecto: <ruta>}` |
| `regla-metodologia` / `regla-proyecto` | metodologia / proyecto | `{archivo: <ruta>, diff: <unified diff>}` (vacío si solo hay texto propuesto: `{archivo, texto}`) |
| `subir-a-hook` | trampa | igual que `trampa-nueva`; la regla ya está escrita y se sigue repitiendo |
| `subir-a-bloqueo` / `podar` | trampa | `{archivo: <yml>, id: <trampa>, disparos: N, dias: N}` |
| `permiso-allow` / `permiso-quitar-ask` / `envolver-script` | permisos | `{lista: allow\|ask, accion: agregar\|quitar, regla: "Bash(...)", comando_jq: "..."}` |

`aprobar` de un destino `permisos` o `metodologia` **imprime** el comando o el diff a aplicar:
nunca toca `settings.json` ni `METODOLOGIA.md` por su cuenta.

## 5. Evidencia (`<proyecto>/.claude/evidencia/<ts>.json`, en `.gitignore`)

```json
{
  "version": 1,
  "ts": "2026-11-23T11:04:05-03:00",
  "proyecto": "/abs/ruta",
  "head": "<sha de HEAD o null>",
  "tipo": "mcp",
  "ok": false,
  "funciones": [
    {"id": "consultar", "ok": false, "comando": "mecanismo verificar --funciones consultar",
     "resumen": "1 de 3 casos difiere", "capturas": [], "diffs": ["--- golden\n+++ actual\n..."],
     "duracion_ms": 812}
  ],
  "huellas": {"internal/consultar/x.go": "<sha256>"}
}
```

`huellas` = `comun.sha256_archivo` de cada archivo cambiado que el mapa asigna a alguna función
verificada, ruta relativa a la raíz del proyecto.
**Vigente** para un archivo F: existe una evidencia con `huellas[F]` = sha256 actual de F y cuya
función que cubre F tiene `ok: true`. `stop-evidencia` solo lee, no verifica.

## 6. `.claude/mecanismo.yml` y `.claude/mapa-funciones.yml`

```yaml
# mecanismo.yml
version: 1
tipo: mcp                       # mcp | web | lib
puerta: aviso                   # aviso | bloqueo — nace aviso
arranque: "make servir-falso"   # opcional: cómo se levanta lo que se verifica
mcp:  {url: "http://localhost:8080/mcp", token_env: "MCP_TOKEN", golden: ".claude/verificacion/golden",
       ignorar: [query_id, request_id, firma]}      # o {comando: "python3 servidor.py"} para stdio
web:  {base_url: "http://localhost:8000"}
lib:  {tests: "python3 -m unittest"}
```

```yaml
# mapa-funciones.yml
funciones:
  - id: consultar
    globs: ["internal/consultar/**", "internal/sql/*.sql"]
    mcp:  {tool: consultar, casos: ".claude/verificacion/casos/consultar.yaml"}
  - id: login
    globs: ["resources/views/auth/**"]
    web:  {url: "/login", pasos: ["fill #email x", "click button[type=submit]"]}
  - id: parser
    globs: ["src/parser/**"]
    test: "python3 -m unittest tests.test_parser"
```

Cada función lleva exactamente una vía: `mcp`, `web` o `test`.

## 7. Bitácora (`~/.claude/metodo-claudio.log`, la misma de los hooks bash)

`comun.bitacora(hook, resultado)` →
`2026-11-23 11:04:05 | <hook, 22 col>           | <proyecto, 32 col>                | <RESULTADO> <detalle>`
Categorías (primer token): `ok`, `silencio`, `AVISO`, `BLOQUEO`, `inicio`, `sin-pyyaml`, `error`, `EVENTO`.
Nombres de hook: `trampas`, `trampas-stop`, `stop-evidencia`, `canario-permisos`, `verificar`.
`hooks/informe.sh` agrupa por hook y primer token: no inventar categorías nuevas sin añadirlas aquí.

## 8. `lib/comun.py` (congelado)

Rutas: `claude_home()`, `estado_dir()`, `bitacora_path()`, `raiz_mecanismo()`, `raiz_proyecto(cwd)`.
Bitácora: `bitacora(hook, resultado, proyecto=None)`.
Redacción: `redactar(texto)` — PEM, DSN con credenciales, JWT, Bearer, `sk-`, `gh*_`/`github_pat_`,
Sanctum `\d+|…`, correos → `[REDACTADO:<tipo>]`.
Sesión y cambios: `marca_sesion(sid)`, `desde_sesion(sid)`, `repos_de(base)`,
`archivos_cambiados(base, desde)`, `lineas_cambiadas(archivo)`, `sha256_archivo(archivo)`.
Transcripts: `iterar_transcripts(dias, proyecto)`, `es_prompt_humano(e)`, `texto_de(e)`, `iterar_history(dias)`.
Hooks y YAML: `leer_yaml(path)` (lanza `SinPyYAML`), `leer_stdin_json()`, `salida_hook(evento, msg, bloquear)`,
`exige_tty(accion)`.

## 9. Datos reales que ya se comprobaron (F0, 23-nov, Claude Code 2.1.330)

- Transcript: entrada `user` con `origin.kind` = `human` (persona), `peer` (otro agente) o sin `origin`
  (tool_result). `permissionDecision` vive en la entrada `user` que trae el `toolUseResult`:
  `{decision, source: config|user_temporary, reasonType?, reasonCode?, ruleSource?, grantScope?}`.
  `reasonCode` real: `bashMiss:too-complex`, `bashMiss:no-rule-match`, `rule:userSettings`, `unknown`,
  `subcommands:…+rule:userSettings`.
- `history.jsonl`: `{display, pastedContents, timestamp (ms), project, sessionId}`.
- Eventos de hook presentes en el binario: `PermissionRequest`, `PermissionDenied`,
  `Notification` con `notification_type: permission_prompt`. El canario (`hooks/canario-permisos`)
  confirma cuáles disparan de verdad en el uso diario; C3 no depende de ellos (lee `permissionDecision`).
- Canario real (`claude -p --settings`, Haiku, `--permission-mode default`, un `mkfifo` sin regla):
  disparó **`PermissionRequest` (tool_name=Bash)**; `PermissionDenied` y `Notification` no dispararon
  en modo `-p`. Bitácora: `2026-11-23 11:11:00 | canario-permisos | proy | EVENTO PermissionRequest Bash`.
  Falta verlo en una sesión interactiva: el instalador imprime el snippet para engancharlo.

## 10. Enmiendas de la integración (23-nov, pedidas por los frentes)

Mandan sobre lo anterior donde choquen.

- **Hooks Stop imprimen solo `{"systemMessage": …}`** (como `stop-lint.sh`): `comun.salida_hook` añade
  `hookSpecificOutput`, que Stop no admite. `salida_hook` queda para PostToolUse. Aplica a
  `hooks/trampas --stop` y `hooks/stop-evidencia`.
- **`lib.propuestas`** recibe `argv` con el subcomando delante: `propuestas [ver ID|--todas|--json]` →
  `main(X)`, `aprobar ID` → `main(["aprobar", ID])`, `rechazar ID` → `main(["rechazar", ID])`.
  Una propuesta aprobada o rechazada se queda en `propuestas/` con su `estado`, para que su id no
  vuelva a proponerse. `subir-a-bloqueo` y `podar` al aprobarse imprimen el cambio; no editan el yml.
- **`mecanismo hook X`**: si falta `hooks/X`, exit 0 y `error` en la bitácora (un fallo de instalación
  nunca bloquea una sesión); nombre inválido, exit 2.
- **Trampas**: `silencio` solo se anota si el proyecto tiene `.claude/trampas/`; una trampa inválida se
  salta y deja `error trampa-invalida <id>`. CLI extra: `--trampas DIR`, `--cambiadas`; `--archivo` y
  `--arbol` salen con 1 si hay aciertos. `cargar_trampas(dir, errores=None)`.
- **Evidencia**: la cola de salida de una vía `test` va a `.claude/evidencia/<ts>-<id>.log`, citada en
  `capturas` (y en `diffs` si falla). `verificar` añade `--grabar-golden`, `--sid`, `--json`, escribe
  `.claude/evidencia/.gitignore` con `*`, y levanta `arranque` solo si nada escucha (y lo mata al final).
  `mecanismo.yml` admite opcionales `mcp.timeout`, `web.ignorar_red` (por defecto `/favicon.ico`),
  `web.timeout`, `web.espera_ms`, `lib.timeout`.
  Goldens MCP: `<golden>/tools-list.json` y `<golden>/<tool>/<caso>.json`; una divergencia casa con la
  ruta aplanada (`content/0/text/meta/version`) exacta, por glob o por prefijo.
- **Recolector**: `--proyecto`, `--top`; tercera llamada `trampas` (Sonnet) solo con `--fuente claudemd`.
  Entorno: `MECANISMO_CLAUDE`, `MECANISMO_GH`, `MECANISMO_PRESUPUESTO_USD` (solo baja el tope de 2),
  `MECANISMO_LOTE`, `MECANISMO_MODELO_<TAREA>`, `MECANISMO_TIMEOUT`.
- **Permisos**: `--proponer`, `--min N`, `--subagentes` (lector propio de `subagents/`, que
  `comun.iterar_transcripts` no recorre). `contenido` de permisos admite `script`, `mantener`,
  `variantes`, `quitar_de_ask`. «Diálogo» = `source == user_temporary` o `decision != accept`;
  AskUserQuestion/ExitPlanMode se cuentan aparte. Lista de nunca-allow: `lib/permisos/familias.NUNCA_ALLOW`.

## 11. Enmiendas tras la revisión (23-nov)

- **`exige_tty`**: además de TTY, se niega si `CLAUDECODE` está en el entorno (todo Bash de Claude Code
  lo trae; `script -qec` da TTY pero no lo quita). Sin bypass por entorno: los tests usan
  `unittest.mock.patch("lib.comun.exige_tty")`. `aprobar` pide además teclear el id. Es disuasión; la
  frontera real es `permissions.deny` con `Bash(mecanismo aprobar*)`, `Bash(mecanismo rechazar*)`,
  `Bash(mecanismo confiar*)` y `Bash(script *)`, que imprime `instalar.sh`.
- **`redactar`**: un PEM sin `-----END` (texto cortado) se redacta hasta el final. Regla para todos:
  **redactar antes de cortar**, nunca `redactar(t[:n])`.
- **Confianza de comandos del proyecto** (como `direnv allow`): `verificar` ejecuta `test`, `arranque` y
  `mcp.comando` con shell solo si el sha256 de `.claude/mecanismo.yml` + `.claude/mapa-funciones.yml`
  está en `~/.claude/mecanismo/confianza.json` para esa raíz. Si no, no ejecuta nada, da `ok: false`,
  exit 1 y dice «corre `mecanismo confiar` tú». `mecanismo confiar [dir]` (lib.evidencia.confianza,
  `main(argv)`; `es_confiable(raiz) -> bool`) muestra los comandos, exige TTY y guarda el hash.
  Así `Bash(mecanismo verificar*)` en allow no es una puerta a ejecutar lo que un agente escriba en el yml.
- **Propuesta `subir-puerta`** (destino `proyecto`): la puerta de evidencia de un proyecto pasa de
  `aviso` a `bloqueo` cuando la bitácora de `stop-evidencia` lo justifica (§7.2: la propone el
  mecanismo con datos, no el calendario). `contenido: {archivo: .claude/mecanismo.yml, diff}`.
- **Ids estables**: una propuesta nueva cuyo grupo coincide en significado con una existente actualiza la
  existente en vez de crear otra (la fusión recibe los resúmenes de las propuestas vigentes).

## 12. Juez de permisos (frente F, hook `PermissionRequest`)

Las reglas `ask` de deploy, `rm -rf`, `git push`, `gcloud run jobs execute` y `docker push` **se mantienen**:
abren el diálogo, y el hook decide antes de que se muestre (Derek, 23-nov: ninguna de estas familias le
muestra ya un diálogo; un agente decide y él lo revisa después con `mecanismo juez`). Si `mecanismo` no
está o el juez falla, vuelve el diálogo humano (fail-safe).

- **Piezas.** `hooks/juez-permisos` (python3) → `lib/juez/hook.py:main(t0)`; `lib/juez/{reglas,contexto,
  llamada,auditoria,cli}.py`; `prompts/juez.md` + `juez.schema.json`. CLI: `mecanismo juez [--ultimas N]
  [--negadas] [--json]` (`lib.juez.cli:main(argv)`). Snippet (lo imprime `instalar.sh`, lo aplica Derek):
  `PermissionRequest`, matcher `Bash`, `mecanismo hook juez-permisos`, timeout 90.
- **Entrada** (stdin): `{hook_event_name, tool_name, tool_input.command, cwd, session_id, transcript_path,
  permission_suggestions?}`.
- **Salida.** Permitir: `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}},
  "systemMessage":"juez: permitido — <motivo>"}`. Negar: `decision: {"behavior":"deny","interrupt":false,
  "message":"Juez de permisos: <motivo>. Si es correcto, explica por qué o pídeselo a la persona."}` y
  `systemMessage: "juez: negado — <motivo>"`. **Sin salida y exit 0** = no decide (diálogo normal). Nunca exit 2.
- **Guardas.** `MECANISMO_JUEZ_ANIDADO=1` → exit 0 sin salida (lo pone el propio juez en su `claude -p`, que
  además corre con `--setting-sources project` en `estado_dir()/vacio`, o `--bare` con API key, y `--tools ""`).
  `tool_name != Bash` → sin salida.
- **Qué juzga.** Familias de `lib/permisos/familias` presentes en **cualquier** subcomando. Por defecto
  `gcloud run deploy`, `gcloud builds submit`, `rm -rf`, `gcloud run jobs execute`, `docker push` y `git push`
  (`reglas.FAMILIAS_POR_DEFECTO`, con los nombres de `familias`); se cambia con `estado_dir()/juez.yml`
  (`familias: [...]`; PyYAML solo si el archivo existe). Si además hay otra irreversible o sensible **no** configurada
  (`rm -rf build && kubectl apply …`), no decide (`silencio fuera-de-juez <familia>`): un allow aprobaría el
  comando entero. Las reglas deterministas (rm, push) corren aunque su familia no esté configurada, y un
  NIEGA de cualquiera manda; PERMITE por regla solo si **todas** las familias juzgadas tienen PERMITE de regla.
- **Reglas de `rm -rf`** (deterministas, < 300 ms, antes del modelo; cada objetivo resuelto contra el `cwd`,
  siguiendo los `cd` del propio comando, con `~`/`$HOME` expandidos, en forma léxica y `realpath`, gana la peor):
  NIEGA variable o sustitución sin expandir, glob en `/` o `$HOME`, `/`, `$HOME`, `~/.claude` (y `CLAUDE_HOME`) o
  dentro, cualquier `.git`, la raíz del proyecto (`comun.raiz_proyecto(cwd)`) o un ancestro, un glob `*` en la
  raíz, y todo lo de fuera del proyecto que no esté **estrictamente** bajo `/tmp`. PERMITE si todos los objetivos
  son efímeros dentro del proyecto (algún componente en `build dist node_modules __pycache__ .cache tmp
  .pytest_cache coverage target .next`) o están bajo `/tmp`, y el resto del comando es `cd` o trivial. Lo demás,
  al modelo.
- **Reglas de `git push`** (deterministas, < 300 ms, antes del modelo). Cada push del comando se resuelve en
  su repo (`git -C <cwd>`, siguiendo los `cd` y `-C` del comando) contra la rama actual y el destino real: el
  refspec explícito (`src:dst`, `HEAD`, `refs/heads/…`) o, sin él, todos los candidatos (rama actual, upstream
  y `@{push}`; gana el peor). Remoto: el posicional, `--repo`, o `branch.<r>.pushRemote` / `remote.pushDefault` /
  `branch.<r>.remote` / `origin`. NIEGA `--force`, `-f` (también en `-uf`), `--force-with-lease[=…]`,
  `--force-if-includes`, `--mirror`, `--delete`/`-d`, `--prune`, refspec con `+`, `:rama` y un remoto con nombre
  que no existe (salvo `git remote add` en el mismo comando: al modelo). PERMITE si todos los destinos son ramas
  no protegidas, sin flags fuera de una lista corta (`-u`, `--set-upstream`, `-v`, `-q`, `-n`, `--no-verify`…),
  esté el árbol limpio o no, y el resto del comando es `cd`, git local (`add commit status log diff fetch show
  rev-parse`), `echo`/`tail`/`head`/`cat`/`grep`/`wc` o trivial, sin sustituciones (salvo
  `-m "$(cat <<'EOF' … EOF)"`) ni redirecciones que no sean `2>&1`/`/dev/null`. Protegidas:
  `main|master|prod*|release*` (también `production`). Al modelo: rama protegida, tags (`--tags`,
  `--follow-tags`, `refs/tags/…`, `v<dígito>…`, o un tag local), `--all`, URL o ruta como destino, HEAD
  separado, comodines, `-c`/`--git-dir` globales, `-o`, envoltorios (`xargs git push`), variables o
  sustituciones, y cualquier flag desconocido.
- **Juez modelo** (siempre para los deploy, `gcloud run jobs execute` y `docker push`): Sonnet, `--json-schema`
  `{decision: permitir|negar, motivo ≤200, riesgo: bajo|medio|alto}`, `--max-budget-usd 0.10`, timeout 45 s (`MECANISMO_JUEZ_TIMEOUT`,
  `MECANISMO_MODELO_JUEZ` para tests). Contexto: comando, cwd, familias, nota de las reglas, rama, `git status
  --short` (≤30 líneas), 5 asuntos de commit, 5 últimos prompts humanos y el último texto del asistente.
  Para `git push`, además `push: [{remoto, origen, rama_destino, rama_remota_existe, commits_a_subir (git log --oneline, ≤20), total_commits,
  remoto_por_delante}]` (sin fetch: rango contra `refs/remotes/<remoto>/<dst>`, si no `@{u}`, si no
  `--not --remotes=<remoto>`); el prompt pregunta si la persona pidió publicar y si los commits son los de la
  sesión.
  **Todo** pasa por `contexto.redactar` (= `comun.redactar` más valores de `--set-env-vars`/`--set-secrets`/…,
  `*PASS*|*SECRET*|*TOKEN*|*KEY*=valor` y `--*password*|token|secret valor`) **antes** de cortar.
- **Fallos** (timeout, sin `claude`, JSON inválido o fuera del esquema, config inválida, sin PyYAML con
  `juez.yml`, excepción): exit 0 sin salida, `error <tipo>` en la bitácora (`timeout`, `sin-claude`,
  `json-invalido`, `modelo`, `salida-vacia`, `config-invalida`, `sin-pyyaml`, `excepcion <Clase>`).
- **Bitácora** (amplía §7, hook `juez-permisos`): `PERMITE <familia> regla|modelo`, `NIEGA <familia> <motivo
  corto>`, `silencio fuera-de-juez <familia>`, `error <tipo>`. `<familia>` une varias con `+`.
- **Auditoría**: una línea JSON por decisión en `estado_dir()/juez/AAAA-MM.jsonl`:
  `{ts, proyecto, cwd, comando (redactado), familia, via: regla|modelo, decision: permitir|negar, motivo,
  riesgo, duracion_ms, costo_usd?}`. `duracion_ms` cuenta desde que arranca el proceso del hook.

## 13. Mensajes a mitad de turno (23-nov)

Lo que la persona escribe mientras Claude trabaja no queda como entrada `user`: queda como
`{"type": "attachment", "attachment": {"type": "queued_command", "prompt": …, "commandMode": "prompt",
"origin": {"kind": "human"}}}`. `comun.es_prompt_humano` y `comun.texto_de` los incluyen (solo modo
`prompt`, no los `!comando`). Sin esto el juez negó un push que la persona había pedido a mitad de turno.
