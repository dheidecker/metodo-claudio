# Plan de mecanismo

Fecha: 23-nov-2026. Estado: **plan aprobado en lo general, sin código**. Las preguntas abiertas (§7) las decide Derek.
Origen: sesión orquestadora en `~/Proyectos/mecanismo` (carpeta ya vacía, descartada).

## 0. Por qué existe

Inspiración: la charla de Lauren Tan (Cursor, unos 1000 PR/mes con agentes). La idea de fondo: **la confianza sale de verificar después, no de aprobar antes**.
`metodo-claudio` pone las reglas y `mecanismo` es el ciclo que las mantiene vivas:

1. **Trampas como datos más promoción**: un comentario o corrección que se repite pasa a ser una regla ejecutable (lint o hook) o una regla de metodología.
2. **Verificación con evidencia**: el agente demuestra que lo cambiado funciona (adaptador por tipo de proyecto).
3. **Permisos sin fricción**: los datos de aprobaciones proponen sacar de `ask` lo que siempre se aprueba.
4. **Evals** (más adelante): rúbrica más juez de otro modelo. Por ahora solo es un punto de extensión.

## 1. Decisiones tomadas (con su porqué)

| Decisión | Por qué |
|---|---|
| `mecanismo` vive **dentro de** `metodo-claudio/mecanismo/`, con un solo `instalar.sh` | Es un solo sistema: reglas más el ciclo que las mantiene, que evolucionan juntos. En otro PC basta un clone y un instalador |
| **Cero prompts de permiso nuevos** en el uso diario | Derek ya acepta demasiados prompts y el 99 % estaban bien. Dato: 2.055 aprobados por el clasificador, ~119 por el usuario y 1 solo rechazo |
| `deny` solo para lo irreversible y `ask` solo para publicar o lo irreversible (push, deploy, migraciones en prod). El resto se controla con hooks que avisan y con la puerta Stop | El mismo principio de verificar después |
| **Nada se activa solo**: el recolector escribe en `propuestas/` y `mecanismo aprobar` exige TTY | La memoria de un agente es observación, no política (METODOLOGIA §3). Exigir TTY evita que Claude se apruebe a sí mismo y no agrega prompts |
| Toda trampa nace **aviso** y la puerta de evidencia nace en **aviso** | Un bloqueo injusto es peor que un aviso |
| Las propuestas tienen **dos destinos**: trampa de código (YAML con prueba) o regla de metodología (diff de METODOLOGIA.md o CLAUDE.md) | Caso real: «orquesta varios agentes en paralelo» se pidió 24 veces en 9 proyectos (2-oct a 23-nov) porque el texto decía lo contrario. Se corrigió a mano en `9e12dd7` |
| Python 3.12 con stdlib más PyYAML (ya instalados) y bash solo para los shims | No hay Go en el host (mcp-sempat lo corre en Docker, demasiado lento para un hook), no hay yq y jq no lee YAML. Si falta PyYAML: exit 0 y `sin-pyyaml` en la bitácora |
| Se reutiliza `/fewer-permission-prompts` para la allowlist de lecturas | No duplicar. mecanismo aporta los conteos reales y el recorte de `ask` |

## 2. Árbol (`metodo-claudio/mecanismo/`)

`bin/mecanismo` (dispatcher) · `lib/comun.py` (bitácora, `redactar`, marca de sesión, archivos cambiados, iterar transcripts) · `lib/trampas/` · `lib/recolector/` (fuentes, agrupar, propuestas) · `lib/evidencia/` más `adaptadores/{mcp,web,lib}.py` · `lib/permisos/` · `hooks/{trampas,stop-evidencia}` · `esquemas/` · `prompts/` · `tests/` más `fixtures/{blade,mcp,web}` · `CONTRATO.md`.
El instalador es el `instalar.sh` de metodo-claudio, extendido, idempotente y con todas las rutas derivadas de `$AQUI`:
- Enlaza `~/.local/bin/mecanismo` → `$AQUI/mecanismo/bin/mecanismo`: si el enlace ya es suyo no hace nada, si está colgante lo rehace y si encuentra un archivo ajeno lo respalda.
- Comprueba que estén python3 y PyYAML.
- **Imprime** las reglas allow que hacen falta (`Bash(mecanismo trampas*|verificar*|recolectar*|permisos*)`, `Bash(chrome-devtools *)`) dentro del comando `jq` que ya imprimía. No toca `settings.json`.
- `desinstalar.sh` quita el enlace solo si apunta aquí.
- Se agregan a `plantilla-proyecto/.claude/hooks/` los shims `mecanismo-trampas.sh` y `stop-evidencia.sh`, que se enganchan en el `settings.json` de la plantilla sin tocar las entradas existentes.

