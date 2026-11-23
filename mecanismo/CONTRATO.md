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
