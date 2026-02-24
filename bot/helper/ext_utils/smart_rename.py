# -*- coding: utf-8 -*-
"""
Smart rename helper for KPSML/WZML-X style bots.

Usage:
    from bot.helper.ext_utils.smart_rename import smart_rename_movie
    new_name = smart_rename_movie(old_name, skip_series=False)

Notes:
- Works for both movies and series (when skip_series=False).
- If skip_series=True and filename looks like a series episode (S01E02 etc), it will return original.
"""

import re

JUNK_PATTERNS = [
    r"\bx264\b", r"\bx265\b", r"\bhevc\b", r"\besub\b",
    r"\bvega[a-z]*movies\b", r"\bvegamovies\b", r"\bhot\b",
]

_SERIES_RE = re.compile(
    r"(?i)\bS\d{1,2}E\d{1,2}\b|\bSeason\s*\d+\b|\bEp(?:isode)?\s*\d+\b|\bE\d{1,3}\b"
)

def is_series(name: str) -> bool:
    """Return True if name looks like a series episode."""
    return bool(_SERIES_RE.search(name or ""))

def _clean_spaces(s: str) -> str:
    return re.sub(r"\s{2,}", " ", s).strip()

def smart_rename_movie(filename: str, skip_series: bool = True) -> str:
    """
    Rename a release-style filename into a cleaner title line.

    Example:
      Queen.of.Chess.2026.480p.WEB-DL.HIN-ENG.x264.ESub-Vegamovies.Hot.mkv
      -> Queen of Chess 2026 Dual Audio Hindi English WEB-DL 480p.mkv
    """
    original = (filename or "").strip()
    if not original:
        return filename

    if skip_series and is_series(original):
        return filename

    # Extension
    ext = ""
    m = re.search(r"(?i)\.(mkv|mp4|avi)$", original)
    if m:
        ext = "." + m.group(1).lower()
        name = original[:m.start()]
    else:
        name = original

    s = name

    # separators -> space
    s = re.sub(r"[._-]+", " ", s)

    # Dual audio normalize (covers: HIN-ENG / HIN ENG / Hindi ENG / Hindi English)
    s = re.sub(r"(?i)\bhin\s*-\s*eng\b|\bhin\s*eng\b|\bhindi\s*eng(?:lish)?\b", "Dual Audio Hindi English", s)

    # WEB-DL normalize
    s = re.sub(r"(?i)\bweb\s*dl\b", "WEB-DL", s)

    # Remove junk words
    for p in JUNK_PATTERNS:
        s = re.sub(rf"(?i){p}", "", s)

    # Remove brackets
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)

    s = _clean_spaces(s)

    # Capture resolution
    res  = re.search(r"\b(480p|720p|1080p|2160p|4k)\b", s, re.I)

    has_webdl = bool(re.search(r"(?i)\bWEB-DL\b", s))
    has_dual  = bool(re.search(r"(?i)\bDual Audio Hindi English\b", s))

    # Remove tokens from middle (we’ll place them at end)
    s2 = re.sub(r"(?i)\bWEB-DL\b", "", s)
    s2 = re.sub(r"(?i)\bDual Audio Hindi English\b", "", s2)
    s2 = re.sub(r"(?i)\b(480p|720p|1080p|2160p|4k)\b", "", s2)
    s2 = _clean_spaces(s2)

    tail = []
    if has_dual:
        tail.append("Dual Audio Hindi English")
    if has_webdl:
        tail.append("WEB-DL")
    if res:
        r = res.group(1)
        tail.append(r.upper() if r.lower() == "4k" else r.lower())

    final = (s2 + (" " if s2 and tail else "") + " ".join(tail)).strip()
    final = _clean_spaces(final)

    return final + ext
