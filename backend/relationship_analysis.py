"""Count configured relationship-related language without inferring feelings."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("output/parsed_export.json")
DEFAULT_ROLES = Path("data/processed/sender_roles.json")
DEFAULT_LEXICON = Path("data/processed/language_lexicon.json")
DEFAULT_OUTPUT = Path("output/relationship_statistics.json")


def pattern_for(phrase: str) -> re.Pattern[str]:
    words = re.escape(phrase.strip()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){words}(?!\w)", re.IGNORECASE)


def count_phrase_groups(
    rows: list[dict[str, Any]], role_map: dict[str, str], groups: dict[str, list[str]]
) -> dict[str, Any]:
    counts_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    messages_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    monthly: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    total_messages: Counter[str] = Counter()
    patterns = {group: {phrase: pattern_for(phrase) for phrase in phrases} for group, phrases in groups.items()}

    for row in rows:
        if row.get("analysis_text_kind") != "message_text":
            continue
        raw = row.get("raw", {})
        sender = row.get("sender") or raw.get("sender_name")
        role = role_map.get(sender, "unmapped") if isinstance(sender, str) else "unmapped"
        text = row.get("analysis_text") or ""
        month = (row.get("timestamp_local") or "")[:7]
        total_messages[role] += 1
        for group, phrase_patterns in patterns.items():
            matched_in_message = False
            for phrase, pattern in phrase_patterns.items():
                matches = list(pattern.finditer(text))
                if matches:
                    counts_by_role[group][role] += len(matches)
                    matched_in_message = True
                    if month:
                        monthly[month][group][role] += len(matches)
            if matched_in_message:
                messages_by_role[group][role] += 1

    roles = sorted(set(role_map.values()))
    return {
        "categories": {
            group: {
                "configured_phrases": phrases,
                "occurrences_by_role": {role: counts_by_role[group][role] for role in roles},
                "messages_containing_phrase_by_role": {role: messages_by_role[group][role] for role in roles},
                "occurrences_total": sum(counts_by_role[group].values()),
            }
            for group, phrases in groups.items()
        },
        "monthly_occurrences": {
            month: {
                group: {role: counts[role] for role in roles}
                for group, counts in groups_by_month.items()
            }
            for month, groups_by_month in sorted(monthly.items())
        },
        "message_counts_by_role": {role: total_messages[role] for role in roles},
        "unavailable": {
            "voice_notes": "Audio attachment references do not identify voice notes reliably.",
            "feelings_or_relationship_quality": "Phrase counts are language counts, not evidence about feelings or relationship quality.",
        },
        "definitions": {
            "phrase_counts": "Case-insensitive literal phrase matches in authored text only. Phrases may overlap and can appear jokingly or in quoted content.",
            "speaker_attribution": "Counts the person who sent the message containing the phrase; it does not identify who the phrase refers to.",
        },
    }


def analyze(parsed: dict[str, Any], role_map: dict[str, str], lexicon: dict[str, Any]) -> dict[str, Any]:
    rows = parsed.get("messages")
    if not isinstance(rows, list):
        raise ValueError("Parsed export must contain a messages list")
    groups = {
        "good_morning": lexicon.get("greetings", {}).get("good_morning", []),
        "good_night": lexicon.get("greetings", {}).get("good_night", []),
        "i_love_you": lexicon.get("i_love_you_phrases", []),
        "compliments": lexicon.get("compliment_phrases", []),
        "appreciation": lexicon.get("appreciation_phrases", []),
        "apologies": lexicon.get("apology_phrases", []),
        "pet_names": lexicon.get("pet_names", []),
        "support": lexicon.get("support_phrases", []),
        "reassurance": lexicon.get("reassurance_phrases", []),
        "affectionate_words": lexicon.get("affectionate_words", []),
    }
    return count_phrase_groups(rows, role_map, groups)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--roles", default=str(DEFAULT_ROLES))
    parser.add_argument("--lexicon", default=str(DEFAULT_LEXICON))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    with Path(args.input).open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    with Path(args.roles).open("r", encoding="utf-8") as handle:
        roles = json.load(handle)
    with Path(args.lexicon).open("r", encoding="utf-8") as handle:
        lexicon = json.load(handle)
    result = analyze(parsed, roles, lexicon)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"output": str(output), "phrase_groups": len(result["categories"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
