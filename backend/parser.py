"""Parse Instagram's split message JSON files into one local, timestamped export.

This first prototype preserves each original message object and adds only
derived metadata. It uses the Python standard library so no packages are
needed for the parsing step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from .emoji_analysis import extract_emojis
    from .media_analysis import classify_types, primary_type
    from .text_utils import classify_export_text, normalize_text, repair_utf8_mojibake
except ImportError:
    from emoji_analysis import extract_emojis
    from media_analysis import classify_types, primary_type
    from text_utils import classify_export_text, normalize_text, repair_utf8_mojibake


DEFAULT_INPUT = Path("data/raw/message_*.json")
DEFAULT_OUTPUT = Path("output/parsed_export.json")
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_CONFIG = Path("data/processed/analysis_config.json")
DEFAULT_RULES = Path("data/processed/normalization_rules.json")
MEDIA_FIELDS = ("photos", "videos", "audio_files", "files", "gifs")
REEL_PATH = re.compile(r"(?:^|/)reels?/", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def read_export(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("messages"), list):
        raise ValueError(f"{path} is not an Instagram message file with a messages list")
    return value


def canonical_signature(message: dict[str, Any]) -> str:
    """Hash the complete message object, so separate same-time media isn't lost."""
    encoded = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def resolve_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "Asia/Kolkata":
            # India uses UTC+05:30 without daylight-saving changes.
            return timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
        raise ValueError(
            f"Timezone database entry {timezone_name!r} is unavailable. Install tzdata in the virtual environment."
        )


def local_timestamp(timestamp_ms: int | float, timezone_name: str = DEFAULT_TIMEZONE) -> str:
    utc_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return utc_time.astimezone(resolve_timezone(timezone_name)).isoformat(timespec="milliseconds")


def message_category(message: dict[str, Any]) -> str:
    has_text = isinstance(message.get("content"), str) and bool(message["content"].strip())
    has_share = isinstance(message.get("share"), dict)
    has_media = any(message.get(field) for field in MEDIA_FIELDS)
    if has_share:
        return "shared_content"
    if has_media:
        return "media_with_text" if has_text else "media"
    if has_text:
        return "text"
    return "event_or_empty"


def has_reel_link(message: dict[str, Any]) -> bool:
    """Only flag shares whose link path visibly identifies an Instagram Reel."""
    share = message.get("share")
    if not isinstance(share, dict):
        return False
    link = share.get("link")
    return isinstance(link, str) and bool(REEL_PATH.search(link))


def extract_shared_links(message: dict[str, Any], analysis_text: str | None) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    candidates = []
    share = message.get("share")
    if isinstance(share, dict) and isinstance(share.get("link"), str):
        candidates.append((share["link"], "share"))
    if isinstance(analysis_text, str):
        candidates.extend((url.rstrip(".,!?)]}"), "text") for url in URL_PATTERN.findall(analysis_text))
    seen = set()
    for url, source in candidates:
        if url in seen:
            continue
        seen.add(url)
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        path = parsed.path.casefold()
        if host != "instagram.com" and not host.endswith(".instagram.com"):
            kind = "external_link"
        elif REEL_PATH.search(path):
            kind = "shared_reel_candidate"
        elif re.search(r"/p/", path):
            kind = "shared_instagram_post_candidate"
        elif "/stories/" in path:
            kind = "story_share_candidate"
        else:
            kind = "other_instagram_link"
        found.append({"url": url, "source": source, "candidate_type": kind})
    return found


def collect_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for field in MEDIA_FIELDS:
        value = message.get(field)
        if not value:
            continue
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if isinstance(entry, dict):
                items.append({"type": field, **entry})
            else:
                items.append({"type": field, "value": entry})
    return items