`mecanismo init --tipo mcp|web|lib` deja en un proyecto:
- `.claude/mecanismo.yml`: tipo, cómo se arranca y modo de la puerta.
- `.claude/mapa-funciones.yml`: id, globs del código y cómo se llega a cada función (tool más caso, URL más pasos, o test).
- `.claude/trampas/*.yml` y `.claude/trampas/propuestas/`.
- `.claude/verificacion/{casos,golden}/`.
- `.claude/hooks/mecanismo-*.sh`: shims con `command -v mecanismo || exit 0`.
- `.claude/evidencia/` agregado al `.gitignore`.

## 3. Componentes

**C1 Trampas como datos.** Hook PostToolUse `Edit|Write`. Aplica las trampas cuyos globs casan con el archivo, solo sobre las líneas cambiadas respecto a HEAD (misma lógica que `blade-trampas.sh`). Responde exit 0 con `systemMessage`/`additionalContext`, o exit 2 si la trampa es de nivel `bloqueo`. En la bitácora escribe `AVISO <id> <archivo>`, compatible con `informe.sh`. El mismo motor corre en Stop sobre el árbol cambiado desde `/tmp/lint-marca-<sid>`, porque sed y heredoc no pasan por PostToolUse; sin git, usa `find -newer`. El campo `bloque` sirve para patrones de varias líneas. `mecanismo trampas --probar` ejecuta los casos `dispara` y `no_dispara`.

```yaml
id: tx-con-llamada-externa
nivel: aviso
globs: ["internal/**/*.go"]
bloque: {abre: '\.Begin(Tx)?\(', cierra: '\.(Commit|Rollback)\('}
patron: '\.Do\(|http\.(Get|Post)|sepa\.'
excepto: '//\s*mecanismo:ignorar'
mensaje: "Transacción abierta durante una llamada externa: ciérrala antes de llamar a SEPA."
origen: "trampa 35 de SEMPAT (sepa-mcp/docs/contexto/04 §10)"
prueba:
  dispara: "tx, _ := db.Begin(ctx)\nr, _ := cli.Do(req)\ntx.Commit(ctx)"
  no_dispara: "r, _ := cli.Do(req)\ntx, _ := db.Begin(ctx)\ntx.Commit(ctx)"
```

**C2 Recolector** (`mecanismo recolectar`, una CLI que corre fuera de los hooks).

Fuentes:
- `history.jsonl`: campos `.display`, `.project` y `.timestamp`.
- Transcripts: solo entradas `user` con `origin.kind=="human"`. Se descartan los textos de agent-message, task-notification y system-reminder.
- La bitácora de disparos.
- `gh api …/pulls/comments`, si hay remoto.
- Las trampas escritas en los `CLAUDE.md`, en tres formatos reales:
  - `### 10.N.` en `sempat/SEMPAT.md`.
  - Viñetas `- **…**` bajo `## Trampas` en mcp-sempat.
  - Lista numerada en `sepa-mcp/docs/contexto/04` §10.

Pipeline:
1. `redactar()` local antes de todo: JWT, `sk-`/`ghp_`, `Bearer`, Sanctum `\d+\|`, DSN, PEM y correos.
2. Caché por hash en `~/.claude/mecanismo/`.
3. `claude -p --bare --no-session-persistence --output-format json --json-schema` por lotes de ~300 prompts. Devuelve la instrucción canónica de cada prompt y su alcance (metodología, proyecto o ninguno).
4. Una segunda llamada fusiona las frases canónicas en grupos por significado.
5. Puntuación: ocurrencias × proyectos × días distintos, con umbral 3.

Propuestas:
- Si la regla ya está escrita y se sigue repitiendo, propone «subir de texto a hook».
- Con la bitácora propone subir de aviso a bloqueo (muchos disparos, todos corregidos) y podar (0 disparos en N días).
- Una trampa propuesta cuyo propio caso `dispara` no dispara se descarta.

**C3 Permisos** (`mecanismo permisos`). La fuente es el campo `permissionDecision` de los transcripts, así que no se agrega ningún hook en el día a día.

Medido el 23-nov:

