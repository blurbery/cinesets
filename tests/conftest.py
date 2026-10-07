# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Test helpers: an in-memory media server that speaks the small part of the Emby/Jellyfin API CineSets uses."""
import hashlib
import io
import os
import sys
import time
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cinesets import config  # noqa: E402
from cinesets.servers import ServerError  # noqa: E402
from cinesets.servers.emby import EmbyCalls  # noqa: E402
from cinesets.store import save_json  # noqa: E402


def jpeg_bytes(colour=(120, 40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(buf, "JPEG")
    return buf.getvalue()


class Resp:
    def __init__(self, content=b"", data=None):
        self.content, self._data = content, data

    def json(self):
        return self._data


class FakeServer(EmbyCalls):
    """Collections, items and calls, all in memory. The collection operations are the real ones (EmbyCalls), so the
    requests checked here are the ones Emby and Jellyfin get."""

    def __init__(self, kind="emby"):
        self.kind = kind
        self.items = {}          # id -> {"Name", "Type"}
        self.collections = {}    # id -> {"Name", "members": [], "image": None, "meta": {}}
        self.calls = []          # (method, path)
        self.next_id = 1000
        self.fail_backdrop = False
        self.timeout_on_create = False
        self.reuse_same_name = False   # Emby-style: creating a name that exists returns the existing one
        self.drop_posters = 0          # this many uploads are accepted but not kept
        self.libraries = {}            # name -> folder id
        self.page_cap = None           # send at most this many items per page, whatever Limit asks for
        self.ignore_start = False      # always send the first page, as a server without paging would

    # --- helpers for tests
    def add_item(self, iid, name, kind="Movie"):
        self.items[iid] = {"Id": iid, "Name": name, "Type": kind}

    def add_library(self, name, items):
        """items: [(id, name, year, "Movie" or "Series", provider ids)]"""
        fid = f"lib-{len(self.libraries) + 1}"
        self.libraries[name] = fid
        for iid, title, year, kind, ids in items:
            self.items[iid] = {"Id": iid, "Name": title, "Type": kind, "ProductionYear": year, "ProviderIds": ids, "lib": fid}
        return fid

    def page(self, items, q):
        start = 0 if self.ignore_start else int(q.get("StartIndex", 0))
        n = min(int(q.get("Limit", len(items))), self.page_cap or len(items))
        return Resp(data={"Items": items[start:start + n]})

    def add_collection(self, name, members=()):
        cid = str(self.next_id)
        self.next_id += 1
        self.collections[cid] = {"Name": name, "members": list(members), "image": None, "meta": {}}
        return cid

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "DELETE")]

    # --- the MediaServer interface
    def call(self, method, path, timeout=120, **kw):
        self.calls.append((method, path))
        u = urlparse(path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = u.path.strip("/").split("/")
        if method == "GET" and u.path == "/Library/VirtualFolders":
            return Resp(data=[{"Name": n, "ItemId": fid} for n, fid in self.libraries.items()])
        if method == "GET" and u.path == "/Items":
            if q.get("IncludeItemTypes") == "BoxSet":
                return self.page([{"Id": c, "Name": v["Name"]} for c, v in self.collections.items()], q)
            if q.get("ParentId") in self.libraries.values():
                return self.page([i for i in self.items.values()
                                  if i.get("lib") == q["ParentId"] and i["Type"] == q.get("IncludeItemTypes")], q)
            if "ParentId" in q:
                if self.kind == "jellyfin" and "UserId" not in q:
                    return Resp(data={"Items": []})  # Jellyfin lists box set children only for a user
                members = self.collections[q["ParentId"]]["members"]
                return self.page([{"Id": i} for i in members], q)
            if "Ids" in q:
                ids = q["Ids"].split(",")
                return Resp(data={"Items": [{"Id": i, "Genres": self.items[i].get("Genres", [])} for i in ids if i in self.items]})
        if method == "GET" and len(parts) == 4 and parts[0] == "Items" and parts[2] == "Images":
            if self.fail_backdrop:
                return Resp(content=b"")  # a broken download
            return Resp(content=jpeg_bytes(tuple(sum(map(ord, parts[1])) * k % 256 for k in (37, 91, 53))))  # one per item
        if method == "POST" and u.path == "/Collections":
            if self.timeout_on_create:
                import requests
                cid = self.add_collection(q["Name"], q.get("Ids", "").split(",") if q.get("Ids") else [])
                raise requests.Timeout("simulated timeout after the server made the collection")
            if self.reuse_same_name:
                same = next((c for c, v in self.collections.items() if v["Name"] == q["Name"]), None)
                if same:
                    return Resp(data={"Id": same})
            cid = self.add_collection(q["Name"], q.get("Ids", "").split(",") if q.get("Ids") else [])
            return Resp(data={"Id": cid})
        if parts[0] == "Collections" and len(parts) == 3 and parts[2] == "Items":
            ids = q["Ids"].split(",")
            members = self.collections[parts[1]]["members"]
            if method == "POST":
                members.extend(i for i in ids if i not in members)
            else:
                self.collections[parts[1]]["members"] = [i for i in members if i not in ids]
            return Resp()
        if method == "POST" and len(parts) == 4 and parts[2] == "Images":
            if self.drop_posters:
                self.drop_posters -= 1
            else:
                self.collections[parts[1]]["image"] = kw.get("data")
            return Resp()
        if method == "DELETE" and len(parts) == 2 and parts[0] == "Items":
            self.collections.pop(parts[1], None)
            return Resp()
        if method == "POST" and len(parts) == 2 and parts[0] == "Items":
            body = kw["json"]
            self.collections[parts[1]]["meta"] = body
            self.collections[parts[1]]["Name"] = body["Name"]
            return Resp()
        raise ServerError(f"fake server: no route for {method} {path}", 404)

    def get(self, path, **kw):
        return self.call("GET", path, **kw).json()

    def timed(self, method, path, **kw):
        t = time.time()
        r = self.call(method, path, **kw)
        return r, time.time() - t

    def admin_user(self):
        return "admin"

    def item(self, user_id, item_id):
        self.calls.append(("GET", f"item {item_id}"))
        c = self.collections[item_id]
        tags = {"Primary": hashlib.sha1(c["image"]).hexdigest()[:12]} if c["image"] else {}  # a new image, a new tag
        return {"Id": item_id, "Name": c["Name"], "LockedFields": [], "Path": f"/collections/{item_id}", **c["meta"],
                "ImageTags": tags}


@pytest.fixture
def make_cfg(tmp_path):
    def _make(kind="emby", collections_yml=None, extra=""):
        coll_path = tmp_path / "collections.yml"
        if collections_yml is not None:
            coll_path.write_text(collections_yml)
        cfg_path = tmp_path / "config.yml"
        cfg_path.write_text(
            f'server: {{type: {kind}, url: "http://127.0.0.1:8096", api_key: "test-key"}}\n'
            "libraries: [{name: Movies, type: movie}, {name: TV Shows, type: show}]\n"
            f"collections_file: {coll_path if collections_yml is not None else 'collections.yml'}\n"
            "write_pause: 0\n" + extra)
        return config.load(str(cfg_path))
    return _make


def seed_index(cfg, items):
    """Write a fresh library index so no server read is needed. items: {id: (name, year, kind)}."""
    index = {"built": time.time(), "movie": {"imdb": {}, "tmdb": {}}, "show": {"tvdb": {}, "imdb": {}, "tmdb": {}},
             "items": {i: {"n": n, "y": y, "b": True, "k": k} for i, (n, y, k) in items.items()}}
    save_json(os.path.join(cfg.path("data_dir"), "index.json"), index)
