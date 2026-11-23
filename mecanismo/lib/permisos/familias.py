"""Familias de comandos: partir un comando compuesto y clasificarlo por su subcomando más grave.

Un comando compuesto (`cd x && git push`) pertenece a la familia de su subcomando «peligroso»:
se parte por `&&`, `||`, `;`, `|` y saltos de línea (fuera de comillas, sin el cuerpo de los
heredoc) y se queda con la familia más grave. Las comillas se enmascaran antes de buscar
familias de shell, para que `git commit -m "no hagas git push"` no cuente como push; el SQL
(`DROP`/`TRUNCATE`) se busca en el texto entero, porque siempre viaja entre comillas o en un heredoc.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

# ------------------------------------------------------------------------------------------------
# LISTA FIJA DE IRREVERSIBLES Y PUBLICACIONES.
#
# Ninguna de estas familias recibe NUNCA una propuesta `permiso-allow`, tenga las aprobaciones
# que tenga (PLAN §3 C3, METODOLOGIA §5: push, despliegues y migraciones en producción se
# autorizan cada vez). No se poda con datos: un 100 % de aprobaciones de `rm -rf` no dice que
# el próximo sea inocente. Para ampliar la lista, se añade aquí con su porqué; para quitar algo,
# lo decide Derek, no un agente.
#
# Orden = gravedad: en un comando compuesto gana la primera familia de la lista que aparezca.
# ------------------------------------------------------------------------------------------------
_INI = r"(?:^|[\s(`{])"   # inicio de comando: tras espacio, `(`, `$(`, backtick o `{`
_GIT = _INI + r"git(?:\s+-[cC]\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+"

IRREVERSIBLES: list[tuple[str, str]] = [
    # (familia, por qué es irreversible o es una publicación)
    ("git push", "publica; a main/master o con --force/-f/--force-with-lease reescribe lo compartido"),
    ("gcloud run deploy", "despliegue a producción"),
    ("gcloud builds submit", "construye y publica una imagen (paso de despliegue)"),
    ("gcloud run jobs execute", "ejecuta un job contra producción"),
    ("deploy", "despliegues en general: firebase/fly/vercel/gcloud app|functions deploy, make|npm run deploy, deploy.sh"),
    ("migrate prod", "migración en producción: migrate --force, en prod, o migrate:fresh|refresh|rollback|reset"),
    ("DROP/TRUNCATE", "borra tablas o datos sin vuelta atrás"),
    ("rm -rf", "borrado recursivo sin papelera"),
    ("kubectl apply/delete", "cambia el clúster"),
    ("terraform apply", "cambia infraestructura real (también destroy)"),
    ("npm publish", "publica un paquete (también yarn/pnpm publish)"),
    ("gh pr merge", "fusiona en la rama compartida"),
    ("gh release", "publica una versión"),
    ("docker push", "publica una imagen"),
]
FAMILIAS_IRREVERSIBLES = frozenset(f for f, _ in IRREVERSIBLES)

# Sensibles pero no irreversibles: van en `ask` y se proponen envueltas, no como allow pelado.
SENSIBLES: list[tuple[str, str]] = [
    ("bq query", "gasta cuota de BigQuery: allow solo con un hook que obligue --maximum_bytes_billed"),
]
FAMILIAS_SENSIBLES = frozenset(f for f, _ in SENSIBLES)

# Intérpretes y shells remotos: un allow sobre ellos es un allow sobre cualquier cosa, así que
# tampoco reciben `permiso-allow` (sí pueden acabar dentro de un `envolver-script`).
NUNCA_ALLOW = frozenset({
    "bash", "sh", "zsh", "dash", "fish", "python", "python3", "node", "deno", "bun", "perl", "ruby", "php",
    "eval", "ssh", "scp", "sudo", "su", "gcloud compute ssh", "gcloud compute scp", "docker exec", "docker run",
    "kubectl exec", "psql", "mysql", "sqlite3", "curl", "wget", "script", "tmux", "screen", "uv run",
    "xargs", "env", "find", "timeout", "watch", "systemd-run",
})

# Familias que nunca reciben una regla allow con comodín: `Bash(rm *)` cubre `rm -rf`, se haya
# aprobado lo que se haya aprobado.
SIN_COMODIN = frozenset({"rm"})

# CORPUS de irreversibles (y de NUNCA_ALLOW) conocidos, con sus variantes. Una regla allow propuesta
# no puede casar con NINGUNO (ver reglas.casa_corpus): `Bash(npm run *)` sale de aprobar
# `npm run build`, pero casa con `npm run deploy`. Se comprueba la regla, no el prefijo.
# Para ampliar: un ejemplo más por variante; test_d_permisos exige que cada irreversible esté
# clasificado como tal y que cada familia de IRREVERSIBLES tenga al menos un ejemplo.
CORPUS: dict[str, tuple[str, ...]] = {
    "git push": ("git push", "git push origin main", "git push origin feat", "git push -u origin feat",
                 "git push --force", "git push -f origin feat", "git push --force-with-lease",
                 "git push origin +feat", "git push --mirror", "git push --all", "git push origin --delete feat",
                 "git push origin :feat", "git -C repo push", "git --no-pager push"),
    "gcloud run deploy": ("gcloud run deploy", "gcloud run deploy api --image x", "gcloud beta run deploy api",
                          "gcloud alpha run deploy api"),
    "gcloud builds submit": ("gcloud builds submit", "gcloud builds submit --tag x .", "gcloud beta builds submit"),
    "gcloud run jobs execute": ("gcloud run jobs execute j", "gcloud run jobs execute j --wait",
                                "gcloud beta run jobs execute j"),
    "deploy": ("npm run deploy", "npm run deploy:prod", "pnpm run deploy", "pnpm deploy", "yarn deploy",
               "yarn run deploy", "make deploy", "firebase deploy", "firebase deploy --only hosting", "fly deploy",
               "flyctl deploy", "vercel deploy --prod", "netlify deploy --prod", "gcloud app deploy",
               "gcloud functions deploy f", "npx prisma migrate deploy", "./deploy.sh", "./deploy.sh prod",
               "deploy.sh", "bin/deploy", "./scripts/deploy prod", "cap production deploy"),
    "migrate prod": ("php artisan migrate --force", "php artisan migrate:fresh", "php artisan migrate:refresh",
                     "php artisan migrate:rollback", "php artisan migrate:reset", "php artisan migrate --env=production",
                     "python manage.py migrate --settings=prod", "python3 manage.py migrate --settings=config.production",
                     "rails db:migrate RAILS_ENV=production", "bin/rails db:migrate RAILS_ENV=production"),
    "DROP/TRUNCATE": ("psql -c 'DROP TABLE t'", "psql -c 'TRUNCATE TABLE t'", "mysql -e 'DROP DATABASE d'",
                      "sqlite3 db.sqlite 'DROP TABLE t'", "bq query 'DROP TABLE d.t'", "dropdb prod"),
    "rm -rf": ("rm -rf build", "rm -rf /", "rm -fr x", "rm -Rf x", "rm -fR x", "rm -r -f x", "rm -f -r x",
               "rm -R -f x", "rm --recursive --force x", "rm --force --recursive x", "rm -r --force x",
               "rm x -rf", "rm -rfv x", "rm -vrf x"),
    "kubectl apply/delete": ("kubectl apply -f x.yml", "kubectl delete pod y", "kubectl -n x delete pod y",
                             "kubectl delete ns prod", "kubectl replace -f x.yml", "kubectl --context prod apply -f x"),
    "terraform apply": ("terraform apply", "terraform apply -auto-approve", "terraform destroy",
                        "terraform destroy -auto-approve", "terraform -chdir=infra apply"),
    "npm publish": ("npm publish", "npm publish --access public", "yarn publish", "yarn npm publish",
                    "pnpm publish", "pnpm -r publish"),
    "gh pr merge": ("gh pr merge 3", "gh pr merge 3 --squash --delete-branch", "gh pr merge --admin 3"),
    "gh release": ("gh release create v1", "gh release delete v1", "gh release upload v1 x.tgz",
                   "gh release edit v1"),
    "docker push": ("docker push img:1", "docker image push img:1", "podman push img", "docker compose push",
                    "docker compose push api", "docker compose -f prod.yml push", "docker-compose push",
                    "docker buildx build --push -t x .", "docker build --push -t x ."),
    # NUNCA_ALLOW: un allow sobre estos es un allow sobre cualquier cosa.
    "interpretes": ("bash -c x", "sh x.sh", "zsh -c x", "dash -c x", "fish -c x", "python x.py", "python3 -c x", "node -e x", "deno run x",
                    "bun x", "perl -e x", "ruby -e x", "php -r x", "eval x", "env x", "find . -delete",
                    "find . -exec rm {} +", "xargs rm", "timeout 5 x", "watch x", "systemd-run x", "uv run x",
                    "script -qec x", "tmux new x", "screen x", "sudo x", "su -c x", "curl -X POST x", "wget x",
                    "psql -c x", "mysql -e x", "sqlite3 x"),
    "shells remotos": ("ssh host", "ssh host rm -rf x", "scp a host:", "gcloud compute ssh vm",
                       "gcloud compute scp a vm:", "gcloud beta compute ssh vm", "docker exec -it c sh",
                       "docker run img", "docker run --rm -it img sh", "docker compose exec app sh",
                       "docker compose run app x", "kubectl exec -it p -- sh"),
}
CORPUS_NUNCA_ALLOW: tuple[str, ...] = tuple(c for cs in CORPUS.values() for c in cs)

# Patrones de shell (se aplican a cada subcomando con las comillas enmascaradas).
_RX: dict[str, re.Pattern] = {
    "git push": re.compile(_GIT + r"push\b"),
    "gcloud run deploy": re.compile(_INI + r"gcloud\s+(?:(?:beta|alpha)\s+)?run\s+deploy\b"),
    "gcloud builds submit": re.compile(_INI + r"gcloud\s+(?:(?:beta|alpha)\s+)?builds\s+submit\b"),
    "gcloud run jobs execute": re.compile(_INI + r"gcloud\s+(?:(?:beta|alpha)\s+)?run\s+jobs\s+execute\b"),
    "kubectl apply/delete": re.compile(_INI + r"kubectl\s+(?:\S+\s+)*?(?:apply|delete|replace)\b"),
    "terraform apply": re.compile(_INI + r"terraform\s+(?:-\S+\s+)*(?:apply|destroy)\b"),
    "npm publish": re.compile(_INI + r"(?:npm|yarn|pnpm)\s+(?:\S+\s+)*?publish\b"),
    "gh pr merge": re.compile(_INI + r"gh\s+pr\s+merge\b"),
    "gh release": re.compile(_INI + r"gh\s+release\b"),
    # `docker compose push` y `docker buildx build --push` también publican.
    "docker push": re.compile(_INI + r"(?:(?:docker|podman)\s+(?:image\s+|compose\s+(?:\S+\s+)*?)?|docker-compose\s+"
                              r"(?:\S+\s+)*?)push\b|" + _INI + r"(?:docker|podman)\s+(?:buildx\s+)?build\s+(?:\S+\s+)*?--push\b"),
    "bq query": re.compile(_INI + r"bq\s+(?:--?\S+\s+)*query\b"),
}
_RX_MIGRATE = re.compile(r"\bmigrate(?::(fresh|refresh|rollback|reset))?\b")
_RX_PROD = re.compile(r"--force\b|\bprod(?:uction|uccion|ucción)?\b")
_RX_RM = re.compile(r"(?:^|[\s(`{])rm(?=\s|$)")
_RX_SQL = re.compile(
    r"(?i)\bdrop\s+(?:table|database|schema|view|index|materialized\s+view|function|role|user|owned)\b"
    r"|\btruncate\s+table\b|\bTRUNCATE\s+[\w.\"`]+|\bdropdb\b")
_RX_FORCE = re.compile(_INI + r"(?:--force(?:-with-lease)?(?:=\S*)?|-[a-zA-Z]*f[a-zA-Z]*)(?=\s|$)|\s\+\S+")
_RX_MAIN = re.compile(r"(?:^|[\s:/])(?:main|master)(?=\s|$)")

# Prefijos que no cambian qué se ejecuta.
_PREFIJOS = {"sudo", "env", "time", "nohup", "command", "exec", "nice", "then", "do", "else", "!", "{", "(", "xargs"}
_TRIVIALES = {"cd", "echo", "export", "set", "true", ":", "sleep", "printf", "pwd", "local", "unset", "fi", "done",
              "}", ")", "wait", "exit", "return", "source", ".", "read", "test", "[", "[[", "if", "while", "for",
              "until", "break", "continue", "case", "esac", "umask", "trap", "shift"}
_MULTI = {"git": 1, "docker": 1, "npm": 1, "pnpm": 1, "yarn": 1, "gh": 2, "kubectl": 1, "bq": 1, "terraform": 1,
          "cargo": 1, "go": 1, "pip": 1, "make": 1, "systemctl": 1, "composer": 1, "gcloud": 2, "php": 2,
          "python3": 0, "uv": 1, "npx": 1, "docker-compose": 1, "gsutil": 1, "psql": 0, "claude": 0}


@dataclass(frozen=True)
class Clasificacion:
    familia: str
    irreversible: bool
    compuesto: bool           # tenía más de un subcomando no trivial
    variante: str | None = None   # solo git push: rama | main | force | sin-destino


def quitar_heredocs(cmd: str) -> str:
    """Quita el cuerpo de los heredoc (`<<'EOF' ... EOF`), que es texto, no comandos."""
    lineas = cmd.split("\n")
    out, fin = [], None
    for ln in lineas:
        if fin is not None:
            if ln.strip() == fin:
                fin = None
            continue
        out.append(ln)
        m = re.search(r"(?<!<)<<-?(?!<)\s*['\"]?([A-Za-z_]\w*)['\"]?", ln)
        if m:
            fin = m.group(1)
    return "\n".join(out)


def partir_con_ops(cmd: str) -> list[tuple[str, str]]:
    """[(subcomando, operador que lo precede)] con las comillas enmascaradas (su contenido pasa a `…`).
    Separa por &&, ||, ;, |, & y salto de línea fuera de comillas. El primer operador es ""."""
    s = quitar_heredocs(cmd or "")
    piezas, actual, op, i, n = [], [], "", 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            actual.append(s[i:i + 2]); i += 2; continue
        if c in ("'", '"'):
            j = i + 1
            while j < n and s[j] != c:
                j += 2 if (c == '"' and s[j] == "\\") else 1
            actual.append(c + "…" + c); i = j + 1; continue
        if c in ";|&\n":
            if c == "&" and i + 1 < n and s[i + 1] == ">":   # &> redirección
                actual.append(c); i += 1; continue
            if c == "&" and i > 0 and s[i - 1] in "<>":       # 2>&1
                actual.append(c); i += 1; continue
            if c == "|" and i > 0 and s[i - 1] == ">":       # >| redirección
                actual.append(c); i += 1; continue
            piezas.append(("".join(actual), op)); actual = []
            op = s[i:i + 2] if s[i:i + 2] in ("&&", "||", ";;") else c
            i += len(op)
            continue
        actual.append(c); i += 1
    piezas.append(("".join(actual), op))
    return [(p.strip(), o) for p, o in piezas if p.strip()]


def partir(cmd: str) -> list[str]:
    """Solo los subcomandos (ver partir_con_ops)."""
    return [p for p, _ in partir_con_ops(cmd)]


# Envoltorios que no cambian qué se ejecuta, con las opciones que llevan un valor aparte.
_ENVOLTORIOS: dict[str, frozenset] = {
    "command": frozenset({"-p"}), "builtin": frozenset(), "exec": frozenset({"-a"}),
    "sudo": frozenset({"-u", "-g", "-C", "-h", "-p", "-U", "-r", "-t", "-D", "-R", "-T"}),
    "env": frozenset({"-u", "-C", "-S"}), "nice": frozenset({"-n"}), "nohup": frozenset(),
    "time": frozenset({"-f", "-o"}), "timeout": frozenset({"-s", "-k"}), "xargs": frozenset(
        {"-n", "-I", "-L", "-P", "-d", "-E", "-s", "-a"}),
    "then": frozenset(), "do": frozenset(), "else": frozenset(), "!": frozenset(),
}
_RX_ASIGNACION = re.compile(r"[A-Za-z_]\w*=(?:(\$\(|`)|\S*)")


def _palabra_comando(tok: str) -> str:
    """`\\rm` -> `rm`, `/bin/rm` -> `rm`, `./deploy.sh` -> `deploy.sh`."""
    tok = tok.lstrip("\\")
    if "/" in tok.rstrip("/"):
        tok = tok.rstrip("/").rsplit("/", 1)[-1]
    return tok


def normalizar(pieza: str) -> str:
    """El subcomando con su primera palabra tal como se ejecuta: sin asignaciones `VAR=x`, sin
    envoltorios (`command`, `builtin`, `sudo -u u`, `env -i VAR=x`, `nice -n 5`, `timeout 5`...),
    sin `\\` inicial y sin ruta (`/bin/rm` -> `rm`). Así `/bin/rm -rf x`, `\\rm -rf x` y
    `sudo env A=1 nice rm -rf x` se clasifican igual que `rm -rf x`. `command -v x` es una consulta:
    se deja tal cual."""
    s = (pieza or "").strip()
    while s:
        s = s.lstrip()
        m = re.match(r"(?:\$\(|`|\(|\{)\s*", s)
        if m and m.end():
            s = s[m.end():]
            continue
        m = _RX_ASIGNACION.match(s)
        if m:
            s = s[m.end():] if m.group(1) else s[m.end():].lstrip()
            continue
        m = re.match(r"\S+", s)
        palabra = _palabra_comando(m.group(0))
        resto = s[m.end():].lstrip()
        if palabra not in _ENVOLTORIOS:
            return palabra + (" " + resto if resto else "")
        if palabra == "command" and re.match(r"-[vV]\b", resto):
            return palabra + " " + resto
        con_valor, s = _ENVOLTORIOS[palabra], resto
        while s:                                  # opciones del envoltorio (y su valor)
            m = re.match(r"(\S+)\s*", s)
            x = m.group(1)
            if x == "--":
                s = s[m.end():]
                break
            if palabra == "env" and _RX_ASIGNACION.fullmatch(x):
                s = s[m.end():]
                continue
            if not x.startswith("-") or x == "-":
                break
            s = s[m.end():]
            if x in con_valor:
                s = re.sub(r"^\S+\s*", "", s, count=1)
        if palabra == "timeout":                  # la duración
            s = re.sub(r"^\S+\s*", "", s, count=1)
    return s


def _cabezas(pieza: str) -> list[str]:
    """El subcomando normalizado y cada sustitución `$(...)` o `` `...` `` que contiene, normalizada
    también: `echo $(\\rm -rf x)` ejecuta un `rm -rf`."""
    out = [normalizar(pieza)]
    out += [normalizar(pieza[m.end():]) for m in re.finditer(r"\$\(|`", pieza)]
    return out


def _tokens(pieza: str) -> list[str]:
    """Palabras del subcomando sin asignaciones, prefijos inofensivos ni `timeout N`.
    `X=$(cmd args)` se lee como `cmd args`: la sustitución es lo que se ejecuta."""
    try:
        t = shlex.split(pieza, comments=False, posix=True)
    except ValueError:
        t = pieza.split()
    while t:
        x = t[0]
        m = re.fullmatch(r"[A-Za-z_]\w*=(?:\$\(|`)(.*)", x)
        if m:
            t = ([m.group(1)] if m.group(1) else []) + t[1:]
        elif re.fullmatch(r"[A-Za-z_]\w*=.*", x) or x in _PREFIJOS:
            t = t[1:]
        elif x == "timeout" and len(t) > 1:
            t = t[2:]
        elif x.startswith(("(", "$(", "{", "`")) and len(x) > 1:
            t = [x.lstrip("($({`")] + t[1:]
        else:
            break
    if t:
        t[-1] = t[-1].rstrip(")`")
        t = [x for x in t if x]
    return t


def nombre_generico(pieza: str) -> str | None:
    """`git status`, `gcloud compute ssh`, `php artisan test`, `ls`... None si es trivial."""
    t = _tokens(normalizar(pieza))
    if not t:
        return None
    base = _palabra_comando(t[0])
    if (not base or base in _TRIVIALES or base.startswith("-") or re.fullmatch(r"[\W\d]*", base)
            or re.fullmatch(r"[\w-]+\(\)\{?", base)):     # definición de función: `d(){`
        return None
    extra = _MULTI.get(base, 0)
    palabras = [base]
    resto = t[1:]
    j = 0
    while extra and j < len(resto):
        x = resto[j]
        if x.startswith("-"):
            # opción con valor separado (`git -C dir`, `gcloud --project p`)
            if x in ("-C", "-c", "--project", "--region", "--zone", "-f", "--file") and j + 1 < len(resto):
                j += 2
            else:
                j += 1
            continue
        if "…" in x or "/" in x or "=" in x:
            break
        palabras.append(x); extra -= 1; j += 1
    return " ".join(palabras)


def _es_rm_rf(pieza: str) -> bool:
    """`rm` con recursivo (-r/-R/--recursive) y forzado (-f/--force), en cualquier orden, juntos o
    separados, antes o después de los operandos (GNU rm acepta `rm x -rf`); `--` corta las opciones."""
    for m in _RX_RM.finditer(pieza):
        r = f = False
        for x in pieza[m.end():].split():
            x = x.rstrip(")`;")
            if x == "--":
                break
            if x.startswith("--"):
                r = r or x == "--recursive"
                f = f or x == "--force"
            elif re.fullmatch(r"-[a-zA-Z]+", x):
                r = r or bool(re.search(r"[rR]", x))
                f = f or "f" in x
        if r and f:
            return True
    return False


def _es_deploy(pieza: str) -> bool:
    t = _tokens(pieza)
    if not t:
        return False
    if re.fullmatch(r"(?:.*/)?deploy(?:[-_.][\w.-]*)?", t[0]):
        return True
    return any(x == "deploy" or x.startswith("deploy:") for x in t[1:4])


def _es_migrate_prod(pieza: str) -> bool:
    m = _RX_MIGRATE.search(pieza)
    return bool(m and (m.group(1) or _RX_PROD.search(pieza)))


def variante_push(pieza: str) -> str:
    """rama | main | force | sin-destino (sin rama explícita: empuja la actual, que puede ser main)."""
    m = _RX["git push"].search(pieza)
    resto = pieza[m.end():] if m else pieza
    if _RX_FORCE.search(resto):
        return "force"
    if _RX_MAIN.search(resto):
        return "main"
    args = [x for x in resto.split() if not x.startswith("-")]
    return "rama" if len(args) >= 2 else "sin-destino"


def familias_de(pieza: str) -> list[str]:
    """Familias especiales (irreversibles o sensibles) presentes en un subcomando, en orden de gravedad.
    Se mira el subcomando normalizado (ver normalizar) y cada sustitución de comando que contenga."""
    hallas: list[str] = []
    for cabeza in _cabezas(pieza):
        hallas += [f for f in _familias_de_uno(cabeza) if f not in hallas]
    return sorted(hallas, key=_ORDEN.__getitem__)


def _familias_de_uno(pieza: str) -> list[str]:
    hallas = []
    for fam, _ in IRREVERSIBLES + SENSIBLES:
        if fam == "rm -rf":
            ok = _es_rm_rf(pieza)
        elif fam == "deploy":
            ok = _es_deploy(pieza) and not any(_RX[f].search(pieza) for f in
                                               ("gcloud run deploy", "gcloud builds submit"))
        elif fam == "migrate prod":
            ok = _es_migrate_prod(pieza)
        elif fam == "DROP/TRUNCATE":
            ok = False      # se busca sobre el texto crudo, ver clasificar()
        else:
            ok = bool(_RX[fam].search(pieza))
        if ok:
            hallas.append(fam)
    return hallas


_ORDEN = {f: i for i, (f, _) in enumerate(IRREVERSIBLES + SENSIBLES)}


def clasificar(cmd: str) -> Clasificacion:
    """Familia de un comando Bash, por su subcomando más grave."""
    piezas = partir(cmd)
    especiales: list[tuple[int, str, str]] = []   # (gravedad, familia, pieza)
    genericos: list[str] = []
    for p in piezas:
        for fam in familias_de(p):
            especiales.append((_ORDEN[fam], fam, normalizar(p)))
        g = nombre_generico(p)
        if g:
            genericos.append(g)
    if _RX_SQL.search(quitar_heredocs(cmd or "")) or _RX_SQL.search(cmd or ""):
        especiales.append((_ORDEN["DROP/TRUNCATE"], "DROP/TRUNCATE", ""))
    compuesto = len(genericos) > 1
    if especiales:
        _, fam, pieza = min(especiales, key=lambda x: x[0])
        var = variante_push(pieza) if fam == "git push" else None
        return Clasificacion(fam, fam in FAMILIAS_IRREVERSIBLES, compuesto, var)
    fam = genericos[0] if genericos else "(vacío)"
    return Clasificacion(fam, False, compuesto)


def es_irreversible(cmd: str) -> bool:
    """¿Alguno de sus subcomandos está en la lista fija? (no solo el más grave)"""
    return clasificar(cmd).irreversible
