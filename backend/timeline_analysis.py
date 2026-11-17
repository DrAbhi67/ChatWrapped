"""Create reviewable relationship-timeline candidates and era comparisons."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

try:
    from .conversation_analysis import DEFAULT_GAP_HOURS, reply_and_double_text_stats, split_sessions, usable_messages
    from .emoji_analysis import extract_emojis
    from .language_analyzer import TOKEN_PATTERN
except ImportError:
    from conversation_analysis import DEFAULT_GAP_HOURS, reply_and_double_text_stats, split_sessions, usable_messages
    from emoji_analysis import extract_emojis
    from language_analyzer import TOKEN_PATTERN


DEFAULT_INPUT = Path("output/parsed_export.json")
DEFAULT_ROLES = Path("data/processed/sender_roles.json")
DEFAULT_RULES = Path("data/processed/normalization_rules.json")
DEFAULT_MILESTONES = Path("data/processed/milestones.json")
DEFAULT_OUTPUT = Path("output/timeline_candidates.json")
SESSION_GAP_HOURS = DEFAULT_GAP_HOURS
CANDIDATE_LIMIT = 20
LATE_NIGHT_START_HOUR = 22
LATE_NIGHT_END_HOUR = 4

AFFECTIONATE_TERMS = {
    "babe", "baby", "babu", "jaan", "jaanu", "shona", "cutie", "sweetheart", "honey",
    "love", "luv", "pyaar", "pyar", "ishq", "beautiful", "pretty", "cute", "miss",
}
LOVE_PHRASE = re.compile(r"\b(?:i\s+love\s+you|i\s+luv\s+you|love\s+you|luv\s+u|ily)\b", re.IGNORECASE)
FLIRT_TERMS = re.compile(
    r"\b(?:crush|flirt|cute|pretty|beautiful|handsome|kiss|date|pasand|like\s+you|miss\s+you)\b",
    re.IGNORECASE,
)
NICKNAME_TERMS = re.compile(
    r"\b(?:babe|baby|babu|jaan|jaanu|shona|cutie|sweetheart|honey|boo)\b",
    re.IGNORECASE,
)


def canonical_map(rules: dict[str, list[str]]) -> dict[str, str]:
    result = {}
    for canonical, forms in rules.items():
        for form in [canonical, *forms]:
            result[form.casefold()] = canonical.casefold()
    return result


def event_reference(row: dict[str, Any], role_map: dict[str, str], label: str) -> dict[str, Any]:
    raw = row.get("raw", {})
    return {
        "candidate_type": label,
        "timestamp_local": row.get("timestamp_local"),
        "date_local": (row.get("timestamp_local") or "")[:10] or None,
        "sender": role_map.get(raw.get("sender_name"), "unmapped"),
        "message_id": row.get("id"),
        "category": row.get("category"),
        "confirmed": False,
    }


def text_candidate(row: dict[str, Any], role_map: dict[str, str], tags: list[str]) -> dict[str, Any]:
    raw = row.get("raw", {})
    return {
        "timestamp_local": row.get("timestamp_local"),
        "sender": role_map.get(raw.get("sender_name"), "unmapped"),
        "message_id": row.get("id"),
        "matched_tags": tags,
        "original_text": raw.get("content"),
        "analysis_text": row.get("analysis_text"),
        "approved": False,
    }


def first_attachment(rows: list[dict[str, Any]], field: str, role_map: dict[str, str]) -> dict[str, Any] | None:
    for row in rows:
        value = row.get("raw", {}).get(field)
        if value:
            result = event_reference(row, role_map, f"first_{field}")
            result["attachment_count"] = len(value) if isinstance(value, list) else 1
            return result
    return None


def milestone_candidates(
    parsed: dict[str, Any], role_map: dict[str, str], manual: dict[str, Any]
) -> dict[str, Any]:
    rows = [
        row for row in parsed.get("messages", [])
        if row.get("analysis_text_kind") not in {"reaction_notice", "unsent_media"} and row.get("timestamp_local")
    ]
    data_events = {}
    if rows:
        data_events["first_conversation_message"] = event_reference(rows[0], role_map, "first_conversation_message")
    for row in rows:
        if isinstance(row.get("raw", {}).get("share"), dict):
            data_events["first_shared_content"] = event_reference(row, role_map, "first_shared_content")
            break
    for row in rows:
        if row.get("reel_link_candidate") or any(
            link.get("candidate_type") == "shared_reel_candidate"
            for link in row.get("shared_links", [])
        ):
            data_events["first_reel_link_candidate"] = event_reference(row, role_map, "first_reel_link_candidate")
            break
    for field in ("photos", "videos", "audio_files"):
        candidate = first_attachment(rows, field, role_map)
        if candidate:
            data_events[f"first_{field}"] = candidate

    conversation_rows, _, _ = usable_messages(parsed, role_map)
    sessions = split_sessions(conversation_rows, SESSION_GAP_HOURS)
    for session in sessions:
        night_messages = [
            message for message in session
            if message["timestamp_local"].hour >= LATE_NIGHT_START_HOUR
            or message["timestamp_local"].hour < LATE_NIGHT_END_HOUR
        ]
        if night_messages:
            first_night = night_messages[0]
            data_events["first_late_night_conversation_candidate"] = {
                "start_local": session[0]["timestamp_local"].isoformat(timespec="milliseconds"),
                "end_local": session[-1]["timestamp_local"].isoformat(timespec="milliseconds"),
                "first_late_night_message_local": first_night["timestamp_local"].isoformat(timespec="milliseconds"),
                "message_count": len(session),
                "session_gap_hours": SESSION_GAP_HOURS,
                "sender": first_night["role"],
                "confirmed": False,
            }
            break

    active_days = sorted({message["timestamp_local"].date() for message in conversation_rows})
    regularity = None
    if len(active_days) >= 7:
        for start_index in range(len(active_days) - 6):
            seven_days = active_days[start_index:start_index + 7]
            if all((seven_days[i] - seven_days[i - 1]).days == 1 for i in range(1, 7)):
                regularity = {
                    "candidate_date": seven_days[0].isoformat(),
                    "active_days_in_run": 7,
                    "definition": "First day of the earliest run of seven consecutive calendar dates with at least one conversation message.",
                    "confirmed": False,
                }
                break

    suggestion_specs = {
        "possible_love_confession_or_i_love_you": LOVE_PHRASE,
        "possible_flirting": FLIRT_TERMS,
        "possible_nickname_or_affectionate_word": NICKNAME_TERMS,
    }
    suggestions = {}
    for label, pattern in suggestion_specs.items():
        matches = []
        total = 0
        for row in rows:
            if row.get("analysis_text_kind") != "message_text":
                continue
            content = row.get("analysis_text") or ""
            tags = sorted({match.group(0).casefold() for match in pattern.finditer(content)})
            if tags:
                total += 1
                if len(matches) < CANDIDATE_LIMIT:
                    matches.append(text_candidate(row, role_map, tags))
        suggestions[label] = {
            "total_matching_messages": total,
            "candidates": matches,
            "all_candidates_approved": False,
        }

    manual_milestones = manual.get("milestones", [])
    confirmed_manual = [item for item in manual_milestones if item.get("confirmed") and item.get("date")]
    pending_manual = [item for item in manual_milestones if not (item.get("confirmed") and item.get("date"))]
    return {
        "data_derived_event_candidates": data_events,
        "regular_talking_candidate": regularity,
        "text_search_suggestions": suggestions,
        "manual_milestones": {
            "relationship_start_date": manual.get("relationship_start_date"),
            "relationship_start_date_confirmed": manual.get("relationship_start_date_confirmed", False),
            "confirmed": confirmed_manual,
            "pending": pending_manual,
        },
        "definitions": {
            "late_night": "A six-hour conversation session containing at least one message from 22:00 through 03:59 Asia/Kolkata.",
            "regular_talking": "Heuristic candidate: first day of seven consecutive dates with at least one non-reaction conversation message.",
            "text_candidates": "Keyword matches only; they are suggestions, not confirmed relationship milestones or memories.",
        },
    }


def compare_eras(
    parsed: dict[str, Any], role_map: dict[str, str], rules: dict[str, list[str]], start_date: date | None
) -> dict[str, Any]:
    if start_date is None:
        return {"status": "awaiting_confirmed_relationship_start_date"}

    canonical_forms = canonical_map(rules)
    conversation_rows, _, unknown_senders = usable_messages(parsed, role_map)
    roles = sorted(set(role_map.values()))
    all_sessions = split_sessions(conversation_rows, SESSION_GAP_HOURS)
    output = {}
    eras = {
        "friendship": lambda day: day < start_date,
        "relationship": lambda day: day >= start_date,
    }

    for era, predicate in eras.items():
        messages = [m for m in conversation_rows if predicate(m["timestamp_local"].date())]
        counts = Counter(message["role"] for message in messages)
        text_lengths: Counter[str] = Counter()
        text_counts: Counter[str] = Counter()
        emoji_counts: dict[str, Counter[str]] = defaultdict(Counter)
        emoji_messages: Counter[str] = Counter()
        affectionate_counts: dict[str, Counter[str]] = defaultdict(Counter)
        affectionate_messages: Counter[str] = Counter()
        share_counts: Counter[str] = Counter()
        reel_counts: Counter[str] = Counter()
        era_role_stats = {}

        row_by_time_role = defaultdict(list)
        for row in parsed.get("messages", []):
            if row.get("analysis_text_kind") in {"reaction_notice", "unsent_media"} or not row.get("timestamp_local"):
                continue
            local_time = datetime.fromisoformat(row["timestamp_local"])
            if not predicate(local_time.date()):
                continue
            raw = row.get("raw", {})
            role = role_map.get(raw.get("sender_name"), "unmapped")
            content = row.get("analysis_text") or ""
            if row.get("analysis_text_kind") == "message_text" and content.strip():
                text_counts[role] += 1
                text_lengths[role] += len(content.strip())
                tokens = [canonical_forms.get(token.casefold(), token.casefold()) for token in TOKEN_PATTERN.findall(content)]
                terms = [token for token in tokens if token in AFFECTIONATE_TERMS]
                if terms:
                    affectionate_messages[role] += 1
                    affectionate_counts[role].update(terms)
                found_emoji = extract_emojis(content)
                if found_emoji:
                    emoji_messages[role] += 1
                    emoji_counts[role].update(found_emoji)
            if isinstance(raw.get("share"), dict):
                share_counts[role] += 1
            if row.get("reel_link_candidate"):
                reel_counts[role] += 1
        for role in roles:
            emoji_total = sum(emoji_counts[role].values())
            msg_count = counts[role]
            output_role = {
                "conversation_message_count": msg_count,
                "nonempty_authored_text_count": text_counts[role],
                "average_authored_text_length_characters": round(text_lengths[role] / text_counts[role], 2) if text_counts[role] else None,
                "message_emoji_uses": emoji_total,
                "messages_with_emoji": emoji_messages[role],
                "emoji_message_rate_percent": round(100 * emoji_messages[role] / msg_count, 2) if msg_count else 0,
                "distinct_emoji_sequences": len(emoji_counts[role]),
                "affectionate_vocabulary_message_count": affectionate_messages[role],
                "affectionate_vocabulary_token_counts": dict(affectionate_counts[role].most_common()),
                "shared_content_count": share_counts[role],
                "reel_link_candidate_count": reel_counts[role],
            }
            era_role_stats[role] = output_role

        sessions = split_sessions(messages, SESSION_GAP_HOURS)
        starts_in_era = [
            session for session in all_sessions
            if predicate(session[0]["timestamp_local"].date())
        ]
        summary = {
            "conversation_message_count": len(messages),
            "messages_by_role": {role: counts[role] for role in roles},
            "messages_by_month": dict(sorted(Counter(m["timestamp_local"].strftime("%Y-%m") for m in messages).items())),
            "by_role": era_role_stats,
            "conversation_starts_by_role": summarize_starts(starts_in_era, roles),
            "reply_times": reply_and_double_text_stats(sessions, roles)[0],
            "date_range": {
                "first_local": messages[0]["timestamp_local"].isoformat(timespec="milliseconds") if messages else None,
                "last_local": messages[-1]["timestamp_local"].isoformat(timespec="milliseconds") if messages else None,
            },
        }
        output[era] = summary

    return {
        "status": "calculated",
        "relationship_start_date": start_date.isoformat(),
        "friendship_era_definition": "From first exported conversation message up to, but not including, the confirmed relationship start date.",
        "relationship_era_definition": "From the confirmed relationship start date through the last exported conversation message.",
        "era_metric_boundary_note": "Conversation starts are assigned by the session's actual first message. Reply turns crossing the era boundary are omitted from both era reply-time samples.",
        "comparison": {era: output[era] for era in eras},
        "unknown_sender_rows": unknown_senders,
        "romantic_vocabulary_note": "Counts use a small transparent keyword list and show exact tokens; words may be used jokingly or non-romantically and need interpretation.",
    }


def summarize_starts(sessions: list[list[dict[str, Any]]], roles: list[str]) -> dict[str, int]:
    counts = Counter(session[0]["role"] for session in sessions)
    return {role: counts[role] for role in roles}


def analyze(
    parsed: dict[str, Any],
    role_map: dict[str, str],
    rules: dict[str, list[str]],
    manual: dict[str, Any],
) -> dict[str, Any]:
    relationship_value = manual.get("relationship_start_date")
    try:
        start_date = date.fromisoformat(relationship_value) if relationship_value else None
    except (TypeError, ValueError):
        start_date = None
    if not manual.get("relationship_start_date_confirmed", False):
        start_date = None

    return {
        "timeline": milestone_candidates(parsed, role_map, manual),
        "before_after_comparison": compare_eras(parsed, role_map, rules, start_date),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Parsed export JSON path")
    parser.add_argument("--roles", default=str(DEFAULT_ROLES), help="Sender-role mapping JSON path")
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="Confirmed normalization rules JSON path")
    parser.add_argument("--milestones", default=str(DEFAULT_MILESTONES), help="Manual milestone settings JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Timeline output path")
    args = parser.parse_args()

    paths = [Path(args.input), Path(args.roles), Path(args.rules), Path(args.milestones)]
    with paths[0].open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    with paths[1].open("r", encoding="utf-8") as handle:
        role_map = json.load(handle)
    with paths[2].open("r", encoding="utf-8") as handle:
        rules = json.load(handle)
    with paths[3].open("r", encoding="utf-8") as handle:
        manual = json.load(handle)
    result = analyze(parsed, role_map, rules, manual)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    comparison = result["before_after_comparison"]
    print(json.dumps({
        "output": str(output_path),
        "relationship_start_date": comparison.get("relationship_start_date"),
        "comparison_status": comparison["status"],
        "text_candidate_groups": len(result["timeline"]["text_search_suggestions"]),
        "data_derived_event_types": len(result["timeline"]["data_derived_event_candidates"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