| Origen de los diálogos | Cantidad |
|---|---|
| `git push` | 16 |
| `gcloud builds submit` | 5 |
| `gcloud run deploy` | 5 |
| `rm -rf` | 3 |
| `bq query` | 0 |

El resto de los diálogos son comandos compuestos (`bashMiss:too-complex`) y comandos sin regla (`no-rule-match`).

Qué propone:
- Pasar a allow lo que tiene N aprobaciones y 0 rechazos.
- Quitar las reglas `ask` que tuvieron 0 diálogos.
- Envolver los comandos compuestos en scripts permitidos.

Nunca propone allow para la lista fija de irreversibles y publicaciones. En F0, un hook canario comprueba qué eventos de permiso existen (PermissionRequest, `permission_prompt`) antes de depender de ellos.

**C4 Evidencia.** `mecanismo verificar [--funciones a,b]` escribe `.claude/evidencia/<ts>.json` con el comando, el resumen, las capturas, los diffs, HEAD y la huella sha256 de los archivos cambiados. Adaptadores:
- **MCP:** initialize → `tools/list` contra golden → `tools/call` por caso contra golden, ignorando los campos volátiles y con `divergencias` declaradas (formato de `mcp-sempat/testdata/golden/casos.yaml`).
- **Web:** CLI `chrome-devtools`: captura, red sin 4xx/5xx y consola sin errores.
- **Librería:** el comando de tests declarado.

El hook Stop `stop-evidencia` es aparte de `stop-lint`, que no se toca, y no ejecuta la verificación: solo comprueba que exista.
- Con `stop_hook_active`, exit 0.
- Cruza los archivos cambiados con el mapa de funciones.
- Si falta evidencia vigente: en modo aviso, exit 0 con `systemMessage`; en modo bloqueo, exit 2 con el comando exacto que hay que correr.
- Los archivos que no están en el mapa no exigen evidencia, pero se anotan.

**Evals (extensión).** Los `adaptadores/` y `evidencia.json` son el contrato de entrada de un futuro `mecanismo evaluar`.

## 4. Fases y frentes (ancho por defecto, en serie solo si hay dependencia)

- **F0, el orquestador en serie:**
  - Rama `mecanismo` desde `main`, sin incluir `hooks/statusline.sh`.
  - `mecanismo/CONTRATO.md` con los esquemas (trampa, propuesta, evidencia, `mecanismo.yml`, mapa, línea de bitácora) y las firmas `lib/<x>/cli.py:main(argv)`.
  - `lib/comun.py`, congelado a partir de aquí.
  - Hook canario de permisos.
  - Prueba: `cd mecanismo && python3 -m unittest tests.test_contrato` y el canario anotado en la bitácora.
- **Frentes en paralelo**, cada uno con carpetas disjuntas y su propio worktree: `git worktree add ../metodo-claudio-wt-<X> -b mecanismo-<X> mecanismo`. Antes de trabajar, cada frente corre `merge --ff-only mecanismo`. **Ninguno toca `hooks/statusline.sh`**, que tiene cambios sin commitear de Derek.

| Frente | Qué construye | Prueba |
|---|---|---|
| **A, trampas** | `lib/trampas`, `hooks/trampas`, `fixtures/blade` | `tests/migracion_blade.sh`: el `blade-trampas.sh` original y `mecanismo trampas` dan listas (archivo, línea, id) idénticas, con 20 invocaciones de menos de 300 ms cada una |
| **B, recolector** | `lib/recolector`, `prompts/` | Offline con un `claude` falso (`MECANISMO_CLAUDE=fixtures/fake-claude`). Canario de redacción: `grep -r CANARIO ~/.claude/mecanismo propuestas/` tiene que dar vacío |
| **C, evidencia** | `lib/evidencia`, `adaptadores`, `fixtures/{mcp,web}` con un servidor MCP de prueba en Python | `mcp-ok` da ok y `mcp-roto` falla con el diff. Una página con un 404 y un `console.error` falla y nombra ambos. `stop-evidencia` alimentado por stdin: aviso → 0, bloqueo → 2, activo → 0, vigente → 0 |
| **D, permisos** | `lib/permisos` | `mecanismo permisos --dias 90` reproduce los conteos de §3. Un test unitario comprueba que nunca propone allow para un irreversible |
| **E, instalación** | `bin/`, `instalar.sh`, `desinstalar.sh`, `init`, los shims de la plantilla, `README.md` y `.gitignore`. También la **reescritura del `CLAUDE.md` de metodo-claudio**, que hoy dice «no hay nada que desarrollar aquí» y pasará a decir: `METODOLOGIA.md`, `hooks/` y la plantilla se instalan y no se adaptan; `mecanismo/` sí se desarrolla, con sus pruebas (`cd mecanismo && python3 -m unittest discover -s tests -t .`) y su `CONTRATO.md`; y no se tocan `statusline.sh` ni las piezas existentes salvo encargo | `./instalar.sh` dos veces: la segunda dice «sin cambios», deja respaldo y no hay rutas escritas a mano. `bash -n` limpio. `git diff main -- hooks/statusline.sh` vacío |

