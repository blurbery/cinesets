# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Requests that meet a dropped connection, a timeout or a busy server are sent again, a few times, waiting longer
each time, but only when that's safe: reads and writes that do the same thing however often they arrive. Making a
collection is never sent twice, except after a 429, which says the server turned it away. The real Emby, Jellyfin
and Silo clients run against a scripted session here."""
import json
from urllib.parse import urlparse

import pytest
import requests

from cinesets import servers
from cinesets.servers import RETRIES, ServerError, emby, jellyfin, silo


class Answer:
    def __init__(self, status=200, data=None, headers=None, text=None, content=b""):
        self.status_code, self._data, self.headers, self.content = status, data, headers or {}, content
        self.text = text if text is not None else (json.dumps(data) if data is not None else "")

    def json(self):
        if self._data is None:
            raise ValueError("no body")
        return self._data


class Script:
    """A session that gives one answer (or raises one error) per request, in order, and keeps what was sent."""

    def __init__(self, *answers):
        self.answers, self.sent, self.headers = list(answers), [], {}

    def request(self, method, url, **kw):
        self.sent.append((method, url, kw))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def get(self, url, **kw):
        return self.request("GET", url, **kw)


@pytest.fixture
def waits(monkeypatch):
    """The waits between tries, taken instead of slept."""
    out = []
    monkeypatch.setattr(servers.time, "sleep", out.append)
    return out


def client(make_cfg, kind, *answers):
    cls = {"emby": emby.EmbyServer, "jellyfin": jellyfin.JellyfinServer, "silo": silo.SiloServer}[kind]
    srv = cls(make_cfg(kind))
    srv.session = Script(*answers)
    return srv


EMBY_LIKE = ["emby", "jellyfin"]
ALL = ["emby", "jellyfin", "silo"]
OK = {"emby": [{"Name": "Movies", "ItemId": "1"}], "jellyfin": [{"Name": "Movies", "ItemId": "1"}],
      "silo": {"items": [{"id": "1", "name": "Movies", "type": "movies"}]}}


def read(srv):
    return srv.library_folders()


@pytest.mark.parametrize("kind", ALL)
@pytest.mark.parametrize("trouble", [Answer(502), Answer(503), Answer(504), requests.ConnectionError("reset"),
                                     requests.ReadTimeout("slow"), requests.exceptions.ChunkedEncodingError("cut off")])
def test_a_read_is_sent_again_after_trouble(make_cfg, waits, kind, trouble):
    srv = client(make_cfg, kind, trouble, trouble, Answer(200, OK[kind]))
    assert read(srv) == {"Movies": "1"}
    assert len(srv.session.sent) == 3 and waits[:2] == [2, 4]   # longer each time


@pytest.mark.parametrize("kind", ALL)
def test_a_read_gives_up_after_a_few_tries_with_the_original_error(make_cfg, waits, kind):
    srv = client(make_cfg, kind, *[requests.ReadTimeout("slow")] * (RETRIES + 1))
    with pytest.raises(requests.ReadTimeout):   # still a requests error, so the engine stops the run to spare it
        read(srv)
    assert len(srv.session.sent) == RETRIES + 1 and waits == [2, 4, 8]


@pytest.mark.parametrize("kind", ALL)
def test_a_busy_answer_that_lasts_keeps_its_status(make_cfg, waits, kind):
    srv = client(make_cfg, kind, *[Answer(503)] * (RETRIES + 1))
    with pytest.raises(ServerError) as e:
        read(srv)
    assert e.value.status == 503 and len(srv.session.sent) == RETRIES + 1


@pytest.mark.parametrize("kind", ALL)
@pytest.mark.parametrize("asked, waited", [("5", 5), ("0", 0), ("3600", 60), ("soon", 2)])
def test_retry_after_is_honoured_up_to_a_minute(make_cfg, waits, kind, asked, waited):
    srv = client(make_cfg, kind, Answer(429, headers={"Retry-After": asked}), Answer(200, OK[kind]))
    read(srv)
    assert waits[0] == waited


def test_retry_after_can_be_a_date(make_cfg, waits):
    import email.utils
    import time
    when = email.utils.formatdate(time.time() + 30, usegmt=True)
    srv = client(make_cfg, "emby", Answer(503, headers={"Retry-After": when}), Answer(200, OK["emby"]))
    read(srv)
    assert 25 <= waits[0] <= 31


@pytest.mark.parametrize("kind", EMBY_LIKE)
@pytest.mark.parametrize("trouble", [Answer(502), requests.ConnectionError("reset"), requests.ReadTimeout("slow")])
def test_making_a_collection_is_never_sent_twice(make_cfg, waits, kind, trouble):
    srv = client(make_cfg, kind, trouble, Answer(200, {"Id": "9"}))
    with pytest.raises((ServerError, requests.RequestException)):
        srv.create_collection("Movies - Test", {"key": "m-test"}, ["1"])
    assert len(srv.session.sent) == 1          # the first try may have made it; the engine looks for it instead


@pytest.mark.parametrize("trouble", [Answer(502), requests.ConnectionError("reset"), requests.ReadTimeout("slow")])
def test_making_a_silo_collection_is_never_sent_twice(make_cfg, waits, trouble):
    srv = client(make_cfg, "silo", trouble)
    srv._folders = {"Movies": "1", "TV Shows": "2"}
    with pytest.raises((ServerError, requests.RequestException)):
        srv.create_collection("Movies - Test", {"key": "m-test", "kind": "movie"}, [])
    assert [m for m, _, _ in srv.session.sent] == ["POST"]


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_making_a_collection_is_sent_again_after_a_429(make_cfg, waits, kind):
    srv = client(make_cfg, kind, Answer(429), Answer(200, {"Id": "9"}))
    assert srv.create_collection("Movies - Test", {"key": "m-test"}, ["1"])[0] == "9"
    assert len(srv.session.sent) == 2


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_writes_that_can_be_repeated_are_sent_again(make_cfg, waits, kind):
    reset = requests.ConnectionError("reset")
    srv = client(make_cfg, kind, reset, Answer(204), Answer(502), Answer(204),        # add titles
                 Answer(503), Answer(204),                                            # take titles out
                 Answer(200, {"Id": "9", "ImageTags": {}}), reset, Answer(204),       # poster: the tag, then the upload
                 Answer(200, {"Id": "9", "ImageTags": {"Primary": "new"}}),
                 Answer(200, {"Id": "9", "LockedFields": []}), Answer(502), Answer(204))   # details
    srv.add_items("9", [f"m{n}" for n in range(45)])     # two batches of up to 40
    srv.remove_items("9", ["m1"])
    assert srv.upload_poster("9", b"jpeg", "admin")[0]
    srv.set_details("9", "admin", {"sort": "a", "overview": ""}, "Movies - Test")
    assert not srv.session.answers
    paths = [(m, urlparse(url).path) for m, url, _ in srv.session.sent if m != "GET"]
    writes = [(m, p[len("/emby"):] if p.startswith("/emby/") else p) for m, p in paths]
    assert writes == [("POST", "/Collections/9/Items")] * 4 + [("DELETE", "/Collections/9/Items")] * 2 + \
        [("POST", "/Items/9/Images/Primary")] * 2 + [("POST", "/Items/9")] * 2


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_deleting_is_sent_again_and_a_lost_answer_is_fine(make_cfg, waits, kind):
    listing = Answer(200, {"Items": [{"Id": "9", "Type": "BoxSet"}]})
    srv = client(make_cfg, kind, listing, requests.ReadTimeout("slow"), Answer(404))  # the first try got through
    srv.delete_collection("9")
    assert [m for m, _, _ in srv.session.sent] == ["GET", "DELETE", "DELETE"]


def test_silo_writes_that_can_be_repeated_are_sent_again(make_cfg, waits):
    reset = requests.ConnectionError("reset")
    srv = client(make_cfg, "silo", reset, Answer(204),                       # add a title
                 Answer(502), Answer(204),                                   # take one out
                 reset, Answer(200, {"poster_url": "https://storage.example.com/p.jpg"}),   # poster
                 Answer(503), Answer(200, {}),                               # details
                 reset, Answer(404, {"detail": "collection not found"}))     # delete: the first try got through
    srv._next["9"] = 0
    srv.add_items("9", ["movie-tmdb-105"])
    srv.remove_items("9", ["movie-tmdb-165"])
    assert srv.upload_poster("9", b"jpeg", None)[0]
    srv.set_details("9", None, {"overview": ""}, "Movies - Test")
    srv.delete_collection("9")
    assert not srv.session.answers and [m for m, _, _ in srv.session.sent] == \
        ["PUT", "PUT", "DELETE", "DELETE", "PUT", "PUT", "PATCH", "PATCH", "DELETE", "DELETE"]


@pytest.mark.parametrize("kind", ALL)
def test_a_certificate_error_is_not_sent_again(make_cfg, waits, kind):
    srv = client(make_cfg, kind, requests.exceptions.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number"))
    with pytest.raises(requests.exceptions.SSLError):
        read(srv)
    assert len(srv.session.sent) == 1 and not waits


@pytest.mark.parametrize("kind", ALL)
def test_how_long_a_write_took_leaves_out_the_waiting(make_cfg, monkeypatch, kind):
    clock = [1000.0]
    monkeypatch.setattr(servers.time, "time", lambda: clock[0])
    monkeypatch.setattr(servers.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    srv = client(make_cfg, kind)

    def slow_then_quick(method, url, **kw):
        clock[0] += 30 if not srv.session.sent else 0.5   # a 30 second 502, then a quick answer
        srv.session.sent.append(method)
        return Answer(502) if len(srv.session.sent) == 1 else Answer(204)
    srv.session.request = slow_then_quick
    took = srv.timed("DELETE", "/whatever", retry=True)[1]
    assert took == 0.5            # so one bad try doesn't trip slow_write_limit or stretch the pause


def test_silo_storage_downloads_are_sent_again(make_cfg, waits, monkeypatch):
    srv = client(make_cfg, "silo", Answer(200, {"items": [{"id": "77", "is_primary": True}]}),
                 Answer(200, {"backdrop_url": "https://storage.example.com/art/1.jpg?signature=abc"}))
    tries = [requests.ConnectionError("reset"), Answer(200, content=b"jpeg")]
    seen = []

    def storage(url, **kw):
        seen.append(kw)
        answer = tries.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(silo.requests, "get", storage)
    assert srv.backdrop_image("movie-tmdb-105") == b"jpeg"
    assert len(seen) == 2 and all("headers" not in kw for kw in seen)   # no API key goes to storage
