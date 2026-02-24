#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smart_rename.py - KPSML/WZML smart rename helper

Goal:
- Clean junk tags (x264/x265/HEVC/ESub/site tags)
- Normalize separators
- Detect year + quality
- Detect languages dynamically (codes or names) and add:
    - "Dual Audio <Lang1> <Lang2>" when 2 langs
    - "Multi Audio <Lang1> <Lang2> ..." when 3+ langs
- Keep WEB-DL/WEBRip/BluRay/HDRip tags (if present)
- Works for Movies + Series (set skip_series=False to also rename series)
"""

from __future__ import annotations

import re
from typing import List, Set, Tuple

try:
    # Project already uses langcodes in other utils.
    from langcodes import Language
except Exception:  # pragma: no cover
    Language = None  # type: ignore


# --- junk/site/codec tokens to remove ---
JUNK_PATTERNS = [
    r"\bx264\b", r"\bx265\b", r"\bh\.?264\b", r"\bh\.?265\b",
    r"\bhevc\b", r"\b10bit\b", r"\b8bit\b",
    r"\besub\b", r"\bsub\b", r"\bsubs\b",
    r"\bvega[a-z]*movies\b", r"\bvegamovies\b", r"\bhot\b",
    r"\byts\b", r"\byify\b", r"\bevo\b", r"\bganool\b",
    r"\bmkvcage\b", r"\bmkvcinemas\b", r"\b(psa|rarbg|ettv)\b",
]

# Sometimes people include "HIN ENG" etc.
LANG_CODE_TOKEN_RE = re.compile(r"(?i)\b([a-z]{2,3})\b")

# Common language name aliases -> canonical display name
LANG_NAME_ALIASES = {
    "eng": "English",
    "english": "English",
    "en": "English",

    "hin": "Hindi",
    "hindi": "Hindi",
    "hi": "Hindi",

    "tam": "Tamil",
    "tamil": "Tamil",

    "tel": "Telugu",
    "telugu": "Telugu",

    "mal": "Malayalam",
    "malayalam": "Malayalam",

    "kan": "Kannada",
    "kannada": "Kannada",

    "ben": "Bengali",
    "bangla": "Bengali",
    "bengali": "Bengali",

    "urd": "Urdu",
    "urdu": "Urdu",

    "ara": "Arabic",
    "arabic": "Arabic",

    "fre": "French",
    "fra": "French",
    "french": "French",

    "ger": "German",
    "deu": "German",
    "german": "German",

    "spa": "Spanish",
    "spanish": "Spanish",

    "ita": "Italian",
    "italian": "Italian",

    "por": "Portuguese",
    "portuguese": "Portuguese",

    "rus": "Russian",
    "russian": "Russian",

    "tur": "Turkish",
    "turkish": "Turkish",

    "zho": "Chinese",
    "chi": "Chinese",
    "chinese": "Chinese",

    "jpn": "Japanese",
    "japanese": "Japanese",

    "kor": "Korean",
    "korean": "Korean",

    "fil": "Filipino",
    "tl": "Filipino",
    "tagalog": "Filipino",
    "filipino": "Filipino",

    "ind": "Indonesian",
    "indonesian": "Indonesian",

    "tha": "Thai",
    "thai": "Thai",

    "vie": "Vietnamese",
    "vietnamese": "Vietnamese",
}

# Release/Source tags we keep and normalize
SOURCE_TAGS = [
    ("WEB-DL", re.compile(r"(?i)\bweb\s*[-_. ]?\s*dl\b")),
    ("WEBRip", re.compile(r"(?i)\bweb\s*[-_. ]?\s*rip\b")),
    ("BluRay", re.compile(r"(?i)\bblu\s*[-_. ]?\s*ray\b|\bbluray\b")),
    ("HDRip",  re.compile(r"(?i)\bh\s*[-_. ]?\s*d\s*[-_. ]?\s*rip\b|\bhdrip\b")),
    ("DVDRip", re.compile(r"(?i)\bdvd\s*[-_. ]?\s*rip\b|\bdvdrip\b")),
]


def is_series(name: str) -> bool:
    return bool(re.search(r"(?i)\bS\d{1,2}E\d{1,2}\b|\bSeason\s*\d+\b|\bEp(?:isode)?\s*\d+\b|\bE\d{1,3}\b", name))


def _split_ext(filename: str) -> Tuple[str, str]:
    m = re.search(r"(?i)\.(mkv|mp4|avi|mov|m4v)$", filename.strip())
    if not m:
        return filename, ""
    return filename[:m.start()], "." + m.group(1).lower()


def _clean_separators(s: str) -> str:
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"[-]{2,}", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _extract_languages(raw: str) -> List[str]:
    s = raw.lower()
    found: List[str] = []
    used: Set[str] = set()

    # 1) strong matches like "hindi", "english", etc.
    for key, disp in LANG_NAME_ALIASES.items():
        if re.search(rf"(?i)\b{re.escape(key)}\b", raw):
            if disp.lower() not in used:
                found.append(disp)
                used.add(disp.lower())

    # 2) ISO 2-3 letter codes (best effort via langcodes)
    if Language is not None:
        for m in LANG_CODE_TOKEN_RE.finditer(raw):
            code = m.group(1).lower()
            # skip common non-language junk tokens
            if code in {"web", "dl", "rip", "hdr", "aac", "dts", "ddp", "atm"}:
                continue
            if code in LANG_NAME_ALIASES:
                disp = LANG_NAME_ALIASES[code]
                if disp.lower() not in used:
                    found.append(disp)
                    used.add(disp.lower())
                continue
            try:
                disp = Language.get(code).display_name()
                disp = disp.split(" (", 1)[0].strip()
                if disp and disp.lower() not in used:
                    found.append(disp)
                    used.add(disp.lower())
            except Exception:
                pass

    return found


def _remove_language_tokens(s: str) -> str:
    # Remove existing "Dual Audio"/"Multi Audio" phrases + known language tokens
    s = re.sub(r"(?i)\bdual\s*audio\b", " ", s)
    s = re.sub(r"(?i)\bmulti\s*audio\b", " ", s)

    for key in sorted(LANG_NAME_ALIASES.keys(), key=len, reverse=True):
        s = re.sub(rf"(?i)\b{re.escape(key)}\b", " ", s)

    # Remove paired code patterns like "HIN ENG"
    s = re.sub(r"(?i)\b[a-z]{2,3}\b\s*[-_. ]\s*\b[a-z]{2,3}\b", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def smart_rename(filename: str, skip_series: bool = False) -> str:
    original = filename
    if skip_series and is_series(original):
        return original

    name, ext = _split_ext(original)
    s = _clean_separators(name)

    # Normalize source tag
    source = None
    for tag, rx in SOURCE_TAGS:
        if rx.search(s):
            source = tag
            s = rx.sub(" ", s)
            break

    # Quality
    res = None
    mres = re.search(r"(?i)\b(480p|540p|720p|1080p|1440p|2160p|4k)\b", s)
    if mres:
        res = mres.group(1)
        s = re.sub(r"(?i)\b(480p|540p|720p|1080p|1440p|2160p|4k)\b", " ", s)

    # Languages
    langs = _extract_languages(s)
    s = _remove_language_tokens(s)

    # Remove junk patterns
    for p in JUNK_PATTERNS:
        s = re.sub(rf"(?i){p}", " ", s)

    # Remove brackets
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()

    tail: List[str] = []
    if langs:
        if len(langs) == 2:
            tail.append("Dual Audio " + " ".join(langs))
        elif len(langs) > 2:
            tail.append("Multi Audio " + " ".join(langs))

    if source:
        tail.append(source)
    if res:
        tail.append(res.upper() if res.lower() == "4k" else res.lower())

    final = (s + (" " if s and tail else "") + " ".join(tail)).strip()
    final = re.sub(r"\s{2,}", " ", final).strip()
    return final + ext


# Backward compatible alias (some patches used smart_rename_movie name)
def smart_rename_movie(filename: str, skip_series: bool = True) -> str:
    return smart_rename(filename, skip_series=skip_series)
