#!/usr/bin/env python3
"""Check the install entries of Omarchy's menu against what this tablet can
install, and hide the ones that can't work here.

  omarchy-menu-audit.py           report the entries that can't work (read-only)
  omarchy-menu-audit.py --apply   also hide them in Omarchy's default menu;
                                  /usr/lib/loa/omarchy-post-upgrade.sh runs this
                                  after every Omarchy package change

Omarchy's menu offers its x86_64 catalogue on every machine. An entry can't
work here when a package it installs is missing from the sync repositories or
has a dependency they can't satisfy (`pacman -Sp`), when an AUR package it
falls back to is built for other architectures only, or when
/usr/share/loa/omarchy/menu-hide lists it (device limits that no package check
sees). The packages come from reading the entry's action and the Omarchy
scripts it calls, not from running them: the case branch for the script's
argument, the side of an `if omarchy-hw-...` test this machine takes. A package
named by a variable stays unchecked, and an entry that can't be checked stays.
Entries whose packages are all installed aren't checked (their own `when`
hides them).

Hiding sets the entry's `when` to `false`, keeps the original in `loaWhen` and
the reason in `loaHidden`, so the next run brings the entry back once it can
work. Both menus read this file: Omarchy's and a cloned one (local.menu).
"""
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

OMARCHY = "/usr/share/omarchy"
MENU = OMARCHY + "/default/omarchy/omarchy-menu.jsonc"
HIDE = "/usr/share/loa/omarchy/menu-hide"
ENTRY = re.compile(r'^(\s*"(install\.[^"]+)":\s*)(\{.*\})(\s*,?\s*)$')
ARCH = platform.machine()
ENV = dict(os.environ, LC_ALL="C", OMARCHY_PATH=OMARCHY,
           PATH=f"{OMARCHY}/bin:/usr/local/bin:/usr/bin")
PKG_CMDS = {"omarchy-pkg-add": "repo", "omarchy-pkg-aur-add": "aur"}


# ------------------------------------------------------------ reading scripts

@lru_cache(maxsize=None)
def script(name):
    """The text of an Omarchy command, None if `name` isn't one."""
    if not re.fullmatch(r"omarchy-[\w-]+", name):
        return None
    try:
        with open(f"{OMARCHY}/bin/{name}", errors="replace") as f:
            return f.read()
    except OSError:
        return None


@lru_cache(maxsize=None)
def hw(pred):
    """Whether this machine passes an `omarchy-hw-*` test, None if unknown."""
    if script(pred) is None:
        return None
    try:
        return subprocess.run([f"{OMARCHY}/bin/{pred}"], env=ENV, timeout=10,
                              capture_output=True).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None


IF_HW = re.compile(r"^(if|elif)\s+(!\s*)?(omarchy-hw-[\w-]+)\s*;\s*then$")
LABEL = re.compile(r"""^\(?\s*([\w.*"'|-]+)\s*\)(.*)$""")


def select(text, args):
    """The lines of a script that run for `args` on this machine."""
    lines = text.replace("\\\n", " ").split("\n")
    arg = args[0] if args else None
    labels = set()
    for line in lines:
        m = LABEL.match(line.strip())
        if m:
            labels.update(l.strip("\"'") for l in m.group(1).split("|"))
    pick = arg in labels
    out, stack = [], []        # frames: {kind, keep[, taken, open]}

    def keeping():
        return all(f["keep"] for f in stack)

    for line in lines:
        s = line.strip()
        top = stack[-1] if stack else None
        if re.match(r"^case\s.*\sin$", s):
            stack.append({"kind": "case", "keep": True, "open": False})
            continue
        if s.startswith("esac") and top and top["kind"] == "case":
            stack.pop()
            continue
        if top and top["kind"] == "case":
            if not top["open"]:
                m = LABEL.match(s)
                if not m:
                    continue
                alts = [l.strip("\"'") for l in m.group(1).split("|")]
                top["keep"] = not pick or arg in alts
                top["open"] = True
                s = line = m.group(2)
            if keeping():
                out.append(line)
            if ";;" in s:
                top["open"] = False
            continue
        m = IF_HW.match(s)
        if m and (m.group(1) == "if" or (top and top["kind"] == "hwif")):
            known = hw(m.group(3))
            take = True if known is None else known != bool(m.group(2))
            if m.group(1) == "if":
                stack.append({"kind": "hwif", "keep": take, "taken": take and known is not None})
            else:
                top["keep"] = not top["taken"] and take
                top["taken"] = top["taken"] or (top["keep"] and known is not None)
            continue
        if re.match(r"^if\s", s) and not re.search(r"\bfi$", s):
            if keeping():
                out.append(line)
            stack.append({"kind": "if", "keep": True})
            continue
        if top and top["kind"] == "hwif" and re.match(r"^(else|elif\s)", s):
            top["keep"] = not top["taken"]
            continue
        if re.match(r"^fi\b", s) and top and top["kind"] in ("if", "hwif"):
            stack.pop()
            continue
        if keeping():
            out.append(line)
    return out


