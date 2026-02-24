import re

# Unwanted/Junk tokens to remove
JUNK_PATTERNS = [
    r"\bx264\b", r"\bx265\b", r"\bhevc\b", r"\besub\b",
    r"\bvega[a-z]*movies\b", r"\bvegamovies\b", r"\bhot\b",
]

VIDEO_EXT_RE = re.compile(r"(?i)\.(mkv|mp4|avi)$")

SERIES_RE = re.compile(
    r"(?i)\bS\d{1,2}E\d{1,2}\b|\bSeason\s*\d+\b|\bEp(?:isode)?\s*\d+\b|\bE\d{1,3}\b"
)

DUAL_RE = re.compile(
    r"(?i)\bhin\s*eng\b|\bhin\s*-\s*eng\b|\bhindi\s*eng(?:lish)?\b|\bhin[-_ ]?eng\b"
)

WEBDL_RE = re.compile(r"(?i)\bweb\s*dl\b")


def is_series(name: str) -> bool:
    return bool(SERIES_RE.search(name or ""))


def _normalize_resolution_token(token: str) -> str:
    t = token.lower()
    if t == "4k":
        return "4K"
    return t  # 480p, 720p, 1080p, 2160p


def smart_rename_movie(filename: str, skip_series: bool = False) -> str:
    """
    Cleans movie/series filenames and makes a nice format like:
    Queen of Chess 2026 Dual Audio Hindi English WEB-DL 480p.mkv

    If skip_series=True then it won't rename series-like names.
    """
    original = (filename or "").strip()
    if not original:
        return filename

    if skip_series and is_series(original):
        return filename

    # Extension separate
    ext = ""
    m = VIDEO_EXT_RE.search(original)
    if m:
        ext = "." + m.group(1).lower()
        name = original[: m.start()]
    else:
        name = original

    s = name

    # separators -> space
    s = re.sub(r"[._-]+", " ", s)

    # WEB-DL normalize (do it early)
    s = WEBDL_RE.sub("WEB-DL", s)

    # Dual audio normalize (avoid duplicates later)
    # First: remove any existing "Dual Audio Hindi English" duplicates then re-add once at tail
    s = DUAL_RE.sub("Dual Audio Hindi English", s)

    # Remove junk words
    for p in JUNK_PATTERNS:
        s = re.sub(rf"(?i){p}", " ", s)

    # Remove brackets
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)

    # Clean multiple spaces
    s = re.sub(r"\s{2,}", " ", s).strip()

    # Detect resolution
    res = re.search(r"(?i)\b(480p|720p|1080p|2160p|4k)\b", s)

    # Flags
    has_webdl = bool(re.search(r"(?i)\bWEB-DL\b", s))
    has_dual = bool(re.search(r"(?i)\bDual Audio Hindi English\b", s))

    # Remove these tokens from middle (we place at end nicely)
    s2 = re.sub(r"(?i)\bWEB-DL\b", " ", s)
    s2 = re.sub(r"(?i)\bDual Audio Hindi English\b", " ", s2)
    s2 = re.sub(r"(?i)\b(480p|720p|1080p|2160p|4k)\b", " ", s2)
    s2 = re.sub(r"\s{2,}", " ", s2).strip()

    tail = []
    if has_dual:
        tail.append("Dual Audio Hindi English")
    if has_webdl:
        tail.append("WEB-DL")
    if res:
        tail.append(_normalize_resolution_token(res.group(1)))

    final = (s2 + (" " if s2 and tail else "") + " ".join(tail)).strip()
    final = re.sub(r"\s{2,}", " ", final).strip()

    return final + ext
