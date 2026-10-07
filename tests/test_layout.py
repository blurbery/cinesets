# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The layout in docs/architecture.md, checked: the centre knows no server and only asks the questions in the shell
(cinesets/servers/base.py), every server module answers all of them itself and uses no other server's module, and
an install loads only its own server's module. So working on one server's module can't change what another gets."""
import ast
import glob
import inspect
import os
import subprocess
import sys

import pytest

from cinesets.servers import ASK_ORDER, SERVERS, load
from cinesets.servers.base import Server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENTRE = sorted(glob.glob(os.path.join(ROOT, "cinesets", "*.py")))
SHELL = sorted(name for name, _ in inspect.getmembers(Server, inspect.isfunction) if not name.startswith("_"))
SHELL_DATA = ("TYPE", "KEY_PAGE", "SETUP_NOTE")
# what only a server module should say: servers' names, and their API paths and headers
SERVER_WORDS = ("emby", "jellyfin", "silo", "plex", "mediabrowser", "/api/v2", "/items/", "/items?", "/collections/",
                "/collections?", "/library/virtualfolders", "/system/info", "/users/", "boxset")
FROM_SERVERS = {"SERVERS", "ServerError", "chunks", "connect", "detect", "load", "names", "server_class", "trim"}


def parsed(paths):
    for path in paths:
        yield os.path.basename(path), ast.parse(open(path).read())


def docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                out.add(id(first.value))
    return out


def targets(tree, package):
    """The full name of everything a file imports (a module, or a name taken from one), relative imports included.
    `package` is the file's own package, which `from . import` means."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                base = f"{parent}.{base}" if base else parent
            yield base
            for alias in node.names:
                yield f"{base}.{alias.name}"


def uses(found, module):
    return any(t == module or t.startswith(module + ".") for t in found)


def server_names(tree):
    """Every variable name that holds a server or a server class: srv, server, and whatever is set from one."""
    names = {"srv", "server"}
    grew = True
    while grew:
        grew = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and is_server(node.value, names):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in names:
                        names.add(target.id)
                        grew = True
    return names


def is_server(node, names):
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return node.attr == "srv"
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):  # servers.connect(...), servers.load(...), servers.server_class(...)
            return getattr(func.value, "id", None) == "servers" and func.attr in ("connect", "load", "server_class")
        if isinstance(func, ast.Name):  # connect(...) taken from cinesets.servers, or type(srv)
            return func.id == "connect" or (func.id == "type" and any(is_server(a, names) for a in node.args))
    if isinstance(node, ast.BoolOp):
        return any(is_server(v, names) for v in node.values)
    return False


def test_the_centre_imports_no_server_module():
    for name, tree in parsed(CENTRE):
        found = set(targets(tree, "cinesets"))
        for kind in SERVERS:
            assert not uses(found, f"cinesets.servers.{kind}"), f"{name} imports the {kind} module; use cinesets.servers"
        assert not uses(found, "cinesets.servers.base"), f"{name} imports the shell's base class"
        taken = {t[len("cinesets.servers."):] for t in found if t.startswith("cinesets.servers.")}
        assert taken <= FROM_SERVERS, f"{name} takes {sorted(taken - FROM_SERVERS)} from cinesets.servers"


def test_no_server_module_uses_another():
    for kind in SERVERS:
        tree = ast.parse(open(os.path.join(ROOT, "cinesets", "servers", f"{kind}.py")).read())
        found = set(targets(tree, "cinesets.servers"))
        for other in SERVERS:
            assert other == kind or not uses(found, f"cinesets.servers.{other}"), \
                f"{kind}.py imports the {other} module: a server module uses only base.py and the shared helpers"


def test_the_centre_only_asks_the_shell():
    """Anything the centre takes from a server or a server class, under any name, is in the shell."""
    asked = set()
    for name, tree in parsed(CENTRE):
        names = server_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and is_server(node.value, names):
                asked.add(node.attr)
                assert node.attr in SHELL or node.attr in SHELL_DATA, \
                    f"{name}:{node.lineno} asks a server for {node.attr!r}, which isn't in the shell"
    assert {"library_items", "create_collection", "narrow", "prepare", "arrange", "KEY_PAGE"} <= asked  # it sees them


def test_the_centre_never_asks_what_a_server_has():
    """No hasattr or getattr on a server: every server answers every question, so the centre never needs to check."""
    for name, tree in parsed(CENTRE):
        names = server_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("hasattr", "getattr") and node.args:
                assert not is_server(node.args[0], names), \
                    f"{name}:{node.lineno} checks what a server has; add it to the shell instead"


def test_the_centre_has_no_server_specific_code():
    found = []
    for name, tree in parsed(CENTRE):
        skip = docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                text = node.value.lower()
                found += [f"{name}:{node.lineno}: {node.value[:60]!r}" for w in SERVER_WORDS if w in text]
    assert not found, "server-specific code in the centre; it belongs in cinesets/servers/<server>.py:\n" + "\n".join(found)


def test_every_server_module_answers_the_whole_shell_itself():
    for kind in SERVERS:
        cls = load(kind)
        assert issubclass(cls, Server) and cls.TYPE == kind and cls.KEY_PAGE, kind
        unanswered = [op for op in SHELL if inspect.getattr_static(cls, op, None) is inspect.getattr_static(Server, op)]
        assert not unanswered, f"{kind} leaves {unanswered} to the base; every server answers each one itself"


def test_setup_asks_every_server():
    assert sorted(ASK_ORDER) == sorted(SERVERS) and len(ASK_ORDER) == len(set(ASK_ORDER))


@pytest.mark.parametrize("kind", sorted(SERVERS))
def test_an_install_loads_only_its_own_server(kind):
    code = (f"import sys; from cinesets import cli, config, engine, web, servers; servers.load({kind!r}); "
            "print(sorted(m for m in sys.modules if m.startswith('cinesets.servers.')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out.strip() == str(sorted(["cinesets.servers.base", f"cinesets.servers.{kind}"]))
