"""Qué juzga el juez y las reglas deterministas de `rm -rf` y `git push` (antes del modelo).

La clasificación reutiliza lib.permisos.familias (partir, normalizar, familias_de...). Lo único
propio es conservar el texto crudo de cada subcomando: `familias.partir` enmascara las comillas
(`"…"`), y para resolver los objetivos de un `rm` hacen falta las rutas tal cual.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lib.permisos import familias as F

# Todas las irreversibles y sensibles de lib.permisos.familias: cualquiera que abra un diálogo lo decide
# el juez, no Derek (CONTRATO §14). Se acota con estado_dir()/juez.yml.
FAMILIAS_POR_DEFECTO = tuple(sorted(F.FAMILIAS_IRREVERSIBLES | F.FAMILIAS_SENSIBLES, key=F._ORDEN.__getitem__))
EFIMEROS = frozenset({"build", "dist", "node_modules", "__pycache__", ".cache", "tmp", ".pytest_cache",
                      "coverage", "target", ".next"})

PERMITE, MODELO, NIEGA = "permitir", "modelo", "negar"
_GRAVEDAD = {PERMITE: 0, MODELO: 1, NIEGA: 2}

_RX_CITA = re.compile(r"\\.|'[^']*'|\"(?:\\.|[^\"\\])*\"", re.S)
_RX_MARCA = re.compile("\x00(\\d+)\x00")
_RX_VARIABLE = re.compile(r"\$(?:[A-Za-z_{(]|[0-9@*#?!$-])|`")
_RX_GLOB = re.compile(r"[*?\[]")
_RX_REDIRECCION = re.compile(r"^\d*(?:>>?|<|&>|>&)")
_RX_VAR_INICIAL = re.compile(r"^\$\{?([A-Za-z_]\w*)\}?(?:/|$)")
_RX_VAR_COMPLETA = re.compile(r"\$\{[^}]*\}|\$\([^)]*\)|`[^`]*`|\$[A-Za-z_]\w*|\$[0-9@*#?!$-]")
_RX_REASIGNA = re.compile(r"(?:^|[\s;(])([A-Za-z_]\w*)\+?=|\bfor\s+([A-Za-z_]\w*)\s+in\b|\bread\s+(?:-\w+\s+)*([A-Za-z_]\w*)")
_RX_MKTEMP = re.compile(r"^\s*(?:export\s+|local\s+|readonly\s+)?([A-Za-z_]\w*)=[\"']?\$\(\s*mktemp\b([^)]*)\)[\"']?\s*$")


@dataclass
class Pieza:
    enmascarada: str     # comillas como `"…"` (lo que espera familias)
    cruda: str           # el texto original del subcomando
    familias: list[str] = field(default_factory=list)


@dataclass
class Destino:
    """Un destino de `git push`: en `dir` (el repo), `src` local hacia `remoto`/`dst`."""
    dir: str
    remoto: str
    src: str
    dst: str
    commits_antes: int = 0   # `git commit` del mismo comando antes del push: aún no salen en el log


@dataclass
class Veredicto:
    decision: str        # permitir | modelo | negar
    motivo: str
    destinos: list[Destino] = field(default_factory=list)   # solo git push: para el contexto del modelo


def piezas(cmd: str) -> list[Pieza]:
    """Subcomandos de `cmd` (mismo corte que familias.partir) con su texto crudo y sus familias."""
    s = F.quitar_heredocs(cmd or "")
    citas: list[str] = []

    def marcar(m: re.Match) -> str:
        if m.group(0).startswith("\\"):
            return m.group(0)
        citas.append(m.group(0))
        return f"\x00{len(citas) - 1}\x00"

    marcado = _RX_CITA.sub(marcar, s)
    out = []
    for p in F.partir(marcado):
        cruda = _RX_MARCA.sub(lambda m: citas[int(m.group(1))], p)
        enm = _RX_MARCA.sub(lambda m: citas[int(m.group(1))][0] + "…" + citas[int(m.group(1))][0], p)
        out.append(Pieza(enm, cruda, F.familias_de(enm)))
    return out


def familias_presentes(cmd: str, ps: list[Pieza] | None = None) -> list[str]:
    """Todas las familias especiales del comando (no solo la más grave), en orden de gravedad."""
    ps = piezas(cmd) if ps is None else ps
    hallas = []
    for p in ps:
        hallas += [f for f in p.familias if f not in hallas]
    if "DROP/TRUNCATE" not in hallas and (F._RX_SQL.search(F.quitar_heredocs(cmd or "")) or F._RX_SQL.search(cmd or "")):
        hallas.append("DROP/TRUNCATE")
    return sorted(hallas, key=F._ORDEN.__getitem__)


# ------------------------------------------------------------------------------- rm -rf

def _dentro(a: str, b: str) -> bool:
    """a está estrictamente dentro de b."""
    return a != b and (a.startswith(b.rstrip("/") + "/"))


def _expandir(tok: str, home: str) -> str | None:
    """`~` y `$HOME`/`${HOME}` expandidos; None si queda alguna variable o sustitución sin expandir."""
    if tok == "~" or tok.startswith("~/"):
        tok = home + tok[1:]
    elif tok.startswith("~"):
        return None                                   # ~usuario
    tok = re.sub(r"\$\{HOME\}|\$HOME(?![A-Za-z0-9_])", lambda _: home, tok)
    return None if _RX_VARIABLE.search(tok) else tok


def _objetivos(cruda: str) -> list[str] | None:
    """Operandos de un `rm` (sin opciones ni redirecciones). None si no se puede leer."""
    norm = F.normalizar(cruda)
    try:
        t = shlex.split(norm, posix=True)
    except ValueError:
        return None
    if not t or t[0] != "rm":
        return None
    out, opciones, saltar = [], True, False
    for x in t[1:]:
        if saltar:
            saltar = False
            continue
        if opciones and x == "--":
            opciones = False
            continue
        if opciones and x.startswith("-") and x != "-":
            continue
        m = _RX_REDIRECCION.match(x)
        if m:
            saltar = m.end() == len(x)                 # `> archivo`: el siguiente es el destino
            continue
        out.append(x.rstrip(")`") or x)
    return out


class _Ctx:
    def __init__(self, raiz: str):
        self.home = os.path.normpath(str(Path.home()))
        self.claudes = {os.path.normpath(os.path.join(self.home, ".claude"))}
        try:
            from lib import comun
            self.claudes.add(os.path.normpath(str(comun.claude_home())))
        except Exception:
            pass
        self.raices = {os.path.normpath(raiz), os.path.realpath(raiz)}
        self.tmps = {"/tmp", os.path.realpath("/tmp"), "/var/tmp", os.path.realpath("/var/tmp")}
        self.homes = {self.home, os.path.realpath(self.home)}
        self.temporales: set[str] = set()      # variables asignadas con `X=$(mktemp …)` en el comando


def _tras_cd(p: Pieza, actual: str | None, home: str) -> tuple[bool, str | None]:
    """(True, cwd nuevo) si la pieza es `cd`/`pushd` (None si no se puede saber); (False, actual) si no."""
    norm = F.normalizar(p.enmascarada)
    cabeza = norm.split()[0] if norm.split() else ""
    if cabeza not in ("cd", "pushd"):
        return False, actual
    try:
        t = shlex.split(F.normalizar(p.cruda), posix=True)
    except ValueError:
        t = []
    destino = t[1].rstrip(")") if len(t) > 1 else "~"
    exp = _expandir(destino, home) if destino != "-" else None
    if exp is None:
        return True, None
    if os.path.isabs(exp):
        return True, os.path.normpath(exp)
    return True, None if actual is None else os.path.normpath(os.path.join(actual, exp))


def _evaluar(p: str, ctx: _Ctx, patron: str | None) -> Veredicto:
    """Una ruta absoluta normalizada. `patron`: el componente con glob cuyo contenido se borra en p."""
    if p == "/":
        return Veredicto(NIEGA, "glob en la raíz (/*)" if patron else "borra /")
    if p == ctx.home:
        return Veredicto(NIEGA, "glob en $HOME (~/*)" if patron else "borra $HOME")
    for c in ctx.claudes:
        if p == c or _dentro(p, c):
            return Veredicto(NIEGA, "toca ~/.claude")
    if ".git" in Path(p).parts:
        return Veredicto(NIEGA, "toca .git")
    for raiz in ctx.raices:
        if _dentro(raiz, p):
            return Veredicto(NIEGA, f"borra un ancestro del proyecto: {p}")
        if p == raiz:
            if patron is None:
                return Veredicto(NIEGA, "borra la raíz del proyecto")
            if re.fullmatch(r"[*.]+", patron):
                return Veredicto(NIEGA, f"vacía la raíz del proyecto ({patron})")
            return Veredicto(MODELO, f"glob {patron} en la raíz del proyecto")
    for raiz in ctx.raices:
        if _dentro(p, raiz):
            rel = Path(p).relative_to(raiz).parts
            if any(x in EFIMEROS for x in rel):
                return Veredicto(PERMITE, "efímero dentro del proyecto")
            return Veredicto(MODELO, f"dentro del proyecto, no efímero: {'/'.join(rel)}")
    for h in ctx.homes:
        if _dentro(h, p):
            return Veredicto(NIEGA, f"borra un ancestro de $HOME: {p}")
        if _dentro(p, h):
            rel = Path(p).relative_to(h).parts
            if len(rel) == 1:
                return Veredicto(NIEGA, f"carpeta de primer nivel de $HOME: {p}")
            # Otro repo o carpeta del usuario (~/Proyectos/otro/...): lo regenerable pasa, lo demás lo
            # mira el modelo con la conversación delante. Negar en seco era el cuello de botella.
            if rel[0] == ".cache":
                return Veredicto(PERMITE, f"caché de $HOME: {p}")
            if rel[0].startswith("."):                 # ~/.ssh, ~/.config, ~/.gnupg…: no se regeneran
                return Veredicto(NIEGA, f"configuración de $HOME: {p}")
            if any(x in EFIMEROS for x in rel[2:]):
                return Veredicto(PERMITE, f"efímero fuera del proyecto: {p}")
            return Veredicto(MODELO, f"fuera del proyecto, dentro de $HOME: {p}")
    if any(_dentro(p, t) for t in ctx.tmps):
        return Veredicto(PERMITE, "temporal (/tmp o /var/tmp)")
    return Veredicto(NIEGA, f"fuera del proyecto y de $HOME: {p}")


def _evaluar_objetivo(tok: str, cwd: str | None, ctx: _Ctx) -> Veredicto:
    m = _RX_VAR_INICIAL.match(tok)
    if m and m.group(1) in ctx.temporales and ".." not in tok:
        return Veredicto(PERMITE, f"temporal de mktemp: {tok}")
    exp = _expandir(tok, ctx.home)
    if exp is None:
        # Con las variables vacías, ¿qué borraría? `$X/*` o `$X/` serían la raíz: eso no pasa nunca.
        resto = _RX_VAR_COMPLETA.sub("", tok)
        vacio = os.path.normpath(resto) if tok.startswith(("$", "`")) and resto.startswith("/") else None
        if vacio is not None and (vacio == "/" or re.fullmatch(r"/[*.?]+", vacio)):
            return Veredicto(NIEGA, f"si {tok} quedara vacía, borraría la raíz")
        return Veredicto(MODELO, f"variable sin expandir en {tok}")
    if not os.path.isabs(exp) and cwd is None:
        return Veredicto(MODELO, f"cwd desconocido tras un cd: {tok}")
    ruta = os.path.join(cwd or "/", exp)
    patron = None
    if _RX_GLOB.search(ruta):
        partes = Path(ruta).parts
        i = next(k for k, x in enumerate(partes) if _RX_GLOB.search(x))
        patron = partes[i]
        ruta = str(Path(*partes[:i])) if i else "/"
    lex = os.path.normpath(ruta)
    peor = Veredicto(PERMITE, "")
    for p in (lex, os.path.realpath(lex)):
        v = _evaluar(p, ctx, patron)
        if _GRAVEDAD[v.decision] > _GRAVEDAD[peor.decision]:
            peor = v
        elif not peor.motivo:
            peor.motivo = v.motivo
    return peor


def reglas_rm(ps: list[Pieza], cwd: str, raiz: str) -> Veredicto:
    """NIEGA si algún objetivo de algún `rm -rf` es peligroso; PERMITE si todo el comando son `rm -rf`
    de efímeros del proyecto o de /tmp (más `cd` y triviales); si no, MODELO."""
    ctx = _Ctx(raiz)
    actual: str | None = os.path.normpath(cwd)
    resultado = Veredicto(PERMITE, "")
    motivos: list[str] = []
    hubo_rm = False

    def peor(v: Veredicto):
        nonlocal resultado
        if _GRAVEDAD[v.decision] > _GRAVEDAD[resultado.decision]:
            resultado = v

    for p in ps:
        norm = F.normalizar(p.enmascarada)
        es_cd, actual = _tras_cd(p, actual, ctx.home)
        if es_cd:
            continue
        mt = _RX_MKTEMP.match(p.cruda)
        if mt:
            if not re.search(r"(?:^|\s)(?:-p|--tmpdir)\b", mt.group(2)):   # mktemp -p otra/ no es /tmp
                ctx.temporales.add(mt.group(1))
            else:
                ctx.temporales.discard(mt.group(1))
            continue
        # cualquier otra asignación de la variable (X=…, for X in, read X) deja de ser el temporal
        for v in _RX_REASIGNA.findall(p.cruda):
            ctx.temporales.discard(next(x for x in v if x))
        if "rm -rf" in p.familias:
            objetivos = _objetivos(p.cruda)
            if not objetivos:
                peor(Veredicto(MODELO, "rm -rf sin objetivos legibles"))
                continue
            hubo_rm = True
            for o in objetivos:
                v = _evaluar_objetivo(o, actual, ctx)
                if v.decision == NIEGA:
                    return v
                peor(v)
                if v.motivo and v.motivo not in motivos:
                    motivos.append(v.motivo)
            continue
        if F.nombre_generico(p.enmascarada) is not None or re.search(r"\$\(|`", p.enmascarada):
            peor(Veredicto(MODELO, f"el comando incluye además: {norm[:60]}"))
    if not hubo_rm and resultado.decision == PERMITE:
        return Veredicto(MODELO, "sin rm -rf que evaluar")
    if resultado.decision == PERMITE:
        return Veredicto(PERMITE, "; ".join(motivos) or "efímeros")
    return resultado


# ----------------------------------------------------------------------------- git push

RX_PROTEGIDA = re.compile(r"(?:main|master|prod.*|release.*)")
_RX_TAG = re.compile(r"v\d")
# Flags que reescriben o borran lo compartido: NIEGA (para el force ya hay un deny en settings; esto
# es defensa en profundidad). `--prune` borra ramas remotas; `--force-if-includes` solo existe para el force.
_PUSH_NIEGA = {"--force": "--force", "--force-with-lease": "--force-with-lease", "--force-if-includes": "--force",
               "--mirror": "--mirror", "--delete": "--delete", "--prune": "--prune"}
_PUSH_CORTAS_NIEGA = {"f": "-f (force)", "d": "-d (borra la rama remota)"}
_PUSH_CORTAS_OK = frozenset("uvqn46")
_PUSH_OK = frozenset({"--set-upstream", "--verbose", "--quiet", "--progress", "--no-progress", "--porcelain",
                      "--dry-run", "--atomic", "--no-atomic", "--no-verify", "--verify", "--thin", "--no-thin",
                      "--ipv4", "--ipv6", "--no-recurse-submodules", "--recurse-submodules=check",
                      "--no-follow-tags", "--no-signed"})
_PUSH_TAGS = frozenset({"--tags", "--follow-tags"})
_PUSH_TODAS = frozenset({"--all", "--branches"})
_PUSH_CON_VALOR = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})
_GIT_GLOBALES_OK = frozenset({"--no-pager", "-P", "--paginate", "-p", "--no-optional-locks"})
# Lo que puede ir junto a un push que se permite sin modelo (`git add -A && git commit -m … && git push`).
_ACOMPANANTES_GIT = frozenset({"git add", "git commit", "git status", "git log", "git diff", "git fetch", "git show",
                               "git rev-parse"})
_ACOMPANANTES = frozenset({"echo", "printf", "pwd", "true", ":", "sleep", "wait", "popd", "tail", "head", "cat",
                           "grep", "wc"})
_RX_SUST_HEREDOC = re.compile(r"\$\(\s*cat\s+<<-?\s*['\"]?\w+['\"]?\s*\)")   # -m "$(cat <<'EOF' … EOF)"
_RX_REDIR_INOCUA = re.compile(r"\d*>&\d|\d*>>?\s*/dev/null")


def _git_rc(cwd: str, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout.strip()


def _git_out(cwd: str, *args: str) -> str:
    rc, out = _git_rc(cwd, *args)
    return out if rc == 0 else ""


class _Peor:
    """Acumula el veredicto más grave (y sus motivos) de un análisis."""

    def __init__(self):
        self.v = Veredicto(PERMITE, "")
        self.motivos: list[str] = []
        self.destinos: list[Destino] = []

    def __call__(self, decision: str, motivo: str):
        if _GRAVEDAD[decision] > _GRAVEDAD[self.v.decision]:
            self.v = Veredicto(decision, motivo)
        if decision == PERMITE and motivo and motivo not in self.motivos:
            self.motivos.append(motivo)

    def final(self) -> Veredicto:
        motivo = self.v.motivo if self.v.decision != PERMITE else "; ".join(self.motivos)
        return Veredicto(self.v.decision, motivo, self.destinos)


def _acompanante_seguro(p: Pieza) -> bool:
    if re.search(r"\$\(|`", _RX_SUST_HEREDOC.sub("", p.cruda)):
        return False
    if ">" in _RX_REDIR_INOCUA.sub("", p.enmascarada):
        return False
    nombre = F.nombre_generico(p.enmascarada)
    if nombre is None:
        cabeza = (F.normalizar(p.enmascarada).split() or [""])[0]
        return cabeza in _ACOMPANANTES or cabeza == ""
    return nombre in _ACOMPANANTES_GIT or nombre in _ACOMPANANTES


def _destino_ref(spec: str, rama: str | None) -> tuple[str | None, str | None, str]:
    """(src, dst, problema) de un refspec sin `+` ni `src` vacío. dst sin `refs/heads/`."""
    src, _, dst = spec.partition(":")
    dst = dst or src
    if src in ("HEAD", "@"):
        src = "HEAD"
    if dst in ("HEAD", "@"):
        if not rama:
            return src, None, "HEAD separado"
        dst = rama
    if "*" in spec:
        return src, None, f"refspec con comodín: {spec}"
    if dst.startswith("refs/heads/"):
        dst = dst[len("refs/heads/"):]
    elif dst.startswith("refs/tags/"):
        return src, dst, "tag"
    elif dst.startswith("refs/"):
        return src, None, f"ref fuera de refs/heads: {dst}"
    return src, dst, ""


def _push_de_pieza(p: Pieza, actual: str | None, home: str, hay_remote_add: bool) -> Veredicto:
    peor = _Peor()
    if re.search(r"\$|`", p.cruda):
        peor(MODELO, "variable o sustitución en el git push")
    if re.match(r"\s*[({]?\s*[A-Za-z_]\w*=", p.cruda):
        peor(MODELO, "variables de entorno delante del git push")
    primera = re.match(r"[\s({]*(\S+)", p.cruda)
    if primera and F._palabra_comando(primera.group(1)) != "git":
        # `xargs git push`, `sudo git push`, `timeout 5 git push`...: normalizar los quita, pero `xargs`
        # añade operandos que aquí no se ven.
        peor(MODELO, f"git push envuelto en {F._palabra_comando(primera.group(1))}")
    try:
        t = shlex.split(F.normalizar(p.cruda), posix=True)
    except ValueError:
        return Veredicto(MODELO, "git push ilegible")
    t = [x.rstrip(")") if i == len(t) - 1 else x for i, x in enumerate(t)]
    t = [x for x in t if x]
    if not t or t[0] != "git":
        return Veredicto(MODELO, f"git push envuelto en {t[0] if t else '?'}")
    # opciones globales de git hasta `push`
    i, d = 1, actual
    while i < len(t) and t[i] != "push":
        x = t[i]
        if x == "-C" and i + 1 < len(t):
            exp = _expandir(t[i + 1], home)
            d = None if exp is None or (d is None and not os.path.isabs(exp)) else os.path.normpath(
                os.path.join(d or "/", exp))
            i += 2
            continue
        if x not in _GIT_GLOBALES_OK:
            peor(MODELO, f"opción global de git: {x}")
            if x in ("-c", "--git-dir", "--work-tree", "--namespace", "--exec-path") and i + 1 < len(t):
                i += 1
        i += 1
    # opciones y operandos de push
    posicionales: list[str] = []
    repo_opt: str | None = None
    tags = todas = False
    args, j, solo_operandos = t[i + 1:], 0, False
    while j < len(args):
        x = args[j]
        j += 1
        m = _RX_REDIRECCION.match(x)
        if m and not solo_operandos:
            if m.end() == len(x):
                j += 1
            continue
        if solo_operandos or not x.startswith("-") or x == "-":
            posicionales.append(x)
            continue
        if x == "--":
            solo_operandos = True
            continue
        nombre = x.split("=", 1)[0]
        if nombre in _PUSH_NIEGA:
            return Veredicto(NIEGA, f"git push con {_PUSH_NIEGA[nombre]}")
        if nombre in _PUSH_CON_VALOR:
            valor = x.split("=", 1)[1] if "=" in x else (args[j] if j < len(args) else "")
            j += 0 if "=" in x else 1
            if nombre == "--repo":
                repo_opt = valor
            else:
                peor(MODELO, f"git push con {nombre}")
            continue
        if x in _PUSH_TAGS:
            tags = True
            continue
        if x in _PUSH_TODAS:
            todas = True
            continue
        if x in _PUSH_OK:
            continue
        if re.fullmatch(r"-[A-Za-z0-9]+", x):
            for c in x[1:]:
                if c in _PUSH_CORTAS_NIEGA:
                    return Veredicto(NIEGA, f"git push con {_PUSH_CORTAS_NIEGA[c]}")
                if c not in _PUSH_CORTAS_OK:
                    peor(MODELO, f"git push con -{c}")
            continue
        peor(MODELO, f"git push con {x}")
    repo = repo_opt or (posicionales[0] if posicionales else None)
    refspecs = posicionales[1:] if not repo_opt else posicionales
    for spec in refspecs:
        if spec.startswith("+"):
            return Veredicto(NIEGA, f"refspec con + (force): {spec}")
        if spec.startswith(":"):
            return Veredicto(NIEGA, f"borra la rama remota {spec[1:] or '(todas las que casen)'}")
    if todas:
        peor(MODELO, "git push de todas las ramas")
    if tags:
        peor(MODELO, "git push de tags")
    if d is None:
        peor(MODELO, "cwd desconocido tras un cd")
        return peor.final()
    if _git_rc(d, "rev-parse", "--git-dir")[0] != 0:
        peor(MODELO, f"no es un repositorio git: {d}")
        return peor.final()
    remotos = set(_git_out(d, "remote").split())
    rama = _git_out(d, "symbolic-ref", "--short", "-q", "HEAD") or None

    if repo is None:
        if not rama:
            peor(MODELO, "HEAD separado y sin destino explícito")
            return peor.final()
        repo = (_git_out(d, "config", f"branch.{rama}.pushRemote") or _git_out(d, "config", "remote.pushDefault")
                or _git_out(d, "config", f"branch.{rama}.remote") or "origin")
    if repo not in remotos:
        if re.search(r"[/:]", repo) or repo == ".":
            peor(MODELO, f"destino que no es un remoto configurado: {repo}")
            return peor.final()
        if hay_remote_add:
            peor(MODELO, f"el remoto {repo} se añade en el mismo comando")
            return peor.final()
        return Veredicto(NIEGA, f"el remoto {repo} no existe")

    destinos: list[tuple[str, str]] = []           # (src, dst)
    if not refspecs:
        if tags and not todas:
            return peor.final()                   # solo tags: ya va al modelo
        if not rama:
            peor(MODELO, "HEAD separado y sin refspec")
            return peor.final()
        candidatos = {rama}
        upstream = _git_out(d, "config", f"branch.{rama}.merge")
        if upstream.startswith("refs/heads/") and _git_out(d, "config", f"branch.{rama}.remote") == repo:
            candidatos.add(upstream[len("refs/heads/"):])
        push = _git_out(d, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}")
        if push.startswith(repo + "/"):
            candidatos.add(push[len(repo) + 1:])
        destinos = [(rama, c) for c in sorted(candidatos)]
    for spec in refspecs:
        src, dst, problema = _destino_ref(spec, rama)
        if problema == "tag":
            peor(MODELO, f"git push de tag {dst}")
        elif problema:
            peor(MODELO, problema)
        if dst is None or problema:
            if dst and src:
                destinos.append((src, dst))
            continue
        if _RX_TAG.match(dst) or (
                _git_rc(d, "show-ref", "--verify", "-q", f"refs/tags/{src}")[0] == 0
                and _git_rc(d, "show-ref", "--verify", "-q", f"refs/heads/{src}")[0] != 0):
            peor(MODELO, f"git push de tag {dst}")
        destinos.append((src, dst))
    for src, dst in destinos:
        peor.destinos.append(Destino(d, repo, src, dst))
        if RX_PROTEGIDA.fullmatch(dst):
            peor(MODELO, f"git push a la rama protegida {dst} de {repo}")
        else:
            peor(PERMITE, f"git push de {src} a {repo}/{dst}")
    if not destinos and peor.v.decision == PERMITE:
        peor(MODELO, "git push sin destino que evaluar")
    return peor.final()


def reglas_push(ps: list[Pieza], cwd: str) -> Veredicto:
    """NIEGA force/mirror/delete/`+`/`:rama`/remoto inexistente; PERMITE push a ramas no protegidas cuando
    el resto del comando es `cd`, git local (add, commit…) o trivial; si no, MODELO."""
    home = os.path.normpath(str(Path.home()))
    actual: str | None = os.path.normpath(cwd)
    hay_remote_add = any(re.search(r"(?:^|\s)git\b.*\sremote\s+add\b", p.enmascarada) for p in ps)
    peor = _Peor()
    hubo = False
    commits = 0
    for p in ps:
        es_cd, actual = _tras_cd(p, actual, home)
        if es_cd:
            continue
        if F.nombre_generico(p.enmascarada) == "git commit":
            commits += 1
        if "git push" in p.familias:
            hubo = True
            if len(p.familias) > 1:
                peor(MODELO, f"el git push lleva además: {'+'.join(f for f in p.familias if f != 'git push')}")
            v = _push_de_pieza(p, actual, home, hay_remote_add)
            if v.decision == NIEGA:
                return v
            peor(v.decision, v.motivo)
            for dst in v.destinos:
                dst.commits_antes = commits
            peor.destinos += v.destinos
            continue
        if p.familias or not _acompanante_seguro(p):
            peor(MODELO, f"el comando incluye además: {F.normalizar(p.enmascarada)[:60]}")
    if not hubo:
        return Veredicto(MODELO, "sin git push que evaluar")
    return peor.final()
