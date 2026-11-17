"""Create the first set of straightforward conversation statistics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("output/parsed_export.json")
DEFAULT_OUTPUT = Path("output/basic_analytics.json")
DEFAULT_ROLES = Path("data/processed/sender_roles.json")


def tied_maxima(counter: Counter[str]) -> list[dict[str, Any]]:
    if not counter:
        return []
    highest = max(counter.values())
    return [
        {"period": key, "message_count": count}
        for key, count in sorted(counter.items())
        if count == highest
    ]


def analyze(data: dict[str, Any], role_map: dict[str, str] | None = None) -> dict[str, Any]:
    role_map = role_map or {}
    rows = data.get("messages")
    if not isinstance(rows, list):
        raise ValueError("Parsed export must contain a messages list")

    sender_counts: Counter[str] = Counter()
    chars_by_sender: Counter[str] = Counter()
    text_count_by_sender: Counter[str] = Counter()
    excluded_template_counts: Counter[str] = Counter()
    by_date: Counter[str] = Counter()
    by_month: Counter[str] = Counter()
    by_weekday: Counter[str] = Counter()
    by_hour: Counter[str] = Counter()
    text_count = 0
    text_char_count = 0
    first_message = None
    first_text_message = None

    for row in rows:
        raw = row.get("raw", {})
        text_kind = row.get("analysis_text_kind", "message_text")
        if text_kind == "reaction_notice":
            excluded_template_counts[text_kind] += 1
            continue
        if text_kind == "unsent_media":
            excluded_template_counts[text_kind] += 1
            continue
        sender = raw.get("sender_name")
        sender_key = sender if isinstance(sender, str) and sender else "(unknown)"
        sender_counts[sender_key] += 1
        local_value = row.get("timestamp_local")
        local_time = datetime.fromisoformat(local_value) if local_value else None

        if first_message is None and local_time is not None:
            first_message = {
                "timestamp_local": local_value,
                "sender": sender_key,
                "role": role_map.get(sender_key),
                "category": row.get("category"),
            }
        if local_time is not None:
            by_date[local_time.date().isoformat()] += 1
            by_month[local_time.strftime("%Y-%m")] += 1
            by_weekday[local_time.strftime("%A")] += 1
            by_hour[f"{local_time.hour:02d}:00"] += 1

        content = row.get("analysis_text", raw.get("content"))
        if text_kind == "attachment_notice":
            excluded_template_counts[text_kind] += 1
            continue
        if isinstance(content, str) and content.strip():
            length = len(content.strip())
            text_count += 1
            text_char_count += length
            chars_by_sender[sender_key] += length
            text_count_by_sender[sender_key] += 1
            if first_text_message is None and local_time is not None:
                first_text_message = {
                    "timestamp_local": local_value,
                    "sender": sender_key,
                    "role": role_map.get(sender_key),
                    "character_count": length,
                }

    total = sum(sender_counts.values())
    active_dates = len(by_date)
    sender_stats = {}
    for sender in sorted(sender_counts):
        count = text_count_by_sender[sender]
        sender_stats[sender] = {
            "message_count": sender_counts[sender],
            "text_message_count": count,
            "average_text_length_characters": round(chars_by_sender[sender] / count, 2) if count else None,
        }

    role_stats = {
        role_map[sender]: {"sender_label": sender, **sender_stats[sender]}
        for sender in sorted(sender_counts)
        if sender in role_map
    }

    return {
        "timezone": data.get("summary", {}).get("timezone", "Asia/Kolkata"),
        "total_message_count": total,
        "raw_export_row_count": len(rows),
        "reaction_notice_rows_excluded": excluded_template_counts["reaction_notice"],
        "first_message": first_message,
        "first_nonempty_text_message": first_text_message,
        "sender_statistics": sender_stats,
        "role_statistics": role_stats,
        "unmapped_sender_names": sorted(set(sender_counts) - set(role_map)),
        "text_statistics": {
            "nonempty_text_message_count": text_count,
            "total_characters_after_trimming_outer_whitespace": text_char_count,
            "average_characters_per_nonempty_text_message": round(text_char_count / text_count, 2) if text_count else None,
            "excluded_export_template_counts": dict(excluded_template_counts),
        },
        "activity": {
            "total_message_count_by_month": dict(sorted(by_month.items())),
            "most_active_months": tied_maxima(by_month),
            "average_messages_per_active_day": round(total / active_dates, 2) if active_dates else None,
            "active_calendar_dates": len(by_date),
            "most_active_calendar_dates": tied_maxima(by_date),
            "messages_by_month": dict(sorted(by_month.items())),
            "most_active_weekdays": tied_maxima(by_weekday),
            "messages_by_hour": dict(sorted(by_hour.items())),
            "peak_messaging_hours": tied_maxima(by_hour),
        },
        "attachment_item_counts": data.get("summary", {}).get("attachment_item_counts", {}),
        "shared_content_message_count": data.get("summary", {}).get("shared_content_message_count", 0),
        "reel_link_candidates": data.get("summary", {}).get("reel_link_candidates", 0),
        "reaction_count": data.get("summary", {}).get("reaction_count", 0),
        "call_event_count": data.get("summary", {}).get("call_event_count", 0),
        "definitions": {
            "text_length": "Unicode character count after trimming whitespace at the two ends of the content field; empty content is excluded.",
            "most_active_calendar_date": "Local calendar date with the most messages; all tied dates are included.",
            "peak_messaging_hours": "Kolkata local clock hour with the most messages; all tied hours are included.",
            "conversation_starts_and_reply_times": "Not calculated in this pass; they need a chosen inactivity-gap rule.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Parsed export JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Analytics JSON output path")
    parser.add_argument("--roles", default=str(DEFAULT_ROLES), help="JSON file mapping exported sender labels to roles")
    args = parser.parse_args()

    input_path = Path(args.input)
    with input_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    role_path = Path(args.roles)
    role_map = {}
    if role_path.is_file():
        with role_path.open("r", encoding="utf-8") as handle:
            loaded_roles = json.load(handle)
        if isinstance(loaded_roles, dict):
            role_map = {str(sender): str(role) for sender, role in loaded_roles.items()}
        else:
            raise ValueError("Sender-role file must be a JSON object mapping sender labels to roles")
    result = analyze(data, role_map)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    # Avoid echoing participant names or message content in terminal output.
    print(json.dumps({
        "output": str(output_path),
        "total_message_count": result["total_message_count"],
        "raw_export_row_count": result["raw_export_row_count"],
        "reaction_notice_rows_excluded": result["reaction_notice_rows_excluded"],
        "nonempty_text_message_count": result["text_statistics"]["nonempty_text_message_count"],
        "peak_messaging_hours": result["activity"]["peak_messaging_hours"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