def substitute(lines, args):
    """Put the script's arguments in for $1.. and for variables set from them."""
    text = "\n".join(lines)
    names = {str(i): a for i, a in enumerate(args, 1)}
    for m in re.finditer(r'^\s*(?:local\s+)?(\w+)="?\$\{?(\d)\}?"?\s*$', text, re.M):
        if m.group(2) in names:
            names[m.group(1)] = names[m.group(2)]
    return re.sub(r"\$\{(\w+)\}|\$(\w+)",
                  lambda m: names.get(m.group(1) or m.group(2), m.group(0)), text)


def commands(snippet):
    """The simple commands of a bash snippet, one argv each."""
    for line in snippet.split("\n"):
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
            lex.whitespace_split = True
            toks = list(lex)
        except ValueError:
            continue
        argv = []
        for t in toks + [";"]:
            if set(t) <= set(";&|()"):
                if argv:
                    yield argv
                argv = []
            else:
                argv.append(t)


class Found:
    def __init__(self):
        self.repo, self.aur, self.unresolved = set(), set(), False


def walk(snippet, found, depth=0):
    for argv in commands(snippet):
        for i, tok in enumerate(argv):
            if re.match(r"\s*omarchy-\S+\s", tok):     # a command line passed as one argument
                walk(tok, found, depth)
            # Every Omarchy command in the argv, so that wrappers which run
            # their arguments (omarchy-launch-floating-terminal-with-presentation
            # omarchy-install-...) are followed too.
            text = PKG_CMDS.get(tok) or script(tok)
            if text is not None:
                call(tok, text, argv[i + 1:], found, depth)


def call(name, text, args, found, depth):
    if name in PKG_CMDS:
        for a in args:
            if a.startswith("-"):
                continue
            if re.fullmatch(r"[\w@.+-]+", a):
                getattr(found, PKG_CMDS[name]).add(a)
            else:
                found.unresolved = True
        return
    # Wrappers that take the package list as an argument (omarchy-install-app,
    # -and-launch, -font) say so in their metadata.
    m = re.search(r"^# omarchy:args=(.*)$", text, re.M)
    for i, slot in enumerate(m.group(1).split() if m else []):
        if slot.strip("<>.") in ("package", "packages"):
            vals = args[i:] if slot.endswith("...>") else args[i:i + 1]
            call("omarchy-pkg-add", None, [w for v in vals for w in v.split()], found, depth)
            return
    if depth < 4 and re.search(r"omarchy-pkg-(aur-)?add|omarchy-install-", text):
        walk(substitute(select(text, args), args), found, depth + 1)


# --------------------------------------------------------- checking packages

@lru_cache(maxsize=None)
def resolve(pkgs):
    """None if pacman can install `pkgs` (a sorted tuple) from the sync
    repositories, else why not."""
    r = subprocess.run(["pacman", "-Sp", "--print-format", "%n", "--", *pkgs],
                       env=ENV, capture_output=True, text=True)
    if r.returncode == 0:
        return None
    err = r.stderr + r.stdout
    missing = re.findall(r"target not found: (\S+)", err)
    if missing:
        return "not in the repositories: " + " ".join(missing)
    deps = re.findall(r"unable to satisfy dependency '([^']+)' required by (\S+)", err)
    if deps:
        return "; ".join(f"{p} needs {d}, which no repository has" for d, p in deps)
    return (err.strip().splitlines() or ["pacman -Sp failed"])[-1]


@lru_cache(maxsize=None)
def aur_arches(pkg):
    """The architectures an AUR package builds for; empty if unknown."""
    url = "https://aur.archlinux.org/cgit/aur.git/plain/.SRCINFO?h=" + urllib.parse.quote(pkg)
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            text = r.read().decode(errors="replace")
    except (OSError, ValueError):
        return frozenset()
    return frozenset(re.findall(r"^\s*arch = (\S+)", text, re.M))