def timestamp_sort_key(message: dict[str, Any]) -> tuple[int, float, str]:
    try:
        return (0, float(message["raw"]["timestamp_ms"]), message["id"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return (1, 0.0, message["id"])


def parse_files(
    paths: list[Path],
    timezone_name: str = DEFAULT_TIMEZONE,
    normalization_rules: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    signatures: set[str] = set()
    sender_names: set[str] = set()
    participants: list[Any] = []
    thread_titles: set[str] = set()
    duplicates_removed = 0
    files_read = []

    for path in sorted(paths, key=lambda item: item.name.casefold()):
        export = read_export(path)
        if isinstance(export.get("participants"), list):
            participants = export["participants"] or participants
        if isinstance(export.get("title"), str):
            thread_titles.add(export["title"])
        added_from_file = 0
        for raw_message in export["messages"]:
            if not isinstance(raw_message, dict):
                continue
            signature = canonical_signature(raw_message)
            if signature in signatures:
                duplicates_removed += 1
                continue
            signatures.add(signature)

            sender = raw_message.get("sender_name")
            if isinstance(sender, str) and sender:
                sender_names.add(sender)

            timestamp = raw_message.get("timestamp_ms")
            try:
                local_time = local_timestamp(timestamp, timezone_name)
            except (TypeError, ValueError, OSError, OverflowError):
                local_time = None

            analysis_text = repair_utf8_mojibake(raw_message["content"]) if isinstance(raw_message.get("content"), str) else None
            text_kind = classify_export_text(analysis_text)
            if raw_message.get("is_unsent_image_by_messenger_kid_parent"):
                text_kind = "unsent_media"
            normalized_text, words = normalize_text(analysis_text, normalization_rules) if text_kind == "message_text" and analysis_text else (None, [])
            emoji_sequences = extract_emojis(analysis_text) if text_kind == "message_text" and analysis_text else []
            category = {
                "reaction_notice": "reaction_event",
                "attachment_notice": "attachment_message",
                "unsent_media": "unsent_media_event",
            }.get(text_kind, message_category(raw_message))
            parsed_message = {
                "id": signature,
                "sender": sender,
                "timestamp_ms": timestamp,
                "timestamp_local": local_time,
                "category": category,
                "message_type": category,
                "reel_link_candidate": has_reel_link(raw_message),
                "text": raw_message.get("content"),
                "analysis_text": analysis_text,
                "analysis_text_kind": text_kind,
                "normalized_text": normalized_text,
                "words": words,
                "emojis": emoji_sequences,
                "attachments": collect_attachments(raw_message),
                "shared_links": extract_shared_links(raw_message, analysis_text),
                "reactions": raw_message.get("reactions", []),
                "raw": raw_message,
                "source_file": path.name,
            }
            message_types = classify_types(parsed_message)
            parsed_message["message_types"] = message_types
            parsed_message["primary_message_type"] = primary_type(message_types)
            parsed_message["message_type"] = parsed_message["primary_message_type"]
            messages.append(parsed_message)
            added_from_file += 1
        files_read.append({"file": path.name, "messages": len(export["messages"]), "unique_added": added_from_file})

    messages.sort(key=timestamp_sort_key)
    summary = make_summary(messages, sender_names, participants, files_read, duplicates_removed, timezone_name)
    summary["thread_titles"] = sorted(thread_titles)
    return messages, summary


def make_summary(
    messages: list[dict[str, Any]],
    sender_names: set[str],
    participants: list[Any],
    files_read: list[dict[str, Any]],
    duplicates_removed: int,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    senders = Counter(message["raw"].get("sender_name", "(unknown)") for message in messages)
    conversation_senders = Counter(
        message["raw"].get("sender_name", "(unknown)")
        for message in messages
        if message.get("analysis_text_kind") not in {"reaction_notice", "unsent_media"}
    )
    categories = Counter(message["category"] for message in messages)
    media_items = Counter()
    media_messages = Counter()
    reaction_count = 0
    share_count = 0
    call_event_count = 0
    nonempty_text_count = 0
    analysis_text_kinds = Counter()
    for message in messages:
        raw = message["raw"]
        sender = raw.get("sender_name", "(unknown)")
        text_kind = message.get("analysis_text_kind") or "no_text"
        analysis_text_kinds[text_kind] += 1
        if text_kind == "message_text":
            nonempty_text_count += 1
        if isinstance(raw.get("share"), dict):
            share_count += 1
        if raw.get("call_duration") is not None:
            call_event_count += 1
        reactions = raw.get("reactions")
        if isinstance(reactions, list):
            reaction_count += len(reactions)
        for field in MEDIA_FIELDS:
            value = raw.get(field)
            if value:
                count = len(value) if isinstance(value, list) else 1
                media_items[field] += count
                media_messages[field] += 1

    valid = [m for m in messages if m["timestamp_local"] and m.get("analysis_text_kind") not in {"reaction_notice", "unsent_media"}]
    first = valid[0]["timestamp_local"] if valid else None
    last = valid[-1]["timestamp_local"] if valid else None
    return {
        "timezone": timezone_name,
        "files": files_read,
        "input_export_row_count": sum(row["messages"] for row in files_read),
        "unique_export_row_count": len(messages),
        "conversation_message_count": sum(conversation_senders.values()),
        "reaction_notice_count": analysis_text_kinds["reaction_notice"],
        "exact_duplicates_removed": duplicates_removed,
        "participant_names_from_export": participants,
        "sender_names_from_messages": sorted(sender_names),
        "message_counts_by_sender": dict(senders),
        "conversation_message_counts_by_sender": dict(conversation_senders),
        "message_counts_by_category": dict(categories),
        "analysis_text_kind_counts": dict(analysis_text_kinds),
        "messages_with_authored_text": nonempty_text_count,
        "shared_content_message_count": share_count,
        "reel_link_candidates": sum(1 for m in messages if m["reel_link_candidate"]),
        "reaction_count": reaction_count,
        "call_event_count": call_event_count,
        "attachment_item_counts": dict(media_items),
        "messages_with_attachment_field": dict(media_messages),
        "first_message_local": first,
        "last_message_local": last,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Glob for Instagram message JSON files")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path for the parsed JSON output")
    parser.add_argument("--timezone", default=None, help="IANA timezone for local reporting (default from analysis_config.json)")
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="Hinglish normalization rules JSON path")
    args = parser.parse_args()

    config = {}
    if DEFAULT_CONFIG.is_file():
        with DEFAULT_CONFIG.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    timezone_name = args.timezone or config.get("timezone", DEFAULT_TIMEZONE)
    with Path(args.rules).open("r", encoding="utf-8") as handle:
        normalization_rules = json.load(handle)

    # Path.glob intentionally keeps input files local and leaves originals untouched.
    pattern = Path(args.input)
    paths = sorted(pattern.parent.glob(pattern.name))
    if not paths:
        raise SystemExit(f"No input files matched: {args.input}")

    messages, summary = parse_files(paths, timezone_name, normalization_rules)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "messages": messages}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    # Keep terminal output useful without echoing participant names or chat text.
    print(json.dumps({
        "output": str(output_path),
        "unique_export_row_count": summary["unique_export_row_count"],
        "conversation_message_count": summary["conversation_message_count"],
        "reaction_notice_count": summary["reaction_notice_count"],
        "exact_duplicates_removed": summary["exact_duplicates_removed"],
        "first_message_local": summary["first_message_local"],
        "last_message_local": summary["last_message_local"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
