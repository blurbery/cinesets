# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The shell: every question the centre asks a media server, and nothing else.

Each server module (emby.py, jellyfin.py, silo.py) subclasses Server and answers every one of these itself, even
when the answer is "nothing to do", so no server inherits behaviour it didn't choose and a change to one server
can't reach another. The engine, the dashboard and setup call only these; tests/test_layout.py checks that, and
that every module answers them all."""


class Server:
    # setup: the server's type in config.yml, where its API keys are made, and anything setup should say about the
    # key (None for nothing). Its name is in SERVERS in servers/__init__.py.
    TYPE = ""
    KEY_PAGE = ""
    SETUP_NOTE = None

    @staticmethod
    def detect(url, verify=True):
        """(server type, its own address or None to ask for it, a note for setup or None) if this server answers at
        `url`, from its public information (no API key), or None if it isn't this server. `verify` is server.verify,
        for the server's certificate."""
        raise NotImplementedError

    @staticmethod
    def trim(url):
        """A pasted browser address, tidied (a web app page on the end of its path taken off, never part of the host's
        name)."""
        raise NotImplementedError

    # ------------------------------------------------------------ reads
    def media_libraries(self):
        """[(name, "movie" or "show")] for setup: the libraries worth listing in config.yml, the main one of each
        type first."""
        raise NotImplementedError

    def library_folders(self):
        """{library name: the server's id for it}."""
        raise NotImplementedError

    def library_items(self, folder, kind, name):
        """Every title in one library: [{"id", "name", "year", "ids": {"tmdb"/"imdb"/"tvdb": id}, "backdrop": bool,
        "poster": bool}], plus "genres" when the server lists them with the titles (the index then keeps them)."""
        raise NotImplementedError

    def genres(self, ids):
        """{item id: {lower-case genre}} for these items."""
        raise NotImplementedError

    def alive(self, ids):
        """The ones of these item ids the server still has."""
        raise NotImplementedError

    def backdrop_image(self, item_id, width=1920, quality=90):
        """An item's backdrop as image bytes."""
        raise NotImplementedError

    def poster_image(self, item_id, width=400, quality=90):
        """A title's own poster (its primary image) as JPEG bytes, about `width` wide: a tile in a mosaic poster."""
        raise NotImplementedError

    # ------------------------------------------------------------ collections
    def admin_user(self):
        """Whatever the collection calls below need as `user_id` (and a clear error if the key can't make
        collections)."""
        raise NotImplementedError

    def list_collections(self):
        """{collection id: name} for every collection on the server."""
        raise NotImplementedError

    def narrow(self, coll, ids):
        """The matched titles (in order) this collection can hold on this server."""
        raise NotImplementedError

    def create_collection(self, name, coll, ids):
        """Make a collection holding `ids`. Returns (its id, how long the slowest write took)."""
        raise NotImplementedError

    def wait_until_ready(self, cid, user_id):
        """Return once a new collection can take titles, a poster and details."""
        raise NotImplementedError

    def prepare(self, cid, coll):
        """Get an existing collection ready before its titles are brought up to date."""
        raise NotImplementedError

    def members(self, cid, user_id):
        """The set of item ids a collection holds."""
        raise NotImplementedError

    def add_items(self, cid, ids):
        """Add these items. Returns the slowest write."""
        raise NotImplementedError

    def remove_items(self, cid, ids):
        """Take these items out. Returns the slowest write."""
        raise NotImplementedError

    def upload_poster(self, cid, raw, user_id):
        """Upload a JPEG poster. Returns (whether the server kept it, how long the write took)."""
        raise NotImplementedError

    def set_details(self, cid, user_id, coll, name):
        """Name, description, sort and display order. Returns how long the write took."""
        raise NotImplementedError

    def delete_collection(self, cid):
        """Delete a collection CineSets made."""
        raise NotImplementedError

    def arrange(self, owned):
        """After a run: put CineSets' collections ({key: id}) in Collections page order, if the server needs telling."""
        raise NotImplementedError
