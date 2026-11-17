"""Build aggregate, local-only stats for the confirmed confession date."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any


def _local_time(row: dict[str, Any]) -> datetime | None:
    value = row.get("timestamp_local")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def analyze(
    parsed: dict[str, Any],
    sender_roles: dict[str, str],
    milestones: dict[str, Any],
) -> dict[str, Any]:
    confession = next((item for item in milestones.get("milestones", []) if item.get("key") == "confession"), {})
    confession_date = confession.get("date") if confession.get("confirmed") else None
    if not confession_date:
        return {"status": "unavailable", "reason": "The confession date is not confirmed."}

    try:
        day_one = date.fromisoformat(confession_date)
    except (TypeError, ValueError):
        return {"status": "unavailable", "reason": "The confirmed confession date is invalid."}
    day_two = day_one + timedelta(days=1)

    messages: list[dict[str, Any]] = []
    for row in parsed.get("messages", []):
        if row.get("analysis_text_kind") in {"reaction_notice", "unsent_media"}:
            continue
        local_time = _local_time(row)
        if local_time is None:
            continue
        sender_name = row.get("sender")
        role = sender_roles.get(sender_name, "unmapped") if isinstance(sender_name, str) else "unmapped"
        messages.append({"row": row, "local_time": local_time, "role": role})
    messages.sort(key=lambda item: item["local_time"])

    date_messages = {
        day.isoformat(): [item for item in messages if item["local_time"].date() == day]
        for day in (day_one, day_two)
    }
    daily_by_role = {
        day: dict(Counter(item["role"] for item in rows))
        for day, rows in date_messages.items()
    }

    you = next((role for role in set(sender_roles.values()) if role == "you"), "you")
    her = next((role for role in set(sender_roles.values()) if role == "her"), "her")
    proposal = None
    for item in date_messages[day_one.isoformat()]:
        if item["role"] != you:
            continue
        row = item["row"]
        links = row.get("shared_links") or []
        candidates = [link.get("url", "") for link in links if isinstance(link, dict)]
        candidates.append(row.get("analysis_text") or "")
        if any("proposal" in str(value).lower() for value in candidates):
            proposal = item
            break
    if proposal is None:
        return {
            "status": "unavailable",
            "reason": "No proposal-site link was found on the confirmed confession date.",
            "relationship_date": day_one.isoformat(),
            "messages_by_date": {day: len(rows) for day, rows in date_messages.items()},
            "messages_by_role_and_date": daily_by_role,
        }

    confession_prompt = next(
        (
            item for item in messages
            if item["role"] == her
            and proposal["local_time"] - timedelta(minutes=20) <= item["local_time"] < proposal["local_time"]
            and re.search(r"dubara\s+bol\s+kar\s+dikh", item["row"].get("analysis_text") or "", re.I)
        ),
        None,
    )
    website_reveal = next(
        (
            item for item in messages
            if item["role"] == you
            and proposal["local_time"] - timedelta(minutes=15) <= item["local_time"] < proposal["local_time"]
            and re.search(r"site|website", item["row"].get("analysis_text") or "", re.I)
            and re.search(r"bana\s+li|banai|already|ready", item["row"].get("analysis_text") or "", re.I)
        ),
        None,
    )
    website_surprise = next(
        (
            item for item in messages
            if item["role"] == her
            and website_reveal is not None
            and website_reveal["local_time"] <= item["local_time"] < proposal["local_time"]
            and re.search(r"itni\s+jaldi|time\s+lagega", item["row"].get("analysis_text") or "", re.I)
        ),
        None,
    )
    after_link = [item for item in messages if item["local_time"] >= proposal["local_time"]]
    her_after_link = [item for item in after_link if item["role"] == her]
    girlfriend_reply = next(
        (item for item in her_after_link if re.search(r"\bgirlfriend\b", item["row"].get("analysis_text") or "", re.I)),
        None,
    )
    love_reply = next(
        (item for item in her_after_link if re.search(r"\bi\s+love\s+you\s+too\b", item["row"].get("analysis_text") or "", re.I)),
        None,
    )
    no_button_surprise = next(
        (
            item for item in after_link
            if item["role"] == you
            and re.search(r"ek\s+baar\s+bhi\s+no\s+n(?:h|a)i\s+dabaya", item["row"].get("analysis_text") or "", re.I)
        ),
        None,
    )

    # The late-night chapter ends at the last conversation message before 04:00 IST.
    late_night_end = next(
        (
            item for item in reversed(messages)
            if item["local_time"].date() == day_two and item["local_time"].time().replace(tzinfo=None) < time(4, 0)
            and item["local_time"] >= proposal["local_time"]
        ),
        None,
    )
    if late_night_end is None:
        return {"status": "unavailable", "reason": "No late-night continuation was found after the proposal link."}

    chapter_messages = [
        item for item in messages
        if proposal["local_time"] <= item["local_time"] <= late_night_end["local_time"]
    ]
    elapsed = max(0, int((late_night_end["local_time"] - proposal["local_time"]).total_seconds()))
    return {
        "status": "available",
        "relationship_date": day_one.isoformat(),
        "next_date": day_two.isoformat(),
        "confession_prompt_at_local": confession_prompt["local_time"].isoformat() if confession_prompt else None,
        "website_revealed_at_local": website_reveal["local_time"].isoformat() if website_reveal else None,
        "website_surprise_at_local": website_surprise["local_time"].isoformat() if website_surprise else None,
        "proposal_link_sent_at_local": proposal["local_time"].isoformat(),
        "girlfriend_reply_at_local": girlfriend_reply["local_time"].isoformat() if girlfriend_reply else None,
        "first_i_love_you_back_at_local": love_reply["local_time"].isoformat() if love_reply else None,
        "no_button_surprise_at_local": no_button_surprise["local_time"].isoformat() if no_button_surprise else None,
        "late_night_last_message_at_local": late_night_end["local_time"].isoformat(),
        "messages_from_proposal_to_late_night": len(chapter_messages),
        "messages_from_proposal_to_late_night_by_role": dict(Counter(item["role"] for item in chapter_messages)),
        "seconds_from_proposal_to_late_night_end": elapsed,
        "messages_by_date": {day: len(rows) for day, rows in date_messages.items()},
        "messages_by_role_and_date": daily_by_role,
    }
