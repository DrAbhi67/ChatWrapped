"""Build a local, review-only shortlist of possible relationship memories."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .conversation_analysis import DEFAULT_GAP_HOURS, split_sessions, usable_messages
    from .emoji_analysis import extract_emojis
    from .language_analyzer import TOKEN_PATTERN
    from .timeline_analysis import canonical_map
except ImportError:
    from conversation_analysis import DEFAULT_GAP_HOURS, split_sessions, usable_messages
    from emoji_analysis import extract_emojis
    from language_analyzer import TOKEN_PATTERN
    from timeline_analysis import canonical_map


DEFAULT_INPUT = Path("output/parsed_export.json")
DEFAULT_ROLES = Path("data/processed/sender_roles.json")
DEFAULT_RULES = Path("data/processed/normalization_rules.json")
DEFAULT_OUTPUT = Path("output/memory_candidates.json")
DEFAULT_APPROVED = Path("data/processed/approved_memories.json")
MESSAGE_LIMIT = 15

PATTERNS = {
    "romantic_or_affectionate": re.compile(
        r"\b(?:i\s+love\s+you|i\s+luv\s+you|love\s+you|luv\s+u|ily|pyaar|pyar|ishq|jaan|jaanu|babe|baby|babu|shona|sweetheart|miss\s+you|kiss)\b",
        re.IGNORECASE,
    ),
    "compliment": re.compile(
        r"\b(?:beautiful|gorgeous|pretty|handsome|cute|adorable|smart|talented|lovely|sundar|pyaari|pyaare)\b",
        re.IGNORECASE,
    ),
    "support": re.compile(
        r"\b(?:proud\s+of\s+you|here\s+for\s+you|i'?m\s+here|im\s+here|don'?t\s+worry|dont\s+worry|you\s+got\s+this|take\s+care|good\s+luck|all\s+the\s+best|tension\s+mat\s+lo|tension\s+mt\s+lo|koi\s+baat\s+nahi|sab\s+theek|you\s+can\s+do\s+it|miss\s+you)\b",
        re.IGNORECASE,
    ),
    "humor": re.compile(r"\b(?:haha+|hehe+|lol|lmao|rofl|funny|joke|mazaak|mazak)\b", re.IGNORECASE),
}
NICKNAMES = {"babe", "baby", "babu", "jaan", "jaanu", "shona", "cutie", "sweetheart", "honey", "boo"}
STOPWORDS = {
    "a", "about", "acha", "accha", "achha", "and", "are", "as", "at", "bas", "be", "been", "but", "by",
    "can", "do", "for", "from", "get", "got", "hai", "have", "he", "her", "here", "h", "him", "his", "ho",
    "how", "i", "if", "in", "is", "it", "kya", "mai", "me", "my", "na", "nahi", "nhi", "nai", "no", "of",
    "on", "or", "or", "she", "so", "that", "the", "this", "to", "too", "tum", "u", "us", "very", "we",
    "what", "when", "where", "who", "why", "will", "with", "ya", "yaar", "yr", "yrr", "you", "your",
}


def row_excerpt(row: dict[str, Any], role_map: dict[str, str]) -> dict[str, Any]:
    raw = row.get("raw", {})
    return {
        "timestamp_local": row.get("timestamp_local"),
        "sender": role_map.get(raw.get("sender_name"), "unmapped"),
        "message_id": row.get("id"),
        "original_text": raw.get("content"),
        "analysis_text": row.get("analysis_text"),
    }


def build_context(rows: list[dict[str, Any]], role_map: dict[str, str]) -> dict[str, dict[str, Any]]:
    by_id = {}
    for index, row in enumerate(rows):
        if row.get("analysis_text_kind") != "message_text":
            continue
        prev_row = rows[index - 1] if index > 0 else None
        next_row = rows[index + 1] if index + 1 < len(rows) else None
        context = []
        for adjacent in (prev_row, next_row):
            if adjacent and adjacent.get("analysis_text_kind") == "message_text":
                context.append(row_excerpt(adjacent, role_map))
        by_id[row.get("id")] = context
    return by_id


def ranked_message_candidates(
    rows: list[dict[str, Any]], role_map: dict[str, str], context_map: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    suggestions = {}
    for category, pattern in PATTERNS.items():
        matches = []
        match_count = 0
        for row in rows:
            if row.get("analysis_text_kind") != "message_text":
                continue
            content = row.get("analysis_text") or ""
            terms = sorted({match.group(0).casefold() for match in pattern.finditer(content)})
            emojis = extract_emojis(content)
            if category == "humor":
                laugh_emojis = [emoji for emoji in emojis if emoji in {"😂", "🤣", "😹", "😆", "😅", "😄", "😃", "😁"}]
                terms.extend(sorted(set(laugh_emojis)))
            if not terms:
                continue
            match_count += 1
            raw = row.get("raw", {})
            matches.append({
                **row_excerpt(row, role_map),
                "category": category,
                "matched_signals": terms,
                "context": context_map.get(row.get("id"), []),
                "approved": False,
            })
        suggestions[category] = {
            "matching_message_count": match_count,
            "shortlist": matches[:MESSAGE_LIMIT],
            "all_items_require_manual_review": True,
        }
    return suggestions


def nickname_candidates(rows: list[dict[str, Any]], role_map: dict[str, str]) -> dict[str, Any]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    first_use = {}
    for row in rows:
        if row.get("analysis_text_kind") != "message_text":
            continue
        raw = row.get("raw", {})
        role = role_map.get(raw.get("sender_name"), "unmapped")
        tokens = [token.casefold() for token in TOKEN_PATTERN.findall(row.get("analysis_text") or "")]
        for token in tokens:
            if token in NICKNAMES:
                counts[token][role] += 1
                first_use.setdefault(token, row_excerpt(row, role_map))
    return {
        nickname: {
            "uses_by_role": dict(counts[nickname]),
            "total_uses": sum(counts[nickname].values()),
            "first_use_candidate": first_use[nickname],
            "approved_as_nickname": False,
        }
        for nickname in sorted(counts)
    }


def inside_joke_vocabulary(
    rows: list[dict[str, Any]], role_map: dict[str, str], rules: dict[str, list[str]], limit: int = 30
) -> list[dict[str, Any]]:
    canonical = canonical_map(rules)
    counts: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    examples: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    total_messages = 0
    for row in rows:
        if row.get("analysis_text_kind") != "message_text":
            continue
        raw = row.get("raw", {})
        role = role_map.get(raw.get("sender_name"), "unmapped")
        if role == "unmapped":
            continue
        tokens = [canonical.get(token.casefold(), token.casefold()) for token in TOKEN_PATTERN.findall(row.get("analysis_text") or "")]
        if not tokens:
            continue
        total_messages += 1
        for size in (2, 3):
            for index in range(len(tokens) - size + 1):
                phrase = tuple(tokens[index:index + size])
                if all(token in STOPWORDS for token in phrase):
                    continue
                counts[phrase][role] += 1
                if len(examples[phrase]) < 5:
                    examples[phrase].append(row_excerpt(row, role_map))

    ranked = []
    role_names = sorted(set(role_map.values()))
    for phrase, by_role in counts.items():
        total = sum(by_role.values())
        if total < 4 or total > 100 or any(by_role[role] < 2 for role in role_names):
            continue
        distinctiveness = math.log((total_messages + 1) / (total + 1))
        balance = min(by_role[role] for role in role_names)
        score = round(balance * distinctiveness, 3)
        ranked.append({
            "phrase": " ".join(phrase),
            "count_by_role": {role: by_role[role] for role in role_names},
            "combined_count": total,
            "candidate_score": score,
            "examples": examples[phrase],
            "approved_as_inside_joke": False,
        })
    ranked.sort(key=lambda item: (-item["candidate_score"], item["phrase"]))
    return ranked[:limit]


def overnight_conversations(parsed: dict[str, Any], role_map: dict[str, str], limit: int = 15) -> list[dict[str, Any]]:
    messages, _, _ = usable_messages(parsed, role_map)
    sessions = split_sessions(messages, DEFAULT_GAP_HOURS)
    candidates = []
    for session in sessions:
        start = session[0]["timestamp_local"]
        end = session[-1]["timestamp_local"]
        duration_hours = (end - start).total_seconds() / 3600
        crosses_date = start.date() != end.date()
        ends_in_morning = 5 <= end.hour < 11
        starts_in_evening = start.hour >= 18
        if not (crosses_date and ends_in_morning and starts_in_evening and duration_hours >= 2):
            continue
        counts = Counter(message["role"] for message in session)
        first_text = next((message for message in session if message.get("text") and message["text"].strip()), None)
        last_text = next((message for message in reversed(session) if message.get("text") and message["text"].strip()), None)
        candidates.append({
            "start_local": start.isoformat(timespec="milliseconds"),
            "end_local": end.isoformat(timespec="milliseconds"),
            "duration_hours": round(duration_hours, 2),
            "message_count": len(session),
            "messages_by_role": dict(counts),
            "session_gap_hours": DEFAULT_GAP_HOURS,
            "start_excerpt": {
                "sender": first_text["role"],
                "message_id": first_text["message_id"],
                "text": first_text["text"],
            } if first_text else None,
            "end_excerpt": {
                "sender": last_text["role"],
                "message_id": last_text["message_id"],
                "text": last_text["text"],
            } if last_text else None,
            "approved": False,
        })
    candidates.sort(key=lambda item: (-item["duration_hours"], -item["message_count"]))
    return candidates[:limit]


def analyze(
    parsed: dict[str, Any], role_map: dict[str, str], rules: dict[str, list[str]], approved: dict[str, Any]
) -> dict[str, Any]:
    rows = parsed.get("messages", [])
    context = build_context(rows, role_map)
    candidates = ranked_message_candidates(rows, role_map, context)
    night_candidates = overnight_conversations(parsed, role_map)

    approved_items = approved.get("approved_memories", [])
    return {
        "review_status": "suggestions_only",
        "romantic_or_affectionate_messages": candidates["romantic_or_affectionate"],
        "compliments": candidates["compliment"],
        "supportive_messages": candidates["support"],
        "funny_messages": candidates["humor"],
        "nickname_candidates": nickname_candidates(rows, role_map),
        "inside_joke_vocabulary_candidates": inside_joke_vocabulary(rows, role_map, rules),
        "overnight_conversation_candidates": night_candidates,
        "approved_memories": approved_items,
        "definitions": {
            "selection": "Keyword and repeated-vocabulary heuristics produce candidates; no memory is selected or approved automatically.",
            "inside_jokes": "Two- or three-word phrases used at least twice by each person and four times overall, ranked by balance and rarity.",
            "overnight_conversation": "A six-hour session that starts at or after 18:00, crosses a date boundary, ends between 05:00 and 10:59, and lasts at least two hours.",
            "source_text": "Each message candidate includes its original export text and a repaired analysis copy; nearby authored messages are shown as context when available.",
            "approved_memory_count": len(approved_items),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Parsed export JSON path")
    parser.add_argument("--roles", default=str(DEFAULT_ROLES), help="Sender-role mapping JSON path")
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="Confirmed spelling rules JSON path")
    parser.add_argument("--approved", default=str(DEFAULT_APPROVED), help="Manually approved memories JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Memory candidates output path")
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    with Path(args.roles).open("r", encoding="utf-8") as handle:
        role_map = json.load(handle)
    with Path(args.rules).open("r", encoding="utf-8") as handle:
        rules = json.load(handle)
    with Path(args.approved).open("r", encoding="utf-8") as handle:
        approved = json.load(handle)
    result = analyze(parsed, role_map, rules, approved)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({
        "output": str(output_path),
        "message_candidates": {
            key: value["matching_message_count"]
            for key, value in result.items()
            if isinstance(value, dict) and "matching_message_count" in value
        },
        "nickname_terms": len(result["nickname_candidates"]),
        "inside_joke_phrase_candidates": len(result["inside_joke_vocabulary_candidates"]),
        "overnight_conversations": len(result["overnight_conversation_candidates"]),
        "approved_memories": len(result["approved_memories"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
