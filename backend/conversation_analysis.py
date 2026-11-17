"""Analyze conversation turns, reply timing, initiations, and active-day streaks."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any


DEFAULT_INPUT = Path("output/parsed_export.json")
DEFAULT_ROLES = Path("data/processed/sender_roles.json")
DEFAULT_OUTPUT = Path("output/conversation_analytics.json")
DEFAULT_GAP_HOURS = 8
SENSITIVITY_GAPS_HOURS = (1, 6, 8, 12, 24)


def usable_messages(parsed: dict[str, Any], role_map: dict[str, str]) -> tuple[list[dict[str, Any]], int, int]:
    rows = parsed.get("messages")
    if not isinstance(rows, list):
        raise ValueError("Parsed export must contain a messages list")

    result = []
    reaction_notices = 0
    unknown_senders = 0
    for row in rows:
        if row.get("analysis_text_kind") in {"reaction_notice", "unsent_media"}:
            if row.get("analysis_text_kind") == "reaction_notice":
                reaction_notices += 1
            continue
        raw = row.get("raw", {})
        sender_name = raw.get("sender_name")
        role = role_map.get(sender_name) if isinstance(sender_name, str) else None
        if role is None:
            unknown_senders += 1
            role = "unmapped"
        timestamp_ms = raw.get("timestamp_ms")
        try:
            timestamp_ms = float(timestamp_ms)
            local_value = row.get("timestamp_local")
            if not local_value:
                continue
            local_time = datetime.fromisoformat(local_value)
        except (TypeError, ValueError, OverflowError):
            continue
        result.append({
            "timestamp_ms": timestamp_ms,
            "timestamp_local": local_time,
            "role": role,
            "sender_name": sender_name,
            "category": row.get("category"),
            "message_id": row.get("id"),
            "text": row.get("analysis_text") if row.get("analysis_text_kind") == "message_text" else None,
            "words": row.get("words", []),
        })
    result.sort(key=lambda item: (item["timestamp_ms"], item["role"]))
    return result, reaction_notices, unknown_senders


def split_sessions(messages: list[dict[str, Any]], gap_hours: float) -> list[list[dict[str, Any]]]:
    if not messages:
        return []
    gap_ms = gap_hours * 60 * 60 * 1000
    sessions = []
    current = [messages[0]]
    for message in messages[1:]:
        if message["timestamp_ms"] - current[-1]["timestamp_ms"] > gap_ms:
            sessions.append(current)
            current = []
        current.append(message)
    sessions.append(current)
    return sessions


def summarize_sessions(sessions: list[list[dict[str, Any]]], roles: list[str]) -> dict[str, Any]:
    initiations: Counter[str] = Counter()
    messages_by_role: Counter[str] = Counter()
    for session in sessions:
        initiations[session[0]["role"]] += 1
        messages_by_role.update(message["role"] for message in session)

    durations = [
        max(0.0, (session[-1]["timestamp_ms"] - session[0]["timestamp_ms"]) / 1000)
        for session in sessions
    ]
    longest_duration = max(durations, default=0.0)
    longest_message_count = max((len(session) for session in sessions), default=0)

    def session_row(session: list[dict[str, Any]]) -> dict[str, Any]:
        duration_seconds = max(0.0, (session[-1]["timestamp_ms"] - session[0]["timestamp_ms"]) / 1000)
        counts = Counter(message["role"] for message in session)
        return {
            "start_local": session[0]["timestamp_local"].isoformat(timespec="milliseconds"),
            "end_local": session[-1]["timestamp_local"].isoformat(timespec="milliseconds"),
            "duration_seconds": round(duration_seconds, 3),
            "duration_hours": round(duration_seconds / 3600, 3),
            "message_count": len(session),
            "initiator": session[0]["role"],
            "messages_by_role": {role: counts[role] for role in roles},
        }

    per_role = {
        role: {
            "initiated_conversations": initiations[role],
            "share_of_conversations_percent": round(100 * initiations[role] / len(sessions), 2) if sessions else 0,
            "message_count": messages_by_role[role],
        }
        for role in roles
    }
    return {
        "conversation_count": len(sessions),
        "conversations_by_initiator": {role: initiations[role] for role in roles},
        "by_role": per_role,
        "longest_by_duration": [
            session_row(session) for session, duration in zip(sessions, durations) if duration == longest_duration
        ],
        "longest_by_message_count": [
            session_row(session) for session in sessions if len(session) == longest_message_count
        ],
    }


def reply_and_double_text_stats(
    sessions: list[list[dict[str, Any]]], roles: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    reply_seconds: dict[str, list[float]] = defaultdict(list)
    reply_seconds_by_month: dict[str, list[float]] = defaultdict(list)
    reply_seconds_by_month_role: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    fastest = None
    slowest = None
    double_text_runs: Counter[str] = Counter()
    double_text_extras: Counter[str] = Counter()

    for session in sessions:
        run_role = session[0]["role"]
        run_count = 1
        for previous, current in zip(session, session[1:]):
            if current["role"] == previous["role"]:
                if current["role"] == run_role:
                    run_count += 1
                else:
                    run_role, run_count = current["role"], 1
                continue

            # A role switch is a reply turn; latency runs from the other
            # person's last message to this person's first message in the turn.
            delta = max(0.0, (current["timestamp_ms"] - previous["timestamp_ms"]) / 1000)
            reply_seconds[current["role"]].append(delta)
            month = current["timestamp_local"].strftime("%Y-%m")
            reply_seconds_by_month[month].append(delta)
            reply_seconds_by_month_role[month][current["role"]].append(delta)
            if fastest is None or delta < fastest["seconds"]:
                fastest = {
                    "responder": current["role"],
                    "seconds": round(delta, 3),
                    "from_local": previous["timestamp_local"].isoformat(timespec="milliseconds"),
                    "reply_local": current["timestamp_local"].isoformat(timespec="milliseconds"),
                }
            if slowest is None or delta > slowest["seconds"]:
                slowest = {
                    "responder": current["role"],
                    "seconds": round(delta, 3),
                    "from_local": previous["timestamp_local"].isoformat(timespec="milliseconds"),
                    "reply_local": current["timestamp_local"].isoformat(timespec="milliseconds"),
                }
            if run_count >= 2:
                double_text_runs[run_role] += 1
                double_text_extras[run_role] += run_count - 1
            run_role, run_count = current["role"], 1

        if run_count >= 2:
            double_text_runs[run_role] += 1
            double_text_extras[run_role] += run_count - 1

    reply_stats = {}
    double_text_stats = {}
    for role in roles:
        values = reply_seconds[role]
        reply_stats[role] = {
            "reply_count": len(values),
            "average_seconds": round(mean(values), 3) if values else None,
            "average_minutes": round(mean(values) / 60, 2) if values else None,
            "median_seconds": round(median(values), 3) if values else None,
            "fastest_seconds": round(min(values), 3) if values else None,
            "slowest_seconds": round(max(values), 3) if values else None,
        }
        double_text_stats[role] = {
            "double_text_runs": double_text_runs[role],
            "additional_messages_in_runs": double_text_extras[role],
        }
    monthly = {}
    for month, values in sorted(reply_seconds_by_month.items()):
        monthly[month] = {
            "reply_count": len(values),
            "average_seconds": round(mean(values), 3),
            "median_seconds": round(median(values), 3),
            "by_responder": {
                role: {
                    "reply_count": len(role_values),
                    "average_seconds": round(mean(role_values), 3),
                    "median_seconds": round(median(role_values), 3),
                }
                for role, role_values in sorted(reply_seconds_by_month_role[month].items())
            },
        }
    return {"by_responder": reply_stats, "fastest_reply": fastest, "slowest_reply": slowest, "by_month": monthly}, double_text_stats


def message_turn_metrics(sessions: list[list[dict[str, Any]]], roles: list[str]) -> dict[str, Any]:
    one_word = Counter()
    question_messages = Counter()
    question_marks = Counter()
    max_consecutive = Counter()
    unanswered_turns = Counter()
    unanswered_messages = Counter()

    for session_index, session in enumerate(sessions):
        run_role = session[0]["role"]
        run_count = 0
        for message in session:
            role = message["role"]
            if role == run_role:
                run_count += 1
            else:
                max_consecutive[run_role] = max(max_consecutive[run_role], run_count)
                run_role, run_count = role, 1

            words = message.get("words") or []
            if len(words) == 1:
                one_word[role] += 1
            text = message.get("text") or ""
            marks = text.count("?") + text.count("？")
            if marks:
                question_messages[role] += 1
                question_marks[role] += marks

        max_consecutive[run_role] = max(max_consecutive[run_role], run_count)

        # A session closed by a later inactivity gap is eligible. The final
        # export session is open-ended, so its trailing turn is not called unanswered.
        if session_index < len(sessions) - 1:
            trailing_role = session[-1]["role"]
            trailing_count = 0
            for message in reversed(session):
                if message["role"] != trailing_role:
                    break
                trailing_count += 1
            if trailing_count:
                unanswered_turns[trailing_role] += 1
                unanswered_messages[trailing_role] += trailing_count

    return {
        "one_word_messages_by_role": {role: one_word[role] for role in roles},
        "question_messages_by_role": {role: question_messages[role] for role in roles},
        "question_mark_count_by_role": {role: question_marks[role] for role in roles},
        "maximum_consecutive_messages_by_role": {role: max_consecutive[role] for role in roles},
        "unanswered_final_turns_by_role": {role: unanswered_turns[role] for role in roles},
        "messages_without_subsequent_reply_by_role": {role: unanswered_messages[role] for role in roles},
        "unanswered_definition": "Counts only the trailing sender turn of sessions confirmed closed by an inactivity gap. The final export session is excluded because the export may end before a reply arrives.",
    }


def longest_inactivity_gap(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    longest = None
    for previous, current in zip(messages, messages[1:]):
        seconds = (current["timestamp_ms"] - previous["timestamp_ms"]) / 1000
        if longest is None or seconds > longest["seconds"]:
            longest = {
                "seconds": round(seconds, 3),
                "hours": round(seconds / 3600, 3),
                "from_local": previous["timestamp_local"].isoformat(timespec="milliseconds"),
                "to_local": current["timestamp_local"].isoformat(timespec="milliseconds"),
                "previous_sender": previous["role"],
                "next_sender": current["role"],
            }
    return longest


def longest_active_day_streak(messages: list[dict[str, Any]]) -> dict[str, Any]:
    active_days = sorted({message["timestamp_local"].date() for message in messages})
    if not active_days:
        return {"days": 0, "start_date": None, "end_date": None}
    best_start = run_start = active_days[0]
    best_end = run_end = active_days[0]
    best_length = run_length = 1
    for day in active_days[1:]:
        if day == run_end + timedelta(days=1):
            run_end = day
            run_length += 1
        else:
            if run_length > best_length:
                best_start, best_end, best_length = run_start, run_end, run_length
            run_start = run_end = day
            run_length = 1
    if run_length > best_length:
        best_start, best_end, best_length = run_start, run_end, run_length
    return {"days": best_length, "start_date": best_start.isoformat(), "end_date": best_end.isoformat()}


def analyze(parsed: dict[str, Any], role_map: dict[str, str], default_gap_hours: float = DEFAULT_GAP_HOURS) -> dict[str, Any]:
    messages, reaction_notices, unknown_senders = usable_messages(parsed, role_map)
    roles = sorted(set(role_map.values()))
    sessions = split_sessions(messages, default_gap_hours)
    session_summary = summarize_sessions(sessions, roles)
    replies, double_text = reply_and_double_text_stats(sessions, roles)

    active_dates = Counter(message["timestamp_local"].date().isoformat() for message in messages)
    peak_count = max(active_dates.values(), default=0)
    most_active_dates = [
        {"date": day, "message_count": count}
        for day, count in sorted(active_dates.items())
        if count == peak_count
    ]
    sensitivity = {}
    for hours in SENSITIVITY_GAPS_HOURS:
        sensitivity[str(hours)] = summarize_sessions(split_sessions(messages, hours), roles)

    dayparts = Counter()
    weekends = Counter()
    messages_by_month = Counter()
    messages_by_month_role: dict[str, Counter[str]] = defaultdict(Counter)
    messages_after_midnight = Counter()
    active_hour_buckets = set()
    for message in messages:
        local = message["timestamp_local"]
        hour = local.hour
        dayparts["morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 21 else "night"] += 1
        weekends["weekend" if local.weekday() >= 5 else "weekday"] += 1
        messages_by_month[local.strftime("%Y-%m")] += 1
        messages_by_month_role[local.strftime("%Y-%m")][message["role"]] += 1
        if hour < 5:
            messages_after_midnight[message["role"]] += 1
        active_hour_buckets.add(local.strftime("%Y-%m-%d %H"))

    turn_metrics = message_turn_metrics(sessions, roles)
    valid_times = [message["timestamp_local"] for message in messages]
    calendar_span_hours = max(1.0, ((valid_times[-1].date() - valid_times[0].date()).days + 1) * 24) if valid_times else 0

    return {
        "timezone": parsed.get("summary", {}).get("timezone", "Asia/Kolkata"),
        "raw_export_row_count": len(parsed.get("messages", [])),
        "reaction_notice_rows_excluded_from_message_metrics": reaction_notices,
        "conversation_message_count": len(messages),
        "unknown_sender_rows": unknown_senders,
        "session_gap_hours": default_gap_hours,
        "messages_by_role": dict(Counter(message["role"] for message in messages)),
        "first_conversation_message": {
            "timestamp_local": messages[0]["timestamp_local"].isoformat(timespec="milliseconds") if messages else None,
            "sender": messages[0]["role"] if messages else None,
            "category": messages[0]["category"] if messages else None,
        },
        "conversation_summary": session_summary,
        "reply_times": replies,
        "message_dynamics": turn_metrics,
        "longest_inactivity_gap": longest_inactivity_gap(messages),
        "double_texting": {
            "by_role": double_text,
            "definition": "One run of at least two consecutive messages by the same sender within a conversation session; extra-message count is reported separately.",
        },
        "activity": {
            "most_active_calendar_dates": most_active_dates,
            "active_calendar_dates": len(active_dates),
            "longest_active_day_streak": longest_active_day_streak(messages),
            "messages_by_month": dict(sorted(messages_by_month.items())),
            "messages_by_month_and_role": {
                month: {role: counts[role] for role in roles}
                for month, counts in sorted(messages_by_month_role.items())
            },
            "messages_by_daypart": dict(dayparts),
            "weekday_vs_weekend": dict(weekends),
            "messages_after_midnight_by_role": {role: messages_after_midnight[role] for role in roles},
            "active_date_hour_buckets": len(active_hour_buckets),
            "average_messages_per_active_hour": round(len(messages) / len(active_hour_buckets), 3) if active_hour_buckets else None,
            "average_messages_per_clock_hour_over_calendar_span": round(len(messages) / calendar_span_hours, 3) if calendar_span_hours else None,
        },
        "session_gap_sensitivity_hours": sensitivity,
        "definitions": {
            "conversation_session": "A run of messages separated by no more than the configured inactivity gap; gaps greater than the threshold start a new session.",
            "reply_time": "When the sender changes, elapsed time from the previous message to the first message by the new sender, within a session.",
            "reaction_notices": "Instagram-generated 'reacted to your message' rows are excluded; structured reaction metadata is analyzed separately.",
            "longest_conversation": "Reported both by elapsed duration and by message count; tied sessions are included.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Parsed export JSON path")
    parser.add_argument("--roles", default=str(DEFAULT_ROLES), help="Sender-role mapping JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Conversation analytics output path")
    parser.add_argument("--gap-hours", type=float, default=DEFAULT_GAP_HOURS, help="Inactivity gap that starts a new conversation")
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    with Path(args.roles).open("r", encoding="utf-8") as handle:
        role_map = json.load(handle)
    result = analyze(parsed, role_map, args.gap_hours)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({
        "output": str(output_path),
        "conversation_message_count": result["conversation_message_count"],
        "conversation_count_at_default_gap": result["conversation_summary"]["conversation_count"],
        "reaction_notice_rows_excluded": result["reaction_notice_rows_excluded_from_message_metrics"],
        "session_gap_hours": result["session_gap_hours"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
