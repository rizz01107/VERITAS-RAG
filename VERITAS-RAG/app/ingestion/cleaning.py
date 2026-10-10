"""Text cleaning that is deliberately conservative: it must not corrupt math or Unicode.

Only these changes are made: NFC normalisation, ligature expansion, soft-hyphen and
zero-width removal, exotic spaces to ' ', control-character removal, whitespace
collapse, and vocabulary-checked de-hyphenation. NFKC is *not* used (it would turn
e.g. superscripts and many math symbols into plain letters/digits).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
}
_SPACE_LIKE = {0x00A0: " ", 0x2002: " ", 0x2003: " ", 0x2007: " ", 0x2009: " ", 0x202F: " "}
_REMOVE = {0x200B: None, 0xFEFF: None, 0x00AD: None}
# Observed in real pdfTeX output: \Delta is extracted as U+2206 (INCREMENT) instead of
# U+0394 (GREEK CAPITAL LETTER DELTA), which breaks matching with queries/LLM text.
_CONFUSABLES = {0x2206: "\u0394"}
_HYPHENS = ("-", "\u2010", "\u2011")
_WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
_PRIVATE_USE = range(0xE000, 0xF900)


@dataclass(frozen=True)
class CleanStats:
    """Counts of what cleaning changed or detected (never silent)."""

    ligatures: int = 0
    replacement_chars: int = 0
    private_use_chars: int = 0
    dehyphenated: int = 0
    symbols_normalized: int = 0

    def __add__(self, other: CleanStats) -> CleanStats:
        return CleanStats(
            self.ligatures + other.ligatures,
            self.replacement_chars + other.replacement_chars,
            self.private_use_chars + other.private_use_chars,
            self.dehyphenated + other.dehyphenated,
            self.symbols_normalized + other.symbols_normalized,
        )


def clean_text(text: str) -> tuple[str, CleanStats]:
    """Clean one line/paragraph; report ligature count and encoding-corruption indicators."""
    out = unicodedata.normalize("NFC", text)
    n_lig = sum(out.count(lig) for lig in LIGATURES)
    for lig, repl in LIGATURES.items():
        out = out.replace(lig, repl)
    n_sym = sum(out.count(chr(code)) for code in _CONFUSABLES)
    out = out.translate(_REMOVE).translate(_SPACE_LIKE).translate(_CONFUSABLES)
    out = "".join(ch for ch in out if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    out = re.sub(r"[ \t]+", " ", out)
    out = "\n".join(line.strip() for line in out.split("\n")).strip()
    stats = CleanStats(
        ligatures=n_lig,
        replacement_chars=out.count("\ufffd"),
        private_use_chars=sum(1 for ch in out if ord(ch) in _PRIVATE_USE),
        symbols_normalized=n_sym,
    )
    return out, stats


def build_vocabulary(texts: Iterable[str]) -> set[str]:
    """Lower-cased word set of free text (used by tests and simple callers)."""
    vocab: set[str] = set()
    for text in texts:
        vocab.update(_WORD.findall(text.lower()))
    return vocab


def build_vocabulary_from_blocks(blocks: Iterable[Sequence[str]]) -> set[str]:
    """Word set from *visual lines*, excluding words split across a line-break hyphen.

    Fragments such as ``optimi-`` / ``zation`` are never added, so the vocabulary only
    contains words that appear intact in the document.
    """
    vocab: set[str] = set()
    for lines in blocks:
        previous_hyphenated = False
        for raw in lines:
            line = raw.rstrip()
            words = _WORD.findall(line.lower())
            hyphenated = line.endswith(_HYPHENS) or line.endswith("\u00ad")
            if previous_hyphenated and words:
                words = words[1:]
            if hyphenated and words:
                words = words[:-1]
            vocab.update(words)
            previous_hyphenated = hyphenated
    return vocab


def join_lines(lines: Sequence[str], vocab: set[str]) -> tuple[str, CleanStats]:
    """Join visual lines into one paragraph, repairing line-break hyphenation.

    Rules: a trailing soft hyphen always joins. A trailing hyphen followed by a lowercase
    continuation joins *without* the hyphen if the joined word occurs in the document
    vocabulary and the hyphenated form does not; keeps the hyphen whenever the hyphenated
    form occurs in the document (never destroys a real compound), keeps it when the left
    part is already a hyphenated compound, and otherwise joins (assumed soft break).
    This is a heuristic; it can be wrong for rare compounds (documented limitation).
    """
    cleaned: list[tuple[str, bool]] = []
    total = CleanStats()
    for raw in lines:
        stripped = raw.rstrip()
        soft = stripped.endswith("\u00ad")
        text, stats = clean_text(stripped[:-1] if soft else stripped)
        total += stats
        if text:
            cleaned.append((text, soft))
    if not cleaned:
        return "", total
    pieces = [cleaned[0][0]]
    n_join = 0
    for (prev, prev_soft), (nxt, _) in zip(cleaned, cleaned[1:], strict=False):
        if prev_soft:
            pieces.append("\x00" + nxt)
            n_join += 1
            continue
        if prev.endswith(_HYPHENS) and len(prev) > 1 and prev[-2].isalpha() and nxt[:1].islower():
            left = prev[:-1].split()[-1] if prev[:-1].split() else ""
            right_match = _WORD.match(nxt)
            right = right_match.group(0) if right_match else ""
            hyphenated = (left + "-" + right).lower()
            keep_hyphen = ("-" in left) or (hyphenated in vocab)
            if keep_hyphen:
                pieces.append("\x00" + nxt)
            else:
                pieces[-1] = pieces[-1][:-1]
                pieces.append("\x00" + nxt)
                n_join += 1
            continue
        pieces.append(nxt)
    text = ""
    for piece in pieces:
        if piece.startswith("\x00"):
            text += piece[1:]
        else:
            text += (" " if text else "") + piece
    return text, total + CleanStats(dehyphenated=n_join)
