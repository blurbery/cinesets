# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Automatic, beautiful collections for Emby, Jellyfin and Silo.
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""CineSets builds and maintains media server collections with generated posters."""

__version__ = "1.6.0"
__author__ = "blurbery"

import warnings

from PIL import Image

# Artwork comes from the media server and its storage, so a picture CineSets didn't make is untrusted. Pillow only
# warns up to about 179 million pixels, and a small file can claim that many and take gigabytes to decode. Nothing
# CineSets reads comes near 12.5 million (a 4K backdrop is 8 million): Pillow refuses anything over twice the limit
# outright, and the warning it gives between the two is made an error too.
Image.MAX_IMAGE_PIXELS = 12_500_000
warnings.simplefilter("error", Image.DecompressionBombWarning)