- **Integración (orquestador):** merge de A–E en `mecanismo` y después en `main`, previa autorización de Derek. El diff de `statusline.sh` tiene que seguir vacío.

- **Aceptación real, después de B:** `mecanismo recolectar --fuente history` sobre el `history.jsonl` actual. El grupo «orquesta varios agentes en paralelo» tiene que salir entre las 3 primeras propuestas, con destino *regla de metodología*, en 3 corridas de 3, y marcado «ya documentada en 9e12dd7; vigilar si se repite».
- **Después de A y C:** el piloto en sepa-mcp (§5).
- **Después de A:** la migración de `blade-trampas.sh` a `plantilla-proyecto/.claude/trampas/blade.yml`, dejando el `.sh` como shim, en un commit aparte.
- **Prueba de cero fricción:** una sesión de prueba hace Edit, Stop y `mecanismo verificar`, y su transcript tiene 0 entradas `permissionDecision.source=="user_temporary"`.
- **Antes de cerrar:** `/code-review` más un revisor fresco contra este plan.

## 5. Piloto: sepa-mcp (Go, servidor MCP; hoy solo tiene `docs/`)

`mecanismo init --tipo mcp`. Las trampas semilla vienen de `docs/contexto/04` §10:

| N.º | Trampa |
|---|---|
| 8 | `err.Error()` en logs, o `fmt.Errorf` con `%v` sobre `err` |
| 35 | Transacción abierta durante una llamada externa |
| 7 | `EXCLUDED\.` en un upsert |
| 28 | `ARRAY\(SELECT` en el SQL de BigQuery |
| — | `sempat` en `*.go` o `*.sql`: criterio de aceptación del frente 0 de `plan-fase1.md` |

Sin código Go todavía, se valida con `mecanismo trampas --probar`. El adaptador MCP, contra `make servir-falso` (backend SEPA falso más `fakes.Querier`), verifica:
- `tools/list` = `mis_accesos`, `consultar` y `buscar_codigo`, con las anotaciones ReadOnly, Idempotent y OpenWorld=false, descripciones de menos de 2.000 bytes y sin `listChanged`.
- El golden de cada tool, ignorando `query_id`, `request_id` y `firma`.
- La métrica `flete` devuelve `PARAMETRO_INVALIDO`, y `/mcp` sin token devuelve 401.
- Ninguna salida contiene `rut_cliente`, `SELECT `, `eyJ` ni `\d+\|`.

## 6. Archivos clave

- `plantilla-proyecto/.claude/hooks/{blade-trampas,stop-lint}.sh`, `hooks/informe.sh`
- `~/Proyectos/sepa-mcp/docs/contexto/04-sempat-mcp-arquitectura.md`
- `~/Proyectos/mcp-sempat/testdata/golden/casos.yaml`

## 7. Preguntas abiertas (recomendación entre paréntesis)

1. ¿Puede `claude -p` gastar cuota sobre el history ya redactado? (Sí, con Haiku para clasificar, Sonnet para fusionar y `--max-budget-usd 2` por corrida)
2. ¿La puerta de evidencia sube a bloqueo tras 2 semanas sin bloqueos injustos? (Sí, pero lo propone el propio mecanismo con datos; no se cambia por calendario)
3. ¿`bq query` pasa a allow con un hook que obligue a usar `--maximum_bytes_billed`? ¿`git push` a ramas que no son main pasa a allow? (Sí a ambas: eso quita 16 de los diálogos medidos. Push a main y `--force` se quedan en ask y deny)
4. ¿sepa-mcp incluye `make servir-falso` y un token de desarrollo? (Sí: es la base del adaptador MCP)
5. ¿El estado agregado se guarda en `~/.claude/mecanismo/`? (Sí)
6. ¿Commiteas tú los cambios de `hooks/statusline.sh` antes de crear la rama `mecanismo`? (Da igual: los worktrees parten de `main` y el archivo queda fuera de todos modos)
