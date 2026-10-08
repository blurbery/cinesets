# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""What each server module asks for and how carefully: paging in a fixed order, deleting only collections, artwork
big enough for a poster, Silo's kept ids, Silo's artwork links and how long Silo is left to rest between writes."""
import time

import pytest

from cinesets import servers
from cinesets.servers import ServerError, silo
from cinesets.store import load_json, save_json
from conftest import FakeServer
from test_server_retries import EMBY_LIKE, Answer, client, waits  # noqa: F401 (waits is a fixture)
from test_silo import silo_run  # noqa: F401 (a fixture)


# ---------------------------------------------------------------- Emby and Jellyfin
class Counted:
    """A fake server that also says how many items a listing has, `hidden` more than it sends."""
    hidden = 0

    def page(self, items, q):
        r = super().page(items, q)
        if q.get("EnableTotalRecordCount") == "true":
            r._data["TotalRecordCount"] = len(items) + self.hidden
        return r


def counted(kind, hidden=0):
    srv = type("CountedServer", (Counted, type(FakeServer(kind))), {})(kind)
    srv.hidden = hidden
    return srv


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_listings_are_paged_in_a_fixed_order(kind, waits):
    srv = counted(kind)
    srv.page_cap = 2
    fid = srv.add_library("Movies", [(f"m{n}", f"Film {n}", 2000, "Movie", {}) for n in range(5)])
    assert len(srv.library_items(fid, "movie", "Movies")) == 5
    reads = [path for method, path in srv.calls if path.startswith("/Items?")]
    assert all("SortBy=SortName,ProductionYear,DateCreated&SortOrder=Ascending" in p for p in reads)
    assert "EnableTotalRecordCount=true" in reads[0] and all("EnableTotalRecordCount=false" in p for p in reads[1:])


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_fewer_titles_than_the_server_counted_is_reported(kind, waits, capsys):
    srv = counted(kind, hidden=2)
    fid = srv.add_library("Movies", [(f"m{n}", f"Film {n}", 2000, "Movie", {}) for n in range(5)])
    srv.library_items(fid, "movie", "Movies")
    assert "library 'Movies': the server counted 7 but sent 5" in capsys.readouterr().out
    srv.hidden = 0
    srv.library_items(fid, "movie", "Movies")
    assert "counted" not in capsys.readouterr().out


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_only_a_collection_is_ever_deleted(kind):
    srv = FakeServer(kind)
    srv.add_item("film", "A Film")
    with pytest.raises(ServerError, match="not a collection"):
        srv.delete_collection("film")
    assert "film" in srv.items and not [c for c in srv.calls if c[0] == "DELETE"]
    cid = srv.add_collection("Movies - Test")
    srv.delete_collection(cid)
    assert cid not in srv.collections


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_a_server_that_ignores_the_type_filter_still_cannot_delete_a_film(make_cfg, waits, kind):
    srv = client(make_cfg, kind, Answer(200, {"Items": [{"Id": "film", "Type": "Movie"}]}))
    with pytest.raises(ServerError, match="not a collection"):
        srv.delete_collection("film")
    assert [m for m, _, _ in srv.session.sent] == ["GET"]


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_poster_artwork_is_asked_for_by_height(kind):
    srv = FakeServer(kind)
    srv.backdrop_image("m1", 1920, 90)    # a poster
    srv.backdrop_image("m1", 1280, 85)    # a preview of one
    srv.backdrop_image("m1", 480, 80)     # a thumbnail, shown wide
    asked = [path.split("?")[1] for _, path in srv.calls]
    assert asked == ["maxHeight=1600&quality=90", "maxHeight=1066&quality=85", "maxWidth=480&quality=80"]


# ---------------------------------------------------------------- Silo's kept ids
def test_silo_looks_up_missing_ids_again_after_a_week(silo_run, monkeypatch):
    cfg, srv, eng = silo_run()
    save_json(srv.ids_file, {"series-tvdb-305288": {"imdb": "tt4574334", "tmdb": "66732", "tvdb": "305288"},
                             "series-tvdb-289574": {}, "series-tvdb-121361": {"tvdb": "121361"}})
    # as an older version kept them: no dates, and a 404 kept as {}

    def lookups():
        found = [c[1] for c in silo_run.fake.calls if c[1].startswith("/catalog/items/")]
        silo_run.fake.calls.clear()
        return sorted(found)
    eng.build_index()
    # the complete one is kept; the empty and partial ones and the new one are looked up
    assert lookups() == ["/catalog/items/series-tmdb-95396", "/catalog/items/series-tvdb-121361",
                         "/catalog/items/series-tvdb-289574"]
    kept = load_json(srv.ids_file, {})
    assert kept["series-tvdb-121361"]["ids"] == {"tvdb": "121361", "imdb": "tt0944947", "tmdb": "1399"}
    assert all("checked" in kept[cid] for cid in ("series-tvdb-121361", "series-tvdb-289574", "series-tmdb-95396"))
    eng.build_index()
    assert lookups() == []                                       # nothing is due yet
    week = time.time() + 8 * 24 * 3600
    monkeypatch.setattr(silo.time, "time", lambda: week)
    index = eng.build_index()
    assert lookups() == ["/catalog/items/series-tmdb-95396"]     # Silo has no TVDB id for it, so it's asked again
    assert index["show"]["imdb"]["tt0944947"] == "series-tvdb-121361"


# ---------------------------------------------------------------- Silo's artwork links
def artwork(make_cfg, monkeypatch, link, *storage):
    """backdrop_image for a title whose backdrop is at `link`, with storage giving these answers in turn."""
    srv = client(make_cfg, "silo", Answer(200, {"items": [{"id": "77", "is_primary": True}]}),
                 Answer(200, {"backdrop_url": link}))
    asked, answers = [], list(storage)

    def get(url, **kw):
        asked.append((url, kw))
        return answers.pop(0)
    monkeypatch.setattr(silo.requests, "get", get)
    return srv, asked


def test_the_api_key_goes_only_to_silos_own_scheme_host_and_port(make_cfg, monkeypatch, waits):
    srv, asked = artwork(make_cfg, monkeypatch, "https://127.0.0.1:8096/art/1.jpg", Answer(200, content=b"jpeg"))
    assert srv.backdrop_image("movie-tmdb-105") == b"jpeg"
    assert asked[0][0].startswith("https://") and "headers" not in asked[0][1]     # https isn't Silo's http address
    assert len(srv.session.sent) == 2                             # only the two API reads went with the key


def test_silo_can_send_artwork_on_to_its_storage(make_cfg, monkeypatch, waits):
    srv, asked = artwork(make_cfg, monkeypatch, "/api/v2/art/1.jpg", Answer(200, content=b"jpeg"))
    srv.session.answers.append(Answer(302, headers={"Location": "https://storage.example.com/1.jpg?signature=abc"}))
    assert srv.backdrop_image("movie-tmdb-105") == b"jpeg"
    assert srv.session.sent[2][1] == "http://127.0.0.1:8096/api/v2/art/1.jpg"      # Silo's own, with the key
    assert srv.session.sent[2][2]["allow_redirects"] is False
    assert asked[0][0] == "https://storage.example.com/1.jpg?signature=abc" and asked[0][1]["allow_redirects"] is False


def test_storage_redirects_are_followed_only_on_the_same_host(make_cfg, monkeypatch, waits):
    link = "https://storage.example.com/art/1.jpg?signature=abc"
    srv, asked = artwork(make_cfg, monkeypatch, link, Answer(307, headers={"Location": "/art/1-big.jpg"}),
                         Answer(200, content=b"jpeg"))
    assert srv.backdrop_image("movie-tmdb-105") == b"jpeg"
    assert asked[1][0] == "https://storage.example.com/art/1-big.jpg"
    srv, asked = artwork(make_cfg, monkeypatch, link, Answer(302, headers={"Location": "http://192.0.2.99/admin"}))
    with pytest.raises(ServerError, match="another host"):
        srv.backdrop_image("movie-tmdb-105")
    assert len(asked) == 1                                       # it stopped there


# ---------------------------------------------------------------- how long Silo rests
@pytest.mark.parametrize("took, floor, rest", [
    (0.05, 0.1, 0.05),     # a fast server: the writes are still a tenth of a second apart, not two tenths
    (0.3, 0.1, 0.3),       # a slower one rests as long as it worked
    (0.2, 1.0, 0.8),       # write_pause keeps other writes a second apart
    (30, 1.0, 10),         # and no pause is longer than ten seconds
])
def test_silo_rests_as_long_as_a_write_took_without_counting_it_twice(make_cfg, monkeypatch, took, floor, rest):
    clock, rests = [1000.0], []
    monkeypatch.setattr(servers.time, "time", lambda: clock[0])
    monkeypatch.setattr(servers.time, "sleep", rests.append)
    srv = client(make_cfg, "silo")

    def write(method, url, **kw):
        clock[0] += took
        return Answer(204)
    srv.session.request = write
    took_back = srv.timed("PUT", "/admin/collections/9/items/movie-tmdb-105", pause=floor, retry=True)[1]
    assert took_back == pytest.approx(took)
    assert rests == [pytest.approx(rest)]
