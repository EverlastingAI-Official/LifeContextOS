"""Punctuation-aware text segmentation for sentence-level streaming TTS."""

from __future__ import annotations

import re


STRONG_PUNCTUATION = frozenset("。！？!?；;\n")
SOFT_PUNCTUATION = frozenset("，,、：:")
CLOSING_MARKS = frozenset("”’\"'）)]】》〉」』")
CLOSING_MARK_CHARACTERS = "”’\"'）)]】》〉」』"


def _visible_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def segment_for_speech(
    text: str,
    *,
    soft_min_chars: int = 22,
    hard_max_chars: int = 72,
) -> list[str]:
    """Split speech at punctuation while retaining punctuation for prosody.

    Full stops, questions, exclamations and semicolons always close a segment.
    Commas and colons close only an already-long clause, avoiding choppy audio.
    The hard limit is a fallback for generated text containing no punctuation.
    """

    normalized = re.sub(r"[ \t\r\f\v]+", " ", text).strip()
    if not normalized:
        return []

    segments: list[str] = []
    buffer: list[str] = []
    index = 0
    while index < len(normalized):
        character = normalized[index]
        buffer.append(character)

        if character in STRONG_PUNCTUATION:
            while index + 1 < len(normalized) and normalized[index + 1] in CLOSING_MARKS:
                index += 1
                buffer.append(normalized[index])
            segment = "".join(buffer).strip()
            if segment:
                segments.append(segment)
            buffer = []
        elif character in SOFT_PUNCTUATION and _visible_length("".join(buffer)) >= soft_min_chars:
            segment = "".join(buffer).strip()
            if segment:
                segments.append(segment)
            buffer = []
        elif _visible_length("".join(buffer)) >= hard_max_chars:
            segment = "".join(buffer).strip()
            if segment:
                segments.append(segment)
            buffer = []
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        segments.append(tail)
    return segments


def pause_seconds_after(segment: str) -> float:
    """Return a small natural pause to place between synthesized segments."""

    ending = segment.rstrip(CLOSING_MARK_CHARACTERS).rstrip()
    if not ending:
        return 0.06
    if ending.endswith(("。", ".", "！", "!", "？", "?")):
        return 0.16
    if ending.endswith(("；", ";")):
        return 0.12
    if ending.endswith(("，", ",", "、", "：", ":")):
        return 0.07
    return 0.09
