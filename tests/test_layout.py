# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The layout in docs/architecture.md, checked: the centre knows no server, so working on one server's module can't
change what another server gets."""
import ast
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENTRE = sorted(glob.glob(os.path.join(ROOT, "cinesets", "*.py")))
# what only a server module should say: other servers' names, and API paths of their own
SERVER_WORDS = ("silo", "jellyfin", "plex", "/emby", "x-emby", "mediabrowser", "/api/v2", "/items/", "/items?",
                "/collections/", "/collections?", "/library/virtualfolders", "/system/info", "/users/", "boxset")


def docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                out.add(id(first.value))
    return out


def test_the_centre_only_reaches_servers_through_the_shell():
    for path in CENTRE:
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = (node.module or "")
                names = [a.name for a in node.names]
                assert not module.startswith("servers.") and not (module == "servers" and set(names) - {
                    "ServerError", "chunks", "connect", "detect", "names", "server_class", "trim"}), \
                    f"{os.path.basename(path)} imports a server module directly ({module}: {names}); use cinesets.servers"


def test_the_centre_has_no_server_specific_code():
    found = []
    for path in CENTRE:
        tree = ast.parse(open(path).read())
        skip = docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                text = node.value.lower()
                found += [f"{os.path.basename(path)}:{node.lineno}: {node.value[:60]!r}" for w in SERVER_WORDS if w in text]
    assert not found, "server-specific code in the centre; it belongs in cinesets/servers/<server>.py:\n" + "\n".join(found)


def test_every_server_module_answers_the_whole_shell():
    from cinesets import servers
    needed = ["media_libraries", "library_folders", "library_items", "genres", "alive", "backdrop_image",
              "list_collections", "create_collection", "wait_until_ready", "members", "add_items", "remove_items",
              "upload_poster", "set_details", "delete_collection", "admin_user", "detect", "trim"]
    for cls in servers._modules():
        missing = [op for op in needed if not callable(getattr(cls, op, None))]
        assert not missing, f"{cls.__name__} is missing {missing}"
        assert cls.NAMES and cls.KEY_PAGE
