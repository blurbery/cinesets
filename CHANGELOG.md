# Changelog

## [1.6.1](https://github.com/blurbery/cinesets/compare/v1.6.0...v1.6.1) (2026-10-10)


### Documentation

* **readme:** a link to the Discord ([2feecec](https://github.com/blurbery/cinesets/commit/2feecec06153189cf8e009155506c7724ce8cc85))

## [1.6.0](https://github.com/blurbery/cinesets/compare/v1.5.0...v1.6.0) (2026-10-09)


### Features

* **cli:** a fonts command that downloads the Japanese, Chinese and Korean font ahead of time ([#48](https://github.com/blurbery/cinesets/issues/48)) ([5192663](https://github.com/blurbery/cinesets/commit/51926631372af3f06e2dfd747369446f50ad4786))
* **collections:** fixed franchise lists can give each film's TMDB id, so a film a server names another way, like Zootropolis, still matches ([#46](https://github.com/blurbery/cinesets/issues/46)) ([10cfba2](https://github.com/blurbery/cinesets/commit/10cfba28c3b2a609a6d095f3124f30fb5e92dfad))
* **collections:** TMDB ids for 405 of the 407 films in the built-in franchises ([#46](https://github.com/blurbery/cinesets/issues/46)) ([10cfba2](https://github.com/blurbery/cinesets/commit/10cfba28c3b2a609a6d095f3124f30fb5e92dfad))
* **posters:** Japanese, Chinese and Korean text drawn in Noto Sans CJK, downloaded when first needed ([#48](https://github.com/blurbery/cinesets/issues/48)) ([5192663](https://github.com/blurbery/cinesets/commit/51926631372af3f06e2dfd747369446f50ad4786))
* **posters:** long Japanese, Chinese and Korean titles wrap between characters ([#48](https://github.com/blurbery/cinesets/issues/48)) ([5192663](https://github.com/blurbery/cinesets/commit/51926631372af3f06e2dfd747369446f50ad4786))
* **setup:** asks what to do about a server certificate it doesn't trust, and saves the answer as server.verify ([#45](https://github.com/blurbery/cinesets/issues/45)) ([b7b95af](https://github.com/blurbery/cinesets/commit/b7b95af4392cceeb3715713bd7d29a45e36d0e2b))
* **web:** the dashboard downloads the Japanese, Chinese and Korean font in the background and redraws the posters when it arrives ([#48](https://github.com/blurbery/cinesets/issues/48)) ([5192663](https://github.com/blurbery/cinesets/commit/51926631372af3f06e2dfd747369446f50ad4786))


### Bug fixes

* **logos:** a service's new logo now reaches servers that downloaded the old one ([#45](https://github.com/blurbery/cinesets/issues/45)) ([b7b95af](https://github.com/blurbery/cinesets/commit/b7b95af4392cceeb3715713bd7d29a45e36d0e2b))
* **logos:** Hulu has one logo instead of two copies of the same one ([#45](https://github.com/blurbery/cinesets/issues/45)) ([b7b95af](https://github.com/blurbery/cinesets/commit/b7b95af4392cceeb3715713bd7d29a45e36d0e2b))
* **logos:** Peacock's 2026 logo, with the 2020 one as its alternative ([#45](https://github.com/blurbery/cinesets/issues/45)) ([b7b95af](https://github.com/blurbery/cinesets/commit/b7b95af4392cceeb3715713bd7d29a45e36d0e2b))


### Documentation

* **preview:** pictures of the sections that gained collections, and the seasonal dates note kept when they're redrawn ([#45](https://github.com/blurbery/cinesets/issues/45)) ([b7b95af](https://github.com/blurbery/cinesets/commit/b7b95af4392cceeb3715713bd7d29a45e36d0e2b))

## [1.5.0](https://github.com/blurbery/cinesets/compare/v1.4.0...v1.5.0) (2026-10-09)


### Features

* **cli:** forget, to stop managing a collection and leave it on the server ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* **cli:** remove shows which collections it would delete before asking ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* **collections:** Binge, BBC iPlayer, ITVX, Channel 4, Crunchyroll, Shudder, the Criterion Collection, and Korean, Japanese, Indian, British and Australian collections ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))
* **collections:** fixed franchise lists also match titles written another way or a year out, never a remake ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))
* **collections:** franchises completed from TMDB, plus 22 new ones including Dune, Final Destination and Wicked ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))
* **collections:** seasonal collections have dates, and new Christmas movies, TV and kids collections ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))
* **collections:** two collections that would share a name get a note instead of being mixed up ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))
* **config:** warn about settings CineSets doesn't know, with a suggestion for typos ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* **docker:** a ready-made image for amd64 and arm64 on ghcr.io/blurbery/cinesets with each release ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* **docker:** an Unraid template ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* **install:** ./install.sh --uninstall takes only this folder's schedule off and says what else to do ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* **posters:** artwork can be set for a section or a single collection ([#40](https://github.com/blurbery/cinesets/issues/40)) ([326ed89](https://github.com/blurbery/cinesets/commit/326ed89ed87ebba7e97d6a0e1bd6f4ff9c7177e7))
* **posters:** logos for Binge, BBC iPlayer, Channel 4, Crunchyroll and Shudder, with alternative logos and icons for iPlayer and Crunchyroll ([#44](https://github.com/blurbery/cinesets/issues/44)) ([b96774d](https://github.com/blurbery/cinesets/commit/b96774d542af10e2985da1e82544105a4782c752))
* **posters:** mosaic artwork made from the collection's own posters in a 2x2 or 3x3 grid ([#40](https://github.com/blurbery/cinesets/issues/40)) ([326ed89](https://github.com/blurbery/cinesets/commit/326ed89ed87ebba7e97d6a0e1bd6f4ff9c7177e7))
* seasonal collections are removed outside their season ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* **servers:** ask Emby, Jellyfin and Silo for each title's own poster ([#40](https://github.com/blurbery/cinesets/issues/40)) ([326ed89](https://github.com/blurbery/cinesets/commit/326ed89ed87ebba7e97d6a0e1bd6f4ff9c7177e7))
* **servers:** server.verify for self-signed certificates (false, or a CA certificate file) ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **web:** a short getting-started note on first use ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** an optional web: hosts list that turns away other names, a defence against DNS rebinding ([#33](https://github.com/blurbery/cinesets/issues/33)) ([42d9629](https://github.com/blurbery/cinesets/commit/42d96299f66ead2394d447a7c5a0dff7ff17175e))
* **web:** Apply offers to save unsaved changes first ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** checking an MDBList list counts the type you pick and warns when too few are in your library to make a collection ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** on phones Save and Apply stay at the bottom, with a small copy of the poster while you scroll ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** smaller, faster previews in the strip and Preview all, with Try again when one fails ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** the Design tab offers mosaic artwork at every scope, with previews and tile shuffling ([#40](https://github.com/blurbery/cinesets/issues/40)) ([326ed89](https://github.com/blurbery/cinesets/commit/326ed89ed87ebba7e97d6a0e1bd6f4ff9c7177e7))
* **web:** the run log keeps growing past 500 lines and shows how each run went: its summary, any problems and whether it stopped early ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** undo and redo for poster designs, and Undo for removing a list, "Use the usual words" and resets ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))


### Bug fixes

* a poster or artwork problem no longer stops a collection's titles updating ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* CineSets never takes over or loses a collection because another one shares its name ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* **collections:** franchises need fewer of their films, so a library missing one still gets the collection ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))
* **collections:** stale or odd lists replaced (Most Watched, DC, Star Wars, MCU shows, Preschool, Popular Animation, Peacock), and Middle-earth and John Wick are fixed lists ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))
* **collections:** The Evil Dead uses TMDB's year (1983), so it matches ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))
* **docker:** the compose example can run a second install, with a port per install and a dashboard healthcheck ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* **emby/jellyfin:** ask for artwork tall enough for a sharp poster ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **emby/jellyfin:** delete only items that are collections ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **emby/jellyfin:** page through libraries in a fixed order and warn when fewer titles come back than the server counted ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **emby/jellyfin:** say clearly when the API key can see no administrator ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **install:** a Python environment broken by a Python upgrade is made again, and run.sh says so ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* **install:** CineSets runs as the folder's owner, switching from root when it can, and cron.example uses that user ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* **install:** the installer says when there's no cron instead of asking to run it again ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* keep a backup of state.json, and explain a broken config.yml or state.json instead of showing a traceback ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* **logos:** renamed logos are found, one missing logo no longer stops the rest, and a cut-off download never leaves a broken file ([#43](https://github.com/blurbery/cinesets/issues/43)) ([ffc73f9](https://github.com/blurbery/cinesets/commit/ffc73f90dc09d8d7d0d95a4e4069965ceac14a99))
* plan, posters and apply end with a Summary line and exit with 1 when something failed or the run stopped early ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* **posters:** artwork is turned by its EXIF orientation and converted to sRGB when it has another colour profile ([#43](https://github.com/blurbery/cinesets/issues/43)) ([ffc73f9](https://github.com/blurbery/cinesets/commit/ffc73f90dc09d8d7d0d95a4e4069965ceac14a99))
* **posters:** Greek, Cyrillic and Vietnamese letters are drawn in Noto Sans instead of as boxes ([#43](https://github.com/blurbery/cinesets/issues/43)) ([ffc73f9](https://github.com/blurbery/cinesets/commit/ffc73f90dc09d8d7d0d95a4e4069965ceac14a99))
* **posters:** long titles go onto two lines and shrink further, and long labels and streaming subtitles shrink, so text stays on the poster ([#43](https://github.com/blurbery/cinesets/issues/43)) ([ffc73f9](https://github.com/blurbery/cinesets/commit/ffc73f90dc09d8d7d0d95a4e4069965ceac14a99))
* **posters:** streaming posters made before their logo was downloaded are drawn again with it, and so are posters whose text ran off or had missing letters ([#43](https://github.com/blurbery/cinesets/issues/43)) ([ffc73f9](https://github.com/blurbery/cinesets/commit/ffc73f90dc09d8d7d0d95a4e4069965ceac14a99))
* **posters:** text over artwork too bright to read gets the artwork darkened just behind it, and a near-black text colour is lightened ([#43](https://github.com/blurbery/cinesets/issues/43)) ([ffc73f9](https://github.com/blurbery/cinesets/commit/ffc73f90dc09d8d7d0d95a4e4069965ceac14a99))
* **posters:** very wide or very tall artwork no longer uses hundreds of megabytes while it's cropped ([#43](https://github.com/blurbery/cinesets/issues/43)) ([ffc73f9](https://github.com/blurbery/cinesets/commit/ffc73f90dc09d8d7d0d95a4e4069965ceac14a99))
* **servers:** retry reads and repeatable writes after a dropped connection, a timeout or a busy server, honouring Retry-After, but never resend making a collection ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **servers:** say what to do when the server refuses the API key, the address is wrong, a proxy rejects a poster upload, the server is rate limiting, or its certificate isn't trusted ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **servers:** tidy only the path of a pasted address, so servers named emby or web keep their names, and tidy addresses in config.yml and CINESETS_URL too ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **silo:** look up missing show ids again after a week instead of keeping a gap forever ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* **silo:** send the API key for artwork only to Silo's own scheme, host and port, and follow storage redirects only on the same host ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))
* stop the run when the server turns down the API key or keeps asking CineSets to slow down ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* the Docker scheduler retries a job that didn't finish after about an hour, remembers when jobs ran, and stops cleanly on docker stop ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* wait out MDBList's rate limit politely, and warn every run about a list that keeps failing ([#36](https://github.com/blurbery/cinesets/issues/36)) ([f2a6c35](https://github.com/blurbery/cinesets/commit/f2a6c35255f48565404ab052b334ae001a91cb81))
* **web:** a collection's new words can't give it another collection's name ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** better contrast, larger touch targets, 16px fields on phones, and focus that follows the Design buttons ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** create web.json readable only by you on filesystems without hard links ([#33](https://github.com/blurbery/cinesets/issues/33)) ([42d9629](https://github.com/blurbery/cinesets/commit/42d96299f66ead2394d447a7c5a0dff7ff17175e))
* **web:** error messages stay until dismissed, and the unsaved state keeps its word on narrow screens ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** on touch screens a tap previews artwork and "Use this" keeps it ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** people who aren't signed in and slow uploads can no longer fill the dashboard's busy slots ([#33](https://github.com/blurbery/cinesets/issues/33)) ([42d9629](https://github.com/blurbery/cinesets/commit/42d96299f66ead2394d447a7c5a0dff7ff17175e))
* **web:** refuse a negative Content-Length, oversized sign-in bodies and overlong session cookies ([#33](https://github.com/blurbery/cinesets/issues/33)) ([42d9629](https://github.com/blurbery/cinesets/commit/42d96299f66ead2394d447a7c5a0dff7ff17175e))
* **web:** setting, changing or removing the dashboard password signs everyone out ([#33](https://github.com/blurbery/cinesets/issues/33)) ([42d9629](https://github.com/blurbery/cinesets/commit/42d96299f66ead2394d447a7c5a0dff7ff17175e))
* **web:** the access key always signs in, and only wrong passwords are rate limited, with the wait shown in minutes ([#33](https://github.com/blurbery/cinesets/issues/33)) ([42d9629](https://github.com/blurbery/cinesets/commit/42d96299f66ead2394d447a7c5a0dff7ff17175e))
* **web:** the dashboard keeps the run log when it restarts mid-run, and shows one banner that retries by itself when CineSets can't be reached ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))
* **web:** the Design tab names Noto Sans as the last fallback font and says when Auto adds a text shadow ([#44](https://github.com/blurbery/cinesets/issues/44)) ([b96774d](https://github.com/blurbery/cinesets/commit/b96774d542af10e2985da1e82544105a4782c752))
* **web:** warn when public mode listens beyond this machine ([#33](https://github.com/blurbery/cinesets/issues/33)) ([42d9629](https://github.com/blurbery/cinesets/commit/42d96299f66ead2394d447a7c5a0dff7ff17175e))
* **web:** words typed in the Text card count as unsaved, are saved by Save and Ctrl+S, and aren't lost without asking ([#34](https://github.com/blurbery/cinesets/issues/34)) ([890219a](https://github.com/blurbery/cinesets/commit/890219a219309d70bc8687d0daa6c64a14225ded))


### Performance

* **posters:** fonts are kept once loaded, and logos and gradient titles are drawn much faster ([#43](https://github.com/blurbery/cinesets/issues/43)) ([ffc73f9](https://github.com/blurbery/cinesets/commit/ffc73f90dc09d8d7d0d95a4e4069965ceac14a99))
* **silo:** pause between writes only as long as each write calls for, roughly halving a first run on a fast server ([#35](https://github.com/blurbery/cinesets/issues/35)) ([72fcf2f](https://github.com/blurbery/cinesets/commit/72fcf2f7598295759bf3ece840dc6ec38d87217f))


### Dependencies

* tested dependency versions in constraints.txt, used by install.sh, Docker and CI ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* update pytest requirement from &gt;=7.0 to &gt;=8.4.2 ([#42](https://github.com/blurbery/cinesets/issues/42)) ([bd9d6b3](https://github.com/blurbery/cinesets/commit/bd9d6b3bb74c51f86a64bc8a7b172948fc737e69))


### Documentation

* **dashboard:** give the dashboard a name of its own rather than a path on an existing site ([#33](https://github.com/blurbery/cinesets/issues/33)) ([42d9629](https://github.com/blurbery/cinesets/commit/42d96299f66ead2394d447a7c5a0dff7ff17175e))
* how release notes work, and how to merge a release pull request ([#31](https://github.com/blurbery/cinesets/issues/31)) ([b931a58](https://github.com/blurbery/cinesets/commit/b931a58f51bada8ff84063e2ffc3a3f8c344b9ca))
* mosaic artwork in the README, example config, preview and dashboard guide ([#40](https://github.com/blurbery/cinesets/issues/40)) ([326ed89](https://github.com/blurbery/cinesets/commit/326ed89ed87ebba7e97d6a0e1bd6f4ff9c7177e7))
* uninstalling, Docker from ghcr.io, and Unraid, TrueNAS SCALE and Synology ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))


### Tests

* **collections:** a checker for every MDBList list in the catalogue ([#37](https://github.com/blurbery/cinesets/issues/37)) ([208c9cb](https://github.com/blurbery/cinesets/commit/208c9cb33b6b8981491500a2d79e2ce97b54af6f))


### Continuous integration

* a pull request can list several changes in its release notes box, each with its own line in the notes ([#31](https://github.com/blurbery/cinesets/issues/31)) ([b931a58](https://github.com/blurbery/cinesets/commit/b931a58f51bada8ff84063e2ffc3a3f8c344b9ca))
* every merged pull request gets a line in the release notes, docs and refactors included ([#31](https://github.com/blurbery/cinesets/issues/31)) ([b931a58](https://github.com/blurbery/cinesets/commit/b931a58f51bada8ff84063e2ffc3a3f8c344b9ca))
* every push to main gets a full CI run instead of being cancelled by the next one ([#31](https://github.com/blurbery/cinesets/issues/31)) ([b931a58](https://github.com/blurbery/cinesets/commit/b931a58f51bada8ff84063e2ffc3a3f8c344b9ca))
* keep pytest below 9 while CineSets supports Python 3.9 ([#41](https://github.com/blurbery/cinesets/issues/41)) ([cdbfb3d](https://github.com/blurbery/cinesets/commit/cdbfb3d4a9e6950995205395e19a390bf40ce911))
* the release pull request can come from a GitHub App so its checks start by themselves ([#31](https://github.com/blurbery/cinesets/issues/31)) ([b931a58](https://github.com/blurbery/cinesets/commit/b931a58f51bada8ff84063e2ffc3a3f8c344b9ca))
* unit tests on Python 3.10, 3.11 and 3.14, a lint job, pinned actions and Dependabot ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))
* weekly checks of the newest servers and of every MDBList list that fail when something breaks ([#38](https://github.com/blurbery/cinesets/issues/38)) ([c0b1ecf](https://github.com/blurbery/cinesets/commit/c0b1ecf5c6efa23602f5670dfc7ddc94e1317fa6))

## [1.4.0](https://github.com/blurbery/cinesets/compare/v1.3.1...v1.4.0) (2026-10-08)


### Features

* **posters:** a choice of fonts ([#29](https://github.com/blurbery/cinesets/issues/29)) ([c20a8e0](https://github.com/blurbery/cinesets/commit/c20a8e07f9e066e063acc86786a8f256cf3f11fe))

## [1.3.1](https://github.com/blurbery/cinesets/compare/v1.3.0...v1.3.1) (2026-10-07)


### Bug fixes

* **web:** tidy up when stopped by docker stop or systemctl stop, and make the access key safely ([#26](https://github.com/blurbery/cinesets/issues/26)) ([2573de0](https://github.com/blurbery/cinesets/commit/2573de01388ea8602a916496792b2c94a0b90ac6))

## [1.3.0](https://github.com/blurbery/cinesets/compare/v1.2.0...v1.3.0) (2026-10-07)


### Features

* Silo support ([#17](https://github.com/blurbery/cinesets/issues/17)) ([61c37dd](https://github.com/blurbery/cinesets/commit/61c37dd4e05cb649cdb64f17dd0a5c167af04374))

## [1.2.0](https://github.com/blurbery/cinesets/compare/v1.1.0...v1.2.0) (2026-10-07)


### Features

* **setup:** a simpler setup that finishes the job ([#14](https://github.com/blurbery/cinesets/issues/14)) ([d9b9efe](https://github.com/blurbery/cinesets/commit/d9b9efe93362fa05bfef0ae73f695cd338799f94))

## [1.1.0](https://github.com/blurbery/cinesets/compare/v1.0.1...v1.1.0) (2026-10-07)


### Features

* a dashboard to pick, design and preview collections ([#12](https://github.com/blurbery/cinesets/issues/12)) ([3cefecd](https://github.com/blurbery/cinesets/commit/3cefecd1467ca59b89dd2ac07064e46703ce0219))
* pick which sections and collections to make ([#10](https://github.com/blurbery/cinesets/issues/10)) ([e72cc54](https://github.com/blurbery/cinesets/commit/e72cc541af5829d9225aceb2ff36ba532096156e))
* **posters:** colour, shade and text settings, and random artwork for each install ([#9](https://github.com/blurbery/cinesets/issues/9)) ([d2cff32](https://github.com/blurbery/cinesets/commit/d2cff32f04ab4e9efc0896ffd76ce09cd89cf264))

## [1.0.1](https://github.com/blurbery/cinesets/compare/v1.0.0...v1.0.1) (2026-10-06)


### Bug fixes

* keep titles that are in collections on Jellyfin 12 ([#7](https://github.com/blurbery/cinesets/issues/7)) ([82ad8fc](https://github.com/blurbery/cinesets/commit/82ad8fc1b4e862fad400c43bacecd65894a9d1d5))
* read every page of libraries and collections, whatever their size ([#6](https://github.com/blurbery/cinesets/issues/6)) ([2f58e2f](https://github.com/blurbery/cinesets/commit/2f58e2f12b2fc9c3c8bc0c433545d088d0c813ae))

## [1.0.0](https://github.com/blurbery/cinesets/releases/tag/v1.0.0) (2026-10-06)

First public release.
