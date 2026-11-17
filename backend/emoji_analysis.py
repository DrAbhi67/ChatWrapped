"""Count Unicode emoji in message text and reactions as separate sources."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from .text_utils import repair_utf8_mojibake
except ImportError:
    from text_utils import repair_utf8_mojibake


DEFAULT_INPUT = Path("output/parsed_export.json")
DEFAULT_ROLES = Path("data/processed/sender_roles.json")
DEFAULT_OUTPUT = Path("output/emoji_profile.json")
VARIATION_SELECTORS = {0xFE0E, 0xFE0F}
SKIN_TONES = range(0x1F3FB, 0x1F400)
REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)
TAG_CHARACTERS = range(0xE0020, 0xE0080)
TEXT_DEFAULT_EMOJI_BASES = {0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299}
HEARTS = {
    "❤", "❤️", "🩷", "🧡", "💛", "💚", "💙", "🩵", "💜", "🤎", "🖤", "🩶", "🤍",
    "💔", "❣", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟",
}
LAUGHING = {"😂", "🤣", "😹", "😆", "😅", "😄", "😃", "😁", "😸", "😺"}
ROMANTIC = HEARTS | {"😘", "😗", "😙", "😚", "😽", "🥰", "😍", "💏", "💑", "👩‍❤️‍👨", "👨‍❤️‍👨", "👩‍❤️‍👩", "💐", "🌹"}


def is_emoji_base(char: str) -> bool:
    point = ord(char)
    return (
        0x1F000 <= point <= 0x1FAFF
        or 0x2600 <= point <= 0x27FF
        or 0x2300 <= point <= 0x23FF
        or point in {0x203C, 0x2049, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299}
    )


def extract_emojis(text: str) -> list[str]:
    """Extract emoji-like Unicode sequences, keeping ZWJ/skin-tone/flag sequences intact."""
    result = []
    index = 0
    while index < len(text):
        point = ord(text[index])

        # Keycap sequences: 1️⃣, #️⃣, and *️⃣.
        if text[index] in "0123456789#*":
            end = index + 1
            if end < len(text) and ord(text[end]) in VARIATION_SELECTORS:
                end += 1
            if end < len(text) and ord(text[end]) == 0x20E3:
                result.append(text[index:end + 1])
                index = end + 1
                continue

        # A flag is a pair of regional indicators; an isolated indicator is not counted.
        if point in REGIONAL_INDICATORS:
            if index + 1 < len(text) and ord(text[index + 1]) in REGIONAL_INDICATORS:
                result.append(text[index:index + 2])
                index += 2
                continue
            index += 1
            continue

        is_text_default_emoji = point in TEXT_DEFAULT_EMOJI_BASES and index + 1 < len(text) and ord(text[index + 1]) == 0xFE0F
        if not (is_emoji_base(text[index]) or is_text_default_emoji) or point in SKIN_TONES:
            index += 1
            continue

        start = index
        index += 1
        while index < len(text):
            next_point = ord(text[index])
            if next_point in VARIATION_SELECTORS or next_point in SKIN_TONES or next_point in TAG_CHARACTERS or next_point == 0x20E3:
                index += 1
                continue
            if next_point == 0x200D and index + 1 < len(text) and is_emoji_base(text[index + 1]):
                index += 2
                continue
            break
        result.append(text[start:index])
    return result


def ranked(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"emoji": emoji, "count": count} for emoji, count in counter.most_common(limit)]


def bucketed(counter: Counter[str], choices: set[str]) -> dict[str, Any]:
    selected = Counter({emoji: count for emoji, count in counter.items() if emoji in choices})
    return {"total_uses": sum(selected.values()), "most_used": ranked(selected, 1)}


def analyze(parsed: dict[str, Any], role_map: dict[str, str]) -> dict[str, Any]:
    rows = parsed.get("messages")
    if not isinstance(rows, list):
        raise ValueError("Parsed export must contain a messages list")

    messages_by_role: Counter[str] = Counter()
    messages_with_emoji: Counter[str] = Counter()
    emoji_counts: dict[str, Counter[str]] = defaultdict(Counter)
    reactions_by_role: Counter[str] = Counter()
    reaction_counts: dict[str, Counter[str]] = defaultdict(Counter)
    message_emojis_by_month: dict[str, Counter[str]] = defaultdict(Counter)
    message_count_by_month: Counter[str] = Counter()
    messages_with_emoji_by_month: Counter[str] = Counter()
    emoji_combinations: Counter[tuple[str, ...]] = Counter()
    reaction_counts_by_month: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        raw = row.get("raw", {})
        sender = raw.get("sender_name")
        role = role_map.get(sender, "unmapped") if isinstance(sender, str) else "unmapped"
        text_kind = row.get("analysis_text_kind", "message_text")
        if text_kind not in {"reaction_notice", "unsent_media"}:
            messages_by_role[role] += 1
        if text_kind == "unsent_media":
            continue
        content = row.get("analysis_text", raw.get("content"))
        month = (row.get("timestamp_local") or "")[:7]
        if text_kind != "reaction_notice" and month:
            message_count_by_month[month] += 1
        if text_kind != "reaction_notice" and text_kind == "message_text" and isinstance(content, str):
            found = extract_emojis(content)
            if found:
                messages_with_emoji[role] += 1
                emoji_counts[role].update(found)
                emoji_counts["combined"].update(found)
                if month:
                    message_emojis_by_month[month].update(found)
                    messages_with_emoji_by_month[month] += 1
                for index in range(len(found) - 1):
                    emoji_combinations[(found[index], found[index + 1])] += 1

        reactions = raw.get("reactions")
        if isinstance(reactions, list):
            for reaction in reactions:
                if not isinstance(reaction, dict):
                    continue
                actor = reaction.get("actor")
                actor_role = role_map.get(actor, "unmapped") if isinstance(actor, str) else "unmapped"
                reactions_by_role[actor_role] += 1
                reactions_by_role["combined"] += 1
                reaction_text = repair_utf8_mojibake(str(reaction.get("reaction", "")))
                for emoji in extract_emojis(reaction_text):
                    reaction_counts[actor_role][emoji] += 1
                    reaction_counts["combined"][emoji] += 1
                    if month:
                        reaction_counts_by_month[month][emoji] += 1

    roles = sorted(role for role in messages_by_role if role != "unmapped")
    per_role = {}
    for role in roles:
        counts = emoji_counts[role]
        message_count = messages_by_role[role]
        used_messages = messages_with_emoji[role]
        per_role[role] = {
            "emoji_uses_in_messages": sum(counts.values()),
            "messages_with_emoji": used_messages,
            "messages_total": message_count,
            "message_emoji_rate_percent": round(100 * used_messages / message_count, 2) if message_count else 0,
            "emoji_uses_per_100_messages": round(100 * sum(counts.values()) / message_count, 2) if message_count else 0,
            "average_emoji_uses_per_message": round(sum(counts.values()) / message_count, 3) if message_count else 0,
            "average_emoji_uses_per_emoji_message": round(sum(counts.values()) / used_messages, 3) if used_messages else 0,
            "distinct_emoji_sequences": len(counts),
            "top_10": ranked(counts),
            "hearts": bucketed(counts, HEARTS),
            "laughing": bucketed(counts, LAUGHING),
            "romantic_curated_set": bucketed(counts, ROMANTIC),
        }

    combined = emoji_counts["combined"]
    comparison_roles = sorted(per_role)
    comparison = {"roles": comparison_roles}
    if len(comparison_roles) == 2:
        first, second = comparison_roles
        first_stats, second_stats = per_role[first], per_role[second]
        comparison.update({
            "more_emoji_uses": first if first_stats["emoji_uses_in_messages"] > second_stats["emoji_uses_in_messages"] else second if second_stats["emoji_uses_in_messages"] > first_stats["emoji_uses_in_messages"] else "tie",
            "higher_emoji_message_rate": first if first_stats["message_emoji_rate_percent"] > second_stats["message_emoji_rate_percent"] else second if second_stats["message_emoji_rate_percent"] > first_stats["message_emoji_rate_percent"] else "tie",
            "more_diverse_emoji_vocabulary": first if first_stats["distinct_emoji_sequences"] > second_stats["distinct_emoji_sequences"] else second if second_stats["distinct_emoji_sequences"] > first_stats["distinct_emoji_sequences"] else "tie",
        })
    reaction_summary = {
        role: {"reaction_count": reactions_by_role[role], "top_10": ranked(reaction_counts[role])}
        for role in sorted(set(reactions_by_role) - {"combined"})
    }
    return {
        "message_emoji_statistics": {
            "combined_top_10": ranked(combined),
            "combined_uses": sum(combined.values()),
            "combined_hearts": bucketed(combined, HEARTS),
            "combined_laughing": bucketed(combined, LAUGHING),
            "combined_romantic_curated_set": bucketed(combined, ROMANTIC),
            "comparison": comparison,
            "top_adjacent_emoji_combinations": [
                {"combination": list(combo), "count": count}
                for combo, count in emoji_combinations.most_common(20)
            ],
            "by_month": {
                month: {
                    "message_count": message_count_by_month[month],
                    "messages_with_emoji": messages_with_emoji_by_month[month],
                    "emoji_uses": sum(message_emojis_by_month[month].values()),
                    "top_10": ranked(message_emojis_by_month[month]),
                }
                for month in sorted(message_count_by_month)
            },
            "roles": per_role,
        },
        "reaction_emoji_statistics": {
            "combined_top_10": ranked(reaction_counts["combined"]),
            "combined_reaction_count": reactions_by_role["combined"],
            "unmapped_actor_reaction_count": reactions_by_role["unmapped"],
            "by_month": {month: ranked(counter, 10) for month, counter in sorted(reaction_counts_by_month.items())},
            "roles": reaction_summary,
        },
        "definitions": {
            "message_emojis": "Emoji sequences found in content text only; never mixed with reactions.",
            "emoji_rate": "Messages containing at least one emoji divided by all messages from that sender.",
            "diversity": "Number of distinct Unicode emoji sequences, preserving flags, skin tones, and joined sequences separately.",
            "romantic_curated_set": "Hearts, kiss/love faces, couple symbols, bouquet, and rose; review this set before using as a romantic claim.",
            "extractor": "Standard-library Unicode sequence scanner covering common emoji blocks, flags, keycaps, skin tones, and zero-width-joiner sequences.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Parsed export JSON path")
    parser.add_argument("--roles", default=str(DEFAULT_ROLES), help="Sender-role mapping JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Emoji output path")
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    with Path(args.roles).open("r", encoding="utf-8") as handle:
        role_map = json.load(handle)
    result = analyze(parsed, role_map)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({
        "output": str(output_path),
        "message_emoji_uses": result["message_emoji_statistics"]["combined_uses"],
        "reaction_count": result["reaction_emoji_statistics"]["combined_reaction_count"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
