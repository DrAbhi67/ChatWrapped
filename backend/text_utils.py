"""Small local text-repair helpers for analysis-only copies."""

import re


_WORD_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def _utf8_sequence_length(first_byte: int) -> int:
    if 0xC2 <= first_byte <= 0xDF:
        return 2
    if 0xE0 <= first_byte <= 0xEF:
        return 3
    if 0xF0 <= first_byte <= 0xF4:
        return 4
    return 0


def _valid_utf8_sequence(values: list[int]) -> bool:
    if len(values) == 2:
        return 0x80 <= values[1] <= 0xBF
    if len(values) == 3:
        first, second, third = values
        if not 0x80 <= third <= 0xBF:
            return False
        if first == 0xE0:
            return 0xA0 <= second <= 0xBF
        if first == 0xED:
            return 0x80 <= second <= 0x9F
        return 0x80 <= second <= 0xBF
    if len(values) == 4:
        first, second, third, fourth = values
        if not (0x80 <= third <= 0xBF and 0x80 <= fourth <= 0xBF):
            return False
        if first == 0xF0:
            return 0x90 <= second <= 0xBF
        if first == 0xF4:
            return 0x80 <= second <= 0x8F
        return first in range(0xF1, 0xF4) and 0x80 <= second <= 0xBF
    return False


def repair_utf8_mojibake(text: str) -> str:
    """Decode UTF-8 byte sequences mis-read as Latin-1, preserving other text.

    Instagram's export in this workspace stores some emoji sequences as
    Latin-1-looking code points. This creates a repaired analysis string only;
    the source message text is never changed.
    """
    output = []
    index = 0
    while index < len(text):
        first = ord(text[index])
        length = _utf8_sequence_length(first) if first <= 0xFF else 0
        if length and index + length <= len(text):
            candidate = [ord(char) for char in text[index:index + length]]
            if all(value <= 0xFF for value in candidate) and _valid_utf8_sequence(candidate):
                output.append(bytes(candidate).decode("utf-8"))
                index += length
                continue
        output.append(text[index])
        index += 1
    return "".join(output)


def classify_export_text(text: str | None) -> str | None:
    """Flag known Instagram boilerplate so it is not mistaken for authored text."""
    if not isinstance(text, str) or not text.strip():
        return None
    tokens = [token.casefold() for token in _WORD_PATTERN.findall(text)]
    if len(tokens) >= 4 and tokens[-3:] == ["sent", "an", "attachment"]:
        return "attachment_notice"
    if len(tokens) >= 4 and tokens[0] == "reacted" and tokens[-3:] == ["to", "your", "message"]:
        return "reaction_notice"
    return "message_text"


def canonical_forms(rules: dict[str, list[str]] | None = None) -> dict[str, str]:
    result = {}
    for canonical, forms in (rules or {}).items():
        for form in [canonical, *forms]:
            key = form.casefold()
            value = canonical.casefold()
            if key in result and result[key] != value:
                raise ValueError(f"Normalization form {key!r} appears in multiple groups")
            result[key] = value
    return result


def tokenize(text: str) -> list[str]:
    return [token.casefold() for token in _WORD_PATTERN.findall(text)]


def normalize_text(text: str, rules: dict[str, list[str]] | None = None) -> tuple[str, list[str]]:
    """Case-fold words and apply only configured aliases; preserve punctuation/spacing."""
    forms = canonical_forms(rules)
    tokens = tokenize(text)
    normalized_text = _WORD_PATTERN.sub(lambda match: forms.get(match.group(0).casefold(), match.group(0).casefold()), text)
    normalized_words = [forms.get(token, token) for token in tokens]
    return normalized_text, normalized_words
