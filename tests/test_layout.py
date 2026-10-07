# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The layout in docs/architecture.md, checked: the centre knows no server and only asks the questions in the shell
(cinesets/servers/base.py), every server module answers all of them itself, and an install loads only its own
server's module. So working on one server's module can't change what another server gets."""
import ast
import glob
import inspect
import os
import subprocess
import sys

from cinesets.servers import SERVERS, load
from cinesets.servers.base import Server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENTRE = sorted(glob.glob(os.path.join(ROOT, "cinesets", "*.py")))
SHELL = sorted(name for name, _ in inspect.getmembers(Server, inspect.isfunction) if not name.startswith("_"))
# what only a server module should say: servers' names, and API paths of their own
SERVER_WORDS = ("silo", "jellyfin", "plex", "/emby", "x-emby", "mediabrowser", "/api/v2", "/items/", "/items?",
                "/collections/", "/collections?", "/library/virtualfolders", "/system/info", "/users/", "boxset")
FROM_SERVERS = {"SERVERS", "ServerError", "chunks", "connect", "detect", "load", "names", "server_class", "trim"}


def parsed():
    for path in CENTRE:
        yield os.path.basename(path), ast.parse(open(path).read())


def docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                out.add(id(first.value))
    return out


def test_the_centre_imports_no_server_module():
    for name, tree in parsed():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith("servers."), f"{name} imports {module}; use cinesets.servers"
                if module == "servers":
                    extra = {a.name for a in node.names} - FROM_SERVERS
                    assert not extra, f"{name} takes {sorted(extra)} from cinesets.servers"


def test_the_centre_only_asks_the_shell():
    """Anything the centre calls on a server (self.srv, engine.srv or servers.connect(...)) is in the shell."""
    asked = set()
    for name, tree in parsed():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            target = node.value
            on_server = (isinstance(target, ast.Attribute) and target.attr == "srv") or \
                        (isinstance(target, ast.Call) and getattr(target.func, "attr", None) == "connect")
            if on_server:
                asked.add(node.attr)
                assert node.attr in SHELL, f"{name}:{node.lineno} asks the server for {node.attr!r}, which isn't in the shell"
    assert {"library_items", "create_collection", "narrow", "prepare", "arrange"} <= asked  # the check sees the calls


def test_the_centre_never_asks_what_a_server_has():
    """No hasattr or getattr on a server: every server answers every question, so the centre never needs to check."""
    for name, tree in parsed():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("hasattr", "getattr") and node.args:
                target = node.args[0]
                on_server = (isinstance(target, ast.Attribute) and target.attr == "srv") or getattr(target, "id", None) == "srv"
                assert not on_server, f"{name}:{node.lineno} checks what the server has; add it to the shell instead"


def test_the_centre_has_no_server_specific_code():
    found = []
    for name, tree in parsed():
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


def test_an_install_loads_only_its_own_server():
    code = ("import sys; from cinesets import cli, engine, web, servers; servers.load('emby'); "
            "print(sorted(m for m in sys.modules if m.startswith('cinesets.servers.')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out.strip() == "['cinesets.servers.base', 'cinesets.servers.emby']"
