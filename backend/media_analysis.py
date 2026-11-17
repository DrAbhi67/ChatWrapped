"""Classify and count media references and shared links in the parsed export."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("output/parsed_export.json")
DEFAULT_ROLES = Path("data/processed/sender_roles.json")
DEFAULT_OUTPUT = Path("output/media_analysis.json")
ATTACHMENT_TYPES = ("photos", "videos", "audio_files", "gifs", "files")


def classify_types(row: dict[str, Any]) -> list[str]:
    types = []
    for link in row.get("shared_links", []):
        kind = link.get("candidate_type")
        if kind and kind not in types:
            types.append(kind)
    for attachment in row.get("attachments", []):
        field = attachment.get("type")
        mapped = {
            "photos": "photo",
            "videos": "video",
            "audio_files": "audio_attachment",
            "gifs": "gif",
            "files": "other_attachment",
        }.get(field)
        if mapped and mapped not in types:
            types.append(mapped)
    if row.get("analysis_text_kind") == "reaction_notice":
        types.append("reaction_event")
    if row.get("analysis_text_kind") == "attachment_notice":
        types.append("attachment_notice")
    if row.get("analysis_text_kind") == "unsent_media":
        types.append("unsent_media_event")
    if row.get("analysis_text_kind") == "message_text":
        types.append("text")
    if not types:
        types.append("other_or_empty")
    return types


def primary_type(types: list[str]) -> str:
    priority = (
        "unsent_media_event", "shared_reel_candidate", "shared_instagram_post_candidate", "story_share_candidate",
        "external_link", "other_instagram_link", "photo", "video", "audio_attachment", "gif",
        "other_attachment", "reaction_event", "attachment_notice", "unsent_media_event", "text", "other_or_empty",
    )
    return next((kind for kind in priority if kind in types), "other_or_empty")


def analyze(parsed: dict[str, Any], role_map: dict[str, str]) -> dict[str, Any]:
    rows = parsed.get("messages")
    if not isinstance(rows, list):
        raise ValueError("Parsed export must contain a messages list")

    role_message_counts: dict[str, Counter[str]] = defaultdict(Counter)
    monthly_counts: dict[str, Counter[str]] = defaultdict(Counter)
    attachment_items: Counter[str] = Counter()
    attachment_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    link_counts: Counter[str] = Counter()
    links_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    reel_counts: Counter[str] = Counter()
    reel_by_month: Counter[str] = Counter()
    text_count = 0
    reaction_notice_count = 0
    valid_dates = []

    for row in rows:
        raw = row.get("raw", {})
        sender_name = row.get("sender", raw.get("sender_name"))
        role = role_map.get(sender_name, "unmapped") if isinstance(sender_name, str) else "unmapped"
        types = classify_types(row)
        row["message_types"] = types
        row["primary_message_type"] = primary_type(types)
        local_value = row.get("timestamp_local")
        month = None
        if local_value:
            local_time = datetime.fromisoformat(local_value)
            month = local_time.strftime("%Y-%m")
            valid_dates.append(local_time.date())

        if row.get("analysis_text_kind") == "unsent_media":
            continue
        if row.get("analysis_text_kind") == "reaction_notice":
            reaction_notice_count += 1
            # Reactions are tracked separately and are not counted as sent messages.
        else:
            role_message_counts[role][row["primary_message_type"]] += 1
            if month:
                monthly_counts[month][row["primary_message_type"]] += 1

        for attachment in row.get("attachments", []):
            kind = attachment.get("type", "files")
            attachment_items[kind] += 1
            attachment_by_role[role][kind] += 1

        for link in row.get("shared_links", []):
            kind = link.get("candidate_type", "other_link")
            link_counts[kind] += 1
            links_by_role[role][kind] += 1
            if kind == "shared_reel_candidate":
                reel_counts[role] += 1
                if month:
                    reel_by_month[month] += 1

        if row.get("analysis_text_kind") == "message_text":
            text_count += 1

    all_roles = sorted(set(role_map.values()))
    message_type_counts = Counter()
    for role_counter in role_message_counts.values():
        message_type_counts.update(role_counter)
    link_total = sum(link_counts.values())
    reel_total = link_counts["shared_reel_candidate"]
    span_weeks = 0.0
    if valid_dates:
        span_days = max(1, (max(valid_dates) - min(valid_dates)).days + 1)
        span_weeks = span_days / 7

    by_role = {}
    for role in all_roles:
        by_role[role] = {
            "messages_by_primary_type": dict(role_message_counts[role]),
            "attachment_item_counts": dict(attachment_by_role[role]),
            "shared_link_counts": dict(links_by_role[role]),
            "reel_link_candidates": reel_counts[role],
        }

    active_media_months = [month for month, counts in monthly_counts.items() if any(
        counts[kind] for kind in ("shared_reel_candidate", "shared_instagram_post_candidate", "story_share_candidate", "photo", "video", "audio_attachment", "gif", "other_attachment")
    )]
    most_active_month = None
    if active_media_months:
        month_totals = {
            month: sum(monthly_counts[month][kind] for kind in (
                "shared_reel_candidate", "shared_instagram_post_candidate", "story_share_candidate",
                "external_link", "other_instagram_link", "photo", "video", "audio_attachment", "gif", "other_attachment"
            ))
            for month in active_media_months
        }
        peak = max(month_totals.values())
        most_active_month = [
            {"month": month, "media_and_link_message_count": count}
            for month, count in sorted(month_totals.items()) if count == peak
        ]

    unavailable = {
        "voice_notes": "Audio attachment references exist, but this export schema does not identify whether they are voice notes or other audio.",
        "stickers": "No sticker attachment field was present in the inspected export.",
        "gif_content": "No GIF attachment field was present; shared GIF links may still appear under shared links.",
        "reel_topics": "Not available because the Reel media itself was not provided or retrieved.",
    }
    return {
        "message_type_counts": dict(message_type_counts),
        "reaction_notice_rows_excluded_from_message_types": reaction_notice_count,
        "attachment_item_counts": dict(attachment_items),
        "shared_link_count": link_total,
        "shared_link_types": dict(link_counts),
        "reel_link_candidates": {
            "total": reel_total,
            "by_role": {role: reel_counts[role] for role in all_roles},
            "per_week_over_export_span": round(reel_total / span_weeks, 2) if span_weeks else None,
        },
        "media_to_authored_text_message_ratio": round(sum(message_type_counts[kind] for kind in (
            "shared_reel_candidate", "shared_instagram_post_candidate", "story_share_candidate", "photo", "video", "audio_attachment", "gif", "other_attachment"
        )) / text_count, 4) if text_count else None,
        "most_active_media_month": most_active_month,
        "messages_by_month_and_type": {month: dict(counts) for month, counts in sorted(monthly_counts.items())},
        "by_role": by_role,
        "unavailable_or_unreliable": unavailable,
        "definitions": {
            "link_types": "Share URLs are classified by visible host/path; text URLs are retained separately. Reel/post/story labels are link-path candidates, not verified media content.",
            "media_to_text_ratio": "Messages with a primary shared-media type divided by authored nonempty text messages; combined or mixed messages use one primary category.",
            "reel_weekly_rate": "Reel-link candidates divided by inclusive export span in weeks.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--roles", default=str(DEFAULT_ROLES))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    with Path(args.input).open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    with Path(args.roles).open("r", encoding="utf-8") as handle:
        role_map = json.load(handle)
    result = analyze(parsed, role_map)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"output": str(output), "link_count": result["shared_link_count"], "reel_candidates": result["reel_link_candidates"]["total"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