def check(found):
    """(status, reason): broken, ok, installed, unchecked or empty."""
    pkgs = found.repo | found.aur
    if not pkgs:
        return ("unchecked" if found.unresolved else "empty"), None
    if subprocess.run(["pacman", "-Q", "--", *pkgs], capture_output=True).returncode == 0:
        return "installed", None
    aur_only = {p for p in found.aur if resolve((p,)) is not None}
    reasons, unchecked = [], found.unresolved
    rest = tuple(sorted(pkgs - aur_only))
    if rest and resolve(rest):
        reasons.append(resolve(rest))
    for p in sorted(aur_only):
        arches = aur_arches(p)
        if not arches:
            unchecked = True
        elif "any" not in arches and ARCH not in arches:
            reasons.append(f"{p} (AUR) builds for {' '.join(sorted(arches))} only")
    if reasons:
        return "broken", "; ".join(reasons)
    return ("unchecked" if unchecked else "ok"), None


# ------------------------------------------------------------------ the menu

def load():
    """The menu's lines, and its install entries as they were before any
    hiding: id -> [line index, prefix, entry, tail]."""
    with open(MENU) as f:
        lines = f.read().split("\n")
    entries = {}
    for i, line in enumerate(lines):
        m = ENTRY.match(line)
        if not m:
            continue
        try:
            obj = json.loads(m.group(3))
        except ValueError:
            continue
        if "loaHidden" in obj:
            del obj["loaHidden"]
            if "loaWhen" in obj:
                obj["when"] = obj.pop("loaWhen")
            else:
                obj.pop("when", None)
        entries[m.group(2)] = [i, m.group(1), obj, m.group(4)]
    return lines, entries


def curated():
    hide = {}
    try:
        with open(HIDE) as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    key, _, reason = line.strip().partition(" ")
                    hide[key] = reason.strip()
    except OSError:
        pass
    return hide


def main():
    apply = "--apply" in sys.argv[1:]
    if not os.path.isfile(MENU):
        return 0
    if apply and not os.access(MENU, os.W_OK):
        sys.exit("omarchy-menu-audit: --apply needs root")
    lines, entries = load()
    was_hidden = {k for k, (i, *_) in entries.items() if '"loaHidden"' in lines[i]}

    hide, notes = {}, []
    for key, reason in curated().items():
        e = entries.get(key)
        if not e:
            notes.append(f"menu-hide lists {key}, which the menu no longer has: drop it")
        elif "omarchy-hw-x86" in e[2].get("when", "") and not hw("omarchy-hw-x86"):
            notes.append(f"Omarchy now hides {key} on ARM itself: drop it from menu-hide")
        else:
            hide[key] = "LoA: " + reason

    todo = {}
    for key, (_, _, obj, _) in entries.items():
        if key in hide or not obj.get("action"):
            continue
        found = Found()
        walk(obj["action"], found)
        todo[key] = found
    with ThreadPoolExecutor(8) as pool:
        results = dict(zip(todo, pool.map(check, todo.values())))
    for key, (status, reason) in results.items():
        if status == "broken":
            hide[key] = reason

    def name(key):
        return f"{entries[key][2].get('label', key)} ({key})"

    changed = False
    for key, (i, prefix, obj, tail) in entries.items():
        new = dict(obj)
        if key in hide:
            if "when" in new:
                new["loaWhen"] = new["when"]
            new["when"] = "false"
            new["loaHidden"] = hide[key]
        line = prefix + json.dumps(new, ensure_ascii=False, separators=(",", ":")) + tail
        if line != lines[i] and json.loads(ENTRY.match(lines[i]).group(3)) != new:
            lines[i] = line
            changed = True

    if apply:
        for key in sorted(hide.keys() - was_hidden):
            print(f"LoA: menu: hid {name(key)}: {hide[key]}")
        for key in sorted(was_hidden - hide.keys()):
            print(f"LoA: menu: {name(key)} is back")
        if changed:
            with open(MENU, "w") as f:
                f.write("\n".join(lines))
    else:
        for key in sorted(hide):
            print(f"{'hidden' if key in was_hidden else 'to hide'}  {name(key)}: {hide[key]}")
        unchecked = sorted(k for k, (s, _) in results.items() if s == "unchecked")
        if unchecked:
            print("unchecked (a package named by a variable, or the AUR out of reach): "
                  + " ".join(unchecked))
        counts = {}
        for status, _ in results.values():
            counts[status] = counts.get(status, 0) + 1
        print(f"{len(entries)} install entries: {len(hide)} can't work here, "
              + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()) if s != "broken"))
    for note in notes:
        print("LoA: menu: " + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
