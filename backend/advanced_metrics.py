"""Additional transparent metrics layered over the existing parsed export."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median
from typing import Any

try:
    from .conversation_analysis import split_sessions, usable_messages
    from .emoji_analysis import HEARTS, ROMANTIC, extract_emojis
    from .language_analyzer import TOKEN_PATTERN
    from .media_analysis import classify_types
except ImportError:
    from conversation_analysis import split_sessions, usable_messages
    from emoji_analysis import HEARTS, ROMANTIC, extract_emojis
    from language_analyzer import TOKEN_PATTERN
    from media_analysis import classify_types


REPLY_BUCKETS = (
    ("under_1_minute", 0, 60),
    ("1_to_5_minutes", 60, 300),
    ("5_to_30_minutes", 300, 1800),
    ("30_to_60_minutes", 1800, 3600),
    ("1_to_6_hours", 3600, 21600),
    ("6_plus_hours", 21600, float("inf")),
)
WORD_RE = TOKEN_PATTERN


def _valid_rows(parsed: dict[str, Any], role_map: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for row in parsed.get("messages", []):
        if row.get("analysis_text_kind") in {"reaction_notice", "unsent_media"}:
            continue
        raw = row.get("raw", {})
        sender = raw.get("sender_name")
        stamp = row.get("timestamp_ms", raw.get("timestamp_ms"))
        local = row.get("timestamp_local")
        try:
            timestamp_ms = float(stamp)
            local_time = datetime.fromisoformat(local)
        except (TypeError, ValueError, OverflowError):
            continue
        rows.append({
            "row": row,
            "timestamp_ms": timestamp_ms,
            "local": local_time,
            "role": role_map.get(sender, "unmapped") if isinstance(sender, str) else "unmapped",
            "text": row.get("analysis_text") if row.get("analysis_text_kind") == "message_text" else "",
            "normalized_text": row.get("normalized_text") if isinstance(row.get("normalized_text"), str) else None,
            "kind": row.get("analysis_text_kind"),
        })
    rows.sort(key=lambda item: (item["timestamp_ms"], item["role"]))
    return rows


def _sessions(rows: list[dict[str, Any]], gap_hours: float) -> list[list[dict[str, Any]]]:
    messages = [{
        "timestamp_ms": item["timestamp_ms"], "timestamp_local": item["local"],
        "role": item["role"], "sender_name": None, "category": None,
        "message_id": item["row"].get("id"), "text": item["text"], "words": WORD_RE.findall(item["text"]),
        "_source": item,
    } for item in rows]
    return split_sessions(messages, gap_hours)


def _reply_samples(sessions: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    samples = []
    for session in sessions:
        for previous, current in zip(session, session[1:]):
            if previous["role"] == current["role"]:
                continue
            seconds = (current["timestamp_ms"] - previous["timestamp_ms"]) / 1000
            # Same-millisecond and negative comparisons have no meaningful latency.
            if seconds <= 0:
                continue
            samples.append({"role": current["role"], "seconds": seconds, "reply_local": current["timestamp_local"]})
    return samples


def conversation_metrics(rows: list[dict[str, Any]], role_map: dict[str, str], gap_hours: float,
                         existing_dynamics: dict[str, Any]) -> dict[str, Any]:
    roles = sorted(set(role_map.values()))
    sessions = _sessions(rows, gap_hours)
    run_lengths: dict[str, Counter[int]] = defaultdict(Counter)
    max_run: Counter[str] = Counter()
    double_runs: Counter[str] = Counter()
    triple_runs: Counter[str] = Counter()
    ending_counts: Counter[str] = Counter()
    message_counts_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    longest_text: dict[str, dict[str, Any] | None] = {role: None for role in roles}
    text_char_counts: Counter[str] = Counter()
    text_message_counts: Counter[str] = Counter()
    for session in sessions:
        if session:
            ending_counts[session[-1]["role"]] += 1
        run_role = None
        run_len = 0
        for message in session:
            role = message["role"]
            message_counts_by_role["all"][role] += 1
            text = message.get("text") or ""
            if text.strip():
                length = len(text.strip())
                text_char_counts[role] += length
                text_message_counts[role] += 1
                previous = longest_text.get(role)
                if previous is None or length > previous["character_count"]:
                    longest_text[role] = {
                        "character_count": length,
                        "timestamp_local": message["timestamp_local"].isoformat(timespec="milliseconds"),
                        "message_id": message.get("message_id"),
                    }
            if run_role is None:
                run_role, run_len = role, 1
            elif role == run_role:
                run_len += 1
            else:
                run_lengths[run_role][run_len] += 1
                max_run[run_role] = max(max_run[run_role], run_len)
                if run_len >= 2:
                    double_runs[run_role] += 1
                if run_len >= 3:
                    triple_runs[run_role] += 1
                run_role, run_len = role, 1
        if run_role is not None:
            run_lengths[run_role][run_len] += 1
            max_run[run_role] = max(max_run[run_role], run_len)
            if run_len >= 2:
                double_runs[run_role] += 1
            if run_len >= 3:
                triple_runs[run_role] += 1

    total_sessions = len(sessions)
    reply_samples = _reply_samples(sessions)
    by_responder: dict[str, list[float]] = defaultdict(list)
    delay_buckets: dict[str, Counter[str]] = defaultdict(Counter)
    replies_by_hour: dict[int, list[float]] = defaultdict(list)
    replies_by_hour_role: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for sample in reply_samples:
        by_responder[sample["role"]].append(sample["seconds"])
        replies_by_hour[sample["reply_local"].hour].append(sample["seconds"])
        replies_by_hour_role[sample["reply_local"].hour][sample["role"]].append(sample["seconds"])
        for label, lower, upper in REPLY_BUCKETS:
            if lower <= sample["seconds"] < upper:
                delay_buckets[sample["role"]][label] += 1
                break

    valid_fastest = min(reply_samples, key=lambda item: item["seconds"], default=None)
    valid_slowest = max(reply_samples, key=lambda item: item["seconds"], default=None)
    longest_sessions = existing_dynamics.get("conversation_summary", {}).get("longest_by_duration", [])
    return {
        "double_and_triple_texting": {
            "by_role": {role: {"runs_of_2_plus": double_runs[role], "runs_of_3_plus": triple_runs[role],
                               "additional_messages_in_2_plus_runs": sum((length - 1) * count for length, count in run_lengths[role].items() if length >= 2),
                               "run_length_distribution": {str(length): count for length, count in sorted(run_lengths[role].items())}}
                      for role in roles},
            "definition": "A burst is a maximal run by one sender in a session; double/triple counts mean runs of at least 2/3 consecutive export rows.",
        },
        "consecutive_message_bursts": {
            "run_count_by_role": {role: sum(run_lengths[role].values()) for role in roles},
            "maximum_run_length_by_role": {role: max_run[role] for role in roles},
            "run_length_distribution_by_role": {role: {str(length): count for length, count in sorted(run_lengths[role].items())} for role in roles},
            "definition": "Consecutive same-sender rows within a configured session; attachment-only rows count as a turn, reaction notices do not.",
        },
        "conversation_sessions": {
            "count": total_sessions,
            "average_messages_per_session": round(sum(map(len, sessions)) / total_sessions, 2) if total_sessions else None,
            "ending_frequency_by_role": {role: ending_counts[role] for role in roles},
            "ending_share_percent_by_role": {role: round(ending_counts[role] * 100 / total_sessions, 2) if total_sessions else None for role in roles},
            "longest_uninterrupted_by_duration": longest_sessions,
            "longest_uninterrupted_by_message_count": existing_dynamics.get("conversation_summary", {}).get("longest_by_message_count", []),
            "definition": f"Sessions split only when the gap between adjacent rows exceeds {gap_hours:g} hours; the last sender is the session ender, not necessarily someone ending the relationship or chat intentionally.",
        },
        "message_lengths": {
            "longest_single_text_message_by_role": longest_text,
            "average_text_length_characters_by_role": {role: round(text_char_counts[role] / text_message_counts[role], 2) if text_message_counts[role] else None for role in roles},
            "text_message_count_by_role": {role: text_message_counts[role] for role in roles},
            "definition": "Character length uses analysis text after trimming outer whitespace. Attachment notices, empty/system rows, and reactions are excluded from text length.",
        },
        "questions_asked": {
            "message_count_by_role": existing_dynamics.get("message_dynamics", {}).get("question_messages_by_role", {}),
            "question_mark_count_by_role": existing_dynamics.get("message_dynamics", {}).get("question_mark_count_by_role", {}),
            "definition": "Counts authored text rows containing one or more ASCII or full-width question marks; question marks are also counted individually.",
        },
        "valid_reply_latency": {
            "fastest": {"responder": valid_fastest["role"], "seconds": round(valid_fastest["seconds"], 3), "timestamp_local": valid_fastest["reply_local"].isoformat(timespec="milliseconds")} if valid_fastest else None,
            "slowest": {"responder": valid_slowest["role"], "seconds": round(valid_slowest["seconds"], 3), "timestamp_local": valid_slowest["reply_local"].isoformat(timespec="milliseconds")} if valid_slowest else None,
            "valid_reply_count": len(reply_samples),
            "by_responder": {
                role: {
                    "count": len(by_responder[role]),
                    "average_seconds": round(mean(by_responder[role]), 3) if by_responder[role] else None,
                    "fastest_seconds": round(min(by_responder[role]), 3) if by_responder[role] else None,
                    "slowest_seconds": round(max(by_responder[role]), 3) if by_responder[role] else None,
                }
                for role in roles
            },
            "delay_buckets_by_responder": {role: {label: delay_buckets[role][label] for label, _, _ in REPLY_BUCKETS} for role in roles},
            "definition": "Only positive timestamp deltas across a sender switch within a session. Equal or negative deltas are excluded because they have no valid reply latency.",
        },
        "reply_speed_by_hour": {
            f"{hour:02d}:00": {
                "reply_count": len(values),
                "average_seconds": round(mean(values), 3),
                "by_responder": {role: {"count": len(role_values), "average_seconds": round(mean(role_values), 3)}
                                 for role, role_values in sorted(replies_by_hour_role[hour].items())},
            }
            for hour, values in sorted(replies_by_hour.items())
        },
        "reply_speed_by_hour_definition": "Local hour of the reply message; only positive-latency sender switches within a session are included.",
    }


def _longest_gap(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    pairs = list(zip(rows, rows[1:]))
    if not pairs:
        return None
    previous, current = max(pairs, key=lambda pair: pair[1]["timestamp_ms"] - pair[0]["timestamp_ms"])
    return {
        "hours": round((current["timestamp_ms"] - previous["timestamp_ms"]) / 3_600_000, 3),
        "from_timestamp_local": previous["local"].isoformat(timespec="milliseconds"),
        "to_timestamp_local": current["local"].isoformat(timespec="milliseconds"),
    }


def time_metrics(rows: list[dict[str, Any]], role_map: dict[str, str], gap_hours: float,
                 timezone_name: str = "Asia/Kolkata") -> dict[str, Any]:
    roles = sorted(set(role_map.values()))
    if not rows:
        return {"timezone": "Asia/Kolkata", "message_count": 0, "definition": "No timestamped rows."}
    all_dates = [item["local"].date() for item in rows]
    start_day, end_day = min(all_dates), max(all_dates)
    date_counts: Counter[date] = Counter()
    role_date_counts: dict[str, Counter[date]] = defaultdict(Counter)
    half_hour_counts: Counter[int] = Counter()
    role_half_hour: dict[str, Counter[int]] = defaultdict(Counter)
    midnight: Counter[str] = Counter()
    night_owl_02_to_05: Counter[str] = Counter()
    working: Counter[str] = Counter()
    weekday_weekend: dict[str, Counter[str]] = defaultdict(Counter)
    media_days: dict[str, set[date]] = defaultdict(set)
    media_by_date: Counter[date] = Counter()
    for item in rows:
        dt, role = item["local"], item["role"]
        day = dt.date()
        date_counts[day] += 1
        role_date_counts[role][day] += 1
        slot = dt.hour * 2 + dt.minute // 30
        half_hour_counts[slot] += 1
        role_half_hour[role][slot] += 1
        if dt.hour < 5:
            midnight[role] += 1
        if 2 <= dt.hour < 5:
            night_owl_02_to_05[role] += 1
        if 9 <= dt.hour < 17:
            working[role] += 1
        weekday_weekend[role]["weekend" if dt.weekday() >= 5 else "weekday"] += 1
        if item["row"].get("attachments") or item["row"].get("shared_links"):
            media_days[role].add(day)
            media_by_date[day] += 1

    def best_window(width: int) -> dict[str, Any]:
        if (end_day - start_day).days + 1 < width:
            return {"window_days": width, "message_count": None, "windows": [], "status": "insufficient_export_span",
                    "definition": f"Highest message count in any {width} consecutive local calendar dates, inclusive."}
        span = max(0, (end_day - start_day).days - width + 1)
        winners = []
        peak = 0
        for offset in range(span + 1):
            first = start_day + timedelta(days=offset)
            count = sum(date_counts[first + timedelta(days=i)] for i in range(width))
            if count > peak:
                peak, winners = count, [first]
            elif count == peak and count:
                winners.append(first)
        return {"window_days": width, "message_count": peak, "windows": [{"start_date": d.isoformat(), "end_date": (d + timedelta(days=width - 1)).isoformat()} for d in winners],
                "definition": f"Highest message count in any {width} consecutive local calendar dates, inclusive."}

    def streak(days: set[date]) -> dict[str, Any]:
        sorted_days = sorted(days)
        if not sorted_days:
            return {"days": 0, "start_date": None, "end_date": None}
        best_start = run_start = sorted_days[0]
        best_end = run_end = sorted_days[0]
        best = run = 1
        for current in sorted_days[1:]:
            if current == run_end + timedelta(days=1):
                run_end, run = current, run + 1
            else:
                if run > best:
                    best_start, best_end, best = run_start, run_end, run
                run_start = run_end = current
                run = 1
        if run > best:
            best_start, best_end, best = run_start, run_end, run
        return {"days": best, "start_date": best_start.isoformat(), "end_date": best_end.isoformat()}

    windows = {}
    for label, counter in [("combined", half_hour_counts), *[(role, role_half_hour[role]) for role in roles]]:
        peak = max(counter.values(), default=0)
        winners = [{"start": f"{slot // 2:02d}:{'30' if slot % 2 else '00'}", "end": f"{(slot + 1) // 2:02d}:{'30' if (slot + 1) % 2 else '00'}", "message_count": count}
                   for slot, count in sorted(counter.items()) if count == peak] if peak else []
        windows[label] = winners

    max_media = max(media_by_date.values(), default=0)
    sessions = _sessions(rows, gap_hours)
    chat_time_silence_cutoff_minutes = 15
    chat_time_sessions = _sessions(rows, chat_time_silence_cutoff_minutes / 60)
    chat_time_elapsed_seconds = sum(
        max(0.0, (session[-1]["timestamp_ms"] - session[0]["timestamp_ms"]) / 1000)
        for session in chat_time_sessions
    )
    long_gap_returns = Counter()
    below_24_band = f"over_{gap_hours:g}_to_under_24_hours"
    return_gaps = {below_24_band: Counter(), "24_plus_hours": Counter()}
    # Return-after-silence is attributed to whoever sends the first row after the gap.
    for previous, current in zip(rows, rows[1:]):
        delta_hours = (current["timestamp_ms"] - previous["timestamp_ms"]) / 3_600_000
        if delta_hours <= gap_hours:
            continue
        long_gap_returns[current["role"]] += 1
        bucket = "24_plus_hours" if delta_hours >= 24 else below_24_band
        return_gaps[bucket][current["role"]] += 1

    inclusive_days = (end_day - start_day).days + 1
    consistency = {}
    for role in roles:
        active = role_date_counts[role]
        consistency[role] = {
            "active_dates": len(active), "calendar_dates_in_export_span": inclusive_days,
            "active_date_percent": round(len(active) * 100 / inclusive_days, 2) if inclusive_days else None,
            "average_messages_per_active_date": round(sum(active.values()) / len(active), 2) if active else None,
            "longest_active_day_streak": streak(set(active)),
        }
    return {
        "timezone": timezone_name,
        "midnight_00_to_05_by_role": {role: midnight[role] for role in roles},
        "night_owl_02_to_05_by_role": {role: night_owl_02_to_05[role] for role in roles},
        "working_hours_09_to_17_by_role": {role: working[role] for role in roles},
        "weekday_vs_weekend_by_role": {role: dict(weekday_weekend[role]) for role in roles},
        "most_active_30_minute_clock_windows": windows,
        "approximate_chat_time": {
            "total_elapsed_hours": round(chat_time_elapsed_seconds / 3600, 1),
            "rounded_hours": round(chat_time_elapsed_seconds / 3600),
            "session_count": len(chat_time_sessions),
            "silence_cutoff_minutes": chat_time_silence_cutoff_minutes,
            "definition": "Approximate elapsed time summed across sessions; a new session starts when the gap between consecutive conversation messages exceeds 15 minutes. This includes short pauses and does not measure hands-on typing time.",
        },
        "most_active_consecutive_3_day_period": best_window(3),
        "most_active_consecutive_7_day_period": best_window(7),
        "longest_inactive_gap": _longest_gap(rows),
        "return_after_silence": {
            "silence_threshold_hours": gap_hours,
            "returning_sender_counts": {role: long_gap_returns[role] for role in roles},
            "by_gap_band_and_returning_sender": {band: {role: counts[role] for role in roles} for band, counts in return_gaps.items()},
            "definition": "A return counts when any sender sends the first row after a gap exceeding the configured session threshold; no inference about intent is made.",
        },
        "daily_messaging_consistency_by_role": consistency,
        "most_media_shared_in_one_day": {"message_count": max_media, "dates": [day.isoformat() for day, count in sorted(media_by_date.items()) if count == max_media]} if max_media else {"message_count": 0, "dates": []},
        "definition": "Time windows use the parsed local timestamp (Asia/Kolkata by default). Midnight means 00:00–04:59; working hours means 09:00–16:59. The 30-minute clock window aggregates the same time-of-day slot across all local dates.",
    }


def language_metrics(rows: list[dict[str, Any]], role_map: dict[str, str], normalization_rules: dict[str, list[str]], lexicon: dict[str, Any] | None = None) -> dict[str, Any]:
    roles = sorted(set(role_map.values()))
    abbreviation_words = {str(word).casefold() for word in (lexicon or {}).get("abbreviation_words", [])}
    aliases = {}
    for canonical, forms in normalization_rules.items():
        for form in [canonical, *forms]:
            aliases[form.casefold()] = canonical.casefold()
    words: dict[str, Counter[str]] = defaultdict(Counter)
    opening: dict[str, Counter[str]] = defaultdict(Counter)
    ending: dict[str, Counter[str]] = defaultdict(Counter)
    monthly: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    repeated: dict[str, Counter[str]] = defaultdict(Counter)
    repeated_combined: Counter[str] = Counter()
    punctuation: dict[str, Counter[str]] = defaultdict(Counter)
    abbreviations: dict[str, Counter[str]] = defaultdict(Counter)
    for item in rows:
        text, role = item["text"], item["role"]
        if not text.strip():
            continue
        normalized = item.get("normalized_text") or text
        tokens = [aliases.get(token.casefold(), token.casefold()) for token in WORD_RE.findall(normalized)]
        if not tokens:
            continue
        words[role].update(tokens)
        abbreviations[role].update(token for token in tokens if token in abbreviation_words)
        opening[role][tokens[0]] += 1
        ending[role][tokens[-1]] += 1
        month = item["local"].strftime("%Y-%m")
        monthly[month][role].update(tokens)
        normalized_sentence = re.sub(r"\s+", " ", normalized.strip()).casefold()
        repeated[role][normalized_sentence] += 1
        repeated_combined[normalized_sentence] += 1
        punctuation[role]["question_marks"] += text.count("?") + text.count("؟") + text.count("？")
        punctuation[role]["exclamation_marks"] += text.count("!") + text.count("！")
        punctuation[role]["messages_with_question_mark"] += int(any(mark in text for mark in "?؟？"))
        punctuation[role]["messages_with_exclamation_mark"] += int(any(mark in text for mark in "!！"))
        punctuation[role]["all_caps_messages"] += int(any(ch.isalpha() for ch in text) and text.upper() == text and sum(ch.isalpha() for ch in text) >= 2)

    profiles = {}
    for role in roles:
        profiles[role] = {
            "unique_vocabulary_size": len(words[role]),
            "most_common_opening_words": [{"word": word, "count": count} for word, count in opening[role].most_common(20)],
            "most_common_ending_words": [{"word": word, "count": count} for word, count in ending[role].most_common(20)],
            "exclusive_words": [{"word": word, "count": count} for word, count in words[role].most_common() if all(words[other][word] == 0 for other in roles if other != role)][:100],
            "punctuation_and_caps": dict(punctuation[role]),
            "abbreviation_frequency": {word: count for word, count in abbreviations[role].most_common()},
            "exclusive_vocabulary_size": sum(1 for word in words[role] if all(words[other][word] == 0 for other in roles if other != role)),
            "most_repeated_sentences": [{"sentence": sentence, "count": count} for sentence, count in repeated[role].most_common(50) if count >= 2],
        }
    shared = set(words[roles[0]]) if roles else set()
    for role in roles[1:]:
        shared.intersection_update(words[role])
    union = set().union(*(set(words[role]) for role in roles)) if roles else set()
    return {
        "by_role": profiles,
        "most_repeated_sentences_combined": [{"sentence": sentence, "count": count} for sentence, count in repeated_combined.most_common(50) if count >= 2],
        "shared_vocabulary": {"size": len(shared), "jaccard_similarity_percent": round(100 * len(shared) / len(union), 2) if union else None,
                              "common_words": [{"word": word, "counts_by_role": {role: words[role][word] for role in roles}} for word in sorted(shared, key=lambda w: -sum(words[role][w] for role in roles))[:100]],
                              "definition": "Shared vocabulary means normalized tokens used at least once by every mapped participant; Jaccard is shared unique words divided by total unique words."},
        "most_used_words_by_month_and_role": {month: {role: [{"word": word, "count": count} for word, count in counts[role].most_common(20)] for role in roles} for month, counts in sorted(monthly.items())},
        "sentence_definition": "Exact case-folded message text after whitespace collapsing; punctuation is retained. Repeated means at least twice by the same role.",
        "punctuation_definition": "Counts punctuation in authored analysis text. ALL CAPS counts messages with at least two letters and all letters uppercase; numerals and punctuation do not affect case.",
    }


def media_metrics(rows: list[dict[str, Any]], role_map: dict[str, str]) -> dict[str, Any]:
    roles = sorted(set(role_map.values()))
    types_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    link_candidates_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    month_role: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    month_links_by_role: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    attachment_items_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    month_attachment_items: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    observed_attachment_types: set[str] = set()
    media_days_by_role: dict[str, set[date]] = defaultdict(set)
    media_count_day: Counter[date] = Counter()
    text_count: Counter[str] = Counter()
    media_message_count: Counter[str] = Counter()
    reactions_on_shared: Counter[str] = Counter()
    total_shared_content_reactions = 0
    for item in rows:
        row, role = item["row"], item["role"]
        if item["kind"] == "message_text" and item["text"].strip():
            text_count[role] += 1
        links = row.get("shared_links", [])
        attachments = row.get("attachments", [])
        types = classify_types(row)
        media_types = [kind for kind in types if kind not in {"text", "reaction_event", "attachment_notice", "other_or_empty"}]
        month = item["local"].strftime("%Y-%m")
        for link in links:
            kind = link.get("candidate_type", "other_link")
            link_candidates_by_role[role][kind] += 1
            month_links_by_role[month][role][kind] += 1
        if media_types:
            media_message_count[role] += 1
            media_days_by_role[role].add(item["local"].date())
            media_count_day[item["local"].date()] += 1
        for kind in media_types:
            types_by_role[role][kind] += 1
            month_role[month][role][kind] += 1
        for attachment in attachments:
            field = attachment.get("type", "files")
            observed_attachment_types.add(field)
            mapped = {"photos": "photo", "videos": "video", "audio_files": "audio_attachment", "gifs": "gif", "files": "other_attachment"}.get(field, "other_attachment")
            attachment_items_by_role[role][mapped] += 1
            month_attachment_items[month][role][mapped] += 1
        raw = row.get("raw", {})
        has_share = isinstance(raw.get("share"), dict) or bool(links)
        if has_share:
            for reaction in raw.get("reactions", []) if isinstance(raw.get("reactions"), list) else []:
                if not isinstance(reaction, dict):
                    continue
                actor = reaction.get("actor")
                actor_role = role_map.get(actor, "unmapped") if isinstance(actor, str) else "unmapped"
                reactions_on_shared[actor_role] += 1
                total_shared_content_reactions += 1
    total_span_days = (max((x["local"].date() for x in rows)) - min((x["local"].date() for x in rows))).days + 1 if rows else 0
    def longest_streak(days: set[date]) -> dict[str, Any]:
        best = run = 0
        best_start = run_start = None
        previous = None
        for current in sorted(days):
            if previous is not None and current == previous + timedelta(days=1):
                run += 1
            else:
                run, run_start = 1, current
            if run > best:
                best, best_start = run, run_start
            previous = current
        return {"days": best, "start_date": best_start.isoformat() if best_start else None,
                "end_date": (best_start + timedelta(days=best - 1)).isoformat() if best_start and best else None}
    return {
        "type_counts_by_role": {role: dict(types_by_role[role]) for role in roles},
        "attachment_item_counts_by_role": {role: dict(attachment_items_by_role[role]) for role in roles},
        "attachment_items_by_month_and_role": {month: {role: dict(counts[role]) for role in roles} for month, counts in sorted(month_attachment_items.items())},
        "shared_link_candidates_by_role": {role: dict(link_candidates_by_role[role]) for role in roles},
        "shared_link_candidates_by_month_and_role": {month: {role: dict(counts[role]) for role in roles} for month, counts in sorted(month_links_by_role.items())},
        "reel_candidates_by_role": {role: link_candidates_by_role[role]["shared_reel_candidate"] for role in roles},
        "shared_post_candidates_by_role": {role: link_candidates_by_role[role]["shared_instagram_post_candidate"] for role in roles},
        "media_messages_by_month_and_role": {month: {role: dict(counts[role]) for role in roles} for month, counts in sorted(month_role.items())},
        "text_to_media_ratio_by_role": {role: {
            "text_messages": text_count[role],
            "media_messages": media_message_count[role],
            "text_messages_per_media_message": round(text_count[role] / media_message_count[role], 4) if media_message_count[role] else None,
            "media_messages_per_text_message": round(media_message_count[role] / text_count[role], 4) if text_count[role] else None,
        } for role in roles},
        "media_sharing_streak_by_role": {role: longest_streak(media_days_by_role[role]) for role in roles},
        "most_media_shared_in_one_day": {"media_message_count": max(media_count_day.values(), default=0), "dates": [day.isoformat() for day, count in sorted(media_count_day.items()) if count == max(media_count_day.values(), default=0)], "unit": "unique message rows containing at least one attachment or shared link"},
        "reaction_frequency_on_shared_content": {"reaction_count": total_shared_content_reactions, "by_reacting_role": {role: reactions_on_shared[role] for role in sorted(set(roles) | set(reactions_on_shared))},
                                                "definition": "Structured reaction records attached to rows with an Instagram share or shared-link reference. This does not imply the reaction targets the media rather than the message."},
        "definitions": {
            "reel_and_post_labels": "URL-path candidates from the parser, not verified media classifications; no URL alone is treated as verified Reel content.",
            "verified_media_content": "No linked media was opened or inspected; all link-based type labels are uncertain candidates.",
            "text_to_media_ratio": "Both directions are reported: text rows/media rows and media rows/text rows. Rows with both text and media are counted in both, so this is a volume ratio rather than mutually exclusive categories.",
            "audio_voice_note": "Audio attachment counts are available, but voice-note subtype is not identifiable in this export.",
            "stickers": "No sticker field exists in the inspected export; count is unavailable, not zero verified stickers.",
        },
        "unavailable": {
            "voice_note_count": None,
            "gif_attachment_count": sum(counts["gif"] for counts in attachment_items_by_role.values()) if "gifs" in observed_attachment_types else None,
            "sticker_count": None,
            "reason": "Audio file references do not distinguish voice notes; no GIF attachment field was observed; there is no sticker discriminator in this export.",
        },
    }


def couple_metrics(relationship: dict[str, Any], emojis: dict[str, Any], dynamics: dict[str, Any],
                   time_analysis: dict[str, Any], media: dict[str, Any]) -> dict[str, Any]:
    categories = relationship.get("categories", {})
    emoji_roles = emojis.get("message_emoji_statistics", {}).get("roles", {})
    hearts = {role: emoji_roles.get(role, {}).get("hearts", {}).get("total_uses", 0) for role in sorted(emoji_roles)}
    love_types = ["i_love_you", "affectionate_words", "pet_names"]
    return {
        "phrase_categories": categories,
        "affection_emoji_usage": {"heart_emoji_uses_by_role": hearts,
                                  "curated_romantic_emoji_uses_by_role": {role: emoji_roles[role].get("romantic_curated_set", {}).get("total_uses", 0) for role in emoji_roles},
                                  "definition": "Unicode emoji frequency from message text only; curated set includes hearts, kiss/love faces, couple symbols, flowers and rose."},
        "affectionate_phrase_trends_by_month": {month: {group: values for group, values in groups.items() if group in love_types} for month, groups in relationship.get("monthly_occurrences", {}).items()},
        "initiations_after_long_gaps": time_analysis.get("return_after_silence"),
        "interpretation_limit": "These are literal configured phrase and emoji counts. They do not measure emotions, intent, or relationship quality.",
    }


def wrapped_awards(conversation: dict[str, Any], time_analysis: dict[str, Any], language: dict[str, Any],
                   couple: dict[str, Any], media: dict[str, Any]) -> dict[str, Any]:
    role_ids = list(conversation.get("conversation_sessions", {}).get("ending_frequency_by_role", {}))
    def award(label: str, metric_by_role: dict[str, Any], explanation: str, *, lower_wins: bool = False, null_reason: str | None = None) -> dict[str, Any]:
        valid = {role: value for role, value in metric_by_role.items() if isinstance(value, (int, float))}
        if null_reason or len(valid) != len(role_ids) or not valid:
            winner, status = None, "unavailable" if not valid or null_reason else "insufficient_data"
        else:
            target = min(valid.values()) if lower_wins else max(valid.values())
            winners = [role for role, value in valid.items() if value == target]
            winner, status = (winners[0], "winner") if len(winners) == 1 else (None, "tie")
        return {"award": label, "winner": winner, "status": status, "statistic_by_role": metric_by_role, "explanation": explanation, "note": null_reason}

    burst = conversation["double_and_triple_texting"]["by_role"]
    replies = conversation["valid_reply_latency"]["by_responder"]
    max_chars = {role: row["character_count"] if row else None for role, row in conversation["message_lengths"]["longest_single_text_message_by_role"].items()}
    emoji_roles = media.get("_emoji_roles", {})
    return {
        "Night Owl": award("Night Owl", time_analysis["midnight_00_to_05_by_role"], "Most messages sent from 00:00 through 04:59 local time."),
        "Night Owl 2–5 AM": award("Night Owl 2–5 AM", time_analysis.get("night_owl_02_to_05_by_role", {}), "Most authored message rows sent from 02:00 through 04:59 local time; reaction events are excluded."),
        "Double Texter": award("Double Texter", {role: value["runs_of_2_plus"] for role, value in burst.items()}, "Most same-sender bursts of at least two consecutive rows."),
        "Speedster": award("Speedster", {role: replies.get(role, {}).get("average_seconds") for role in role_ids}, "Lowest average valid reply delay; only positive sender-switch comparisons count.", lower_wins=True, null_reason="No valid reply comparisons for both participants." if any(not replies.get(role, {}).get("count") for role in role_ids) else None),
        "Flash Trophy": award("Flash Trophy", {role: replies.get(role, {}).get("average_seconds") for role in role_ids}, "Lowest average valid reply delay; only positive sender-switch comparisons count.", lower_wins=True, null_reason="No valid reply comparisons for both participants." if any(not replies.get(role, {}).get("count") for role in role_ids) else None),
        "Essay Writer": award("Essay Writer", max_chars, "Longest single authored text message by trimmed character count."),
        "Yapper Medal": award("Yapper Medal", max_chars, "Longest single authored text message by trimmed character count."),
        "Emoji Addict": award("Emoji Addict", {role: emoji_roles.get(role, {}).get("emoji_uses_per_100_messages") for role in role_ids}, "Most message-text emoji sequences per 100 non-reaction conversation rows."),
        "Reel Dealer": award("Reel Dealer", {role: media.get("reel_candidates_by_role", {}).get(role) for role in role_ids}, "Most links whose visible path is a Reel candidate; content is unverified."),
        "Reel Minister": award("Reel Minister", {role: media.get("reel_candidates_by_role", {}).get(role) for role in role_ids}, "Most links whose visible path is a Reel candidate; content is unverified."),
        "Conversation Starter": award("Conversation Starter", conversation.get("conversation_initiations_by_role", {}), "Most sessions initiated after the configured inactivity gap."),
        "Simp of the Year": award("Simp of the Year", couple.get("phrase_categories", {}).get("compliments", {}).get("occurrences_by_role", {}), "Most configured compliment phrase hits in message text; keyword counts do not interpret emotional intent."),
        "Ghost": award("Ghost", {role: conversation.get("unanswered_final_turns_by_role", {}).get(role, 0) for role in role_ids}, "No winner: an unanswered turn cannot establish that someone intentionally ghosted.", null_reason="Intent cannot be inferred from message timing."),
        "Good Morning Person": award("Good Morning Person", couple.get("phrase_categories", {}).get("good_morning", {}).get("occurrences_by_role", {}), "Most literal matches to the configured good-morning phrase list."),
        "Yap Champion": award("Yap Champion", {role: language.get("total_words_by_role", {}).get(role) for role in role_ids}, "Most Unicode word tokens in authored text after confirmed spelling normalization."),
    }


def analyze(parsed: dict[str, Any], role_map: dict[str, str], gap_hours: float, existing_dynamics: dict[str, Any],
            relationship: dict[str, Any], emojis: dict[str, Any], normalization_rules: dict[str, list[str]],
            existing_language: dict[str, Any] | None = None, lexicon: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = _valid_rows(parsed, role_map)
    conversation = conversation_metrics(rows, role_map, gap_hours, existing_dynamics)
    timezone_name = parsed.get("summary", {}).get("timezone", "Asia/Kolkata")
    time_analysis = time_metrics(rows, role_map, gap_hours, timezone_name)
    language = language_metrics(rows, role_map, normalization_rules, lexicon)
    if existing_language:
        language["dictionary_language_estimates_by_role"] = {
            role: {
                "word_class_counts": existing_language.get("profiles", {}).get(role, {}).get("word_class_counts", {}),
                "message_class_counts": existing_language.get("profiles", {}).get(role, {}).get("message_language_class_counts", {}),
                "configured_slang_counts": existing_language.get("profiles", {}).get(role, {}).get("top_slang", []),
            }
            for role in role_map.values()
        }
        language["language_estimate_definition"] = existing_language.get("language_classification", {}).get("note")
    media = media_metrics(rows, role_map)
    # Give awards direct, role-keyed facts without duplicating their source sections.
    emoji_roles = emojis.get("message_emoji_statistics", {}).get("roles", {})
    media["_emoji_roles"] = emoji_roles
    total_words = Counter()
    for item in rows:
        if item["text"].strip():
            total_words[item["role"]] += len(WORD_RE.findall(item["text"]))
    # Keep the award payload small and remove internal calculation helpers below.
    language["total_words_by_role"] = {role: total_words[role] for role in role_map.values()}
    couple = couple_metrics(relationship, emojis, existing_dynamics, time_analysis, media)
    conversation["conversation_initiations_by_role"] = existing_dynamics.get("conversation_summary", {}).get("conversations_by_initiator", {})
    conversation["unanswered_final_turns_by_role"] = existing_dynamics.get("message_dynamics", {}).get("unanswered_final_turns_by_role", {})
    awards = wrapped_awards(conversation, time_analysis, language, couple, media)
    media.pop("_emoji_roles", None)
    language.pop("total_words_by_role", None)
    conversation.pop("conversation_initiations_by_role", None)
    conversation.pop("unanswered_final_turns_by_role", None)
    return {
        "advanced_conversation_dynamics": conversation,
        "couple_statistics": couple,
        "advanced_time_analysis": time_analysis,
        "advanced_language_analysis": language,
        "advanced_media_analysis": media,
        "wrapped_awards": awards,
        "data_quality": data_quality(parsed, rows, role_map),
    }


def data_quality(parsed: dict[str, Any], valid_rows: list[dict[str, Any]], role_map: dict[str, str]) -> dict[str, Any]:
    all_rows = parsed.get("messages", [])
    kinds = Counter(row.get("analysis_text_kind") or "empty_or_unclassified" for row in all_rows)
    missing_ts = sum(not row.get("timestamp_local") or row.get("timestamp_ms", row.get("raw", {}).get("timestamp_ms")) is None for row in all_rows)
    unsent_marker_true = sum(bool(row.get("raw", {}).get("is_unsent_image_by_messenger_kid_parent")) for row in all_rows)
    reaction_records = sum(len(row.get("raw", {}).get("reactions", [])) for row in all_rows if isinstance(row.get("raw", {}).get("reactions"), list))
    call_event_rows = sum(row.get("raw", {}).get("call_duration") is not None for row in all_rows)
    content_missing_or_empty = sum(not isinstance(row.get("raw", {}).get("content"), str) or not row.get("raw", {}).get("content", "").strip() for row in all_rows)
    raw_sender_names = {row.get("raw", {}).get("sender_name") for row in all_rows}
    return {
        "export_row_count": len(all_rows),
        "unique_export_row_count": parsed.get("summary", {}).get("unique_export_row_count", len(all_rows)),
        "exact_duplicate_rows_removed": parsed.get("summary", {}).get("exact_duplicates_removed", 0),
        "timestamped_non_reaction_rows_used": len(valid_rows),
        "invalid_or_missing_timestamp_rows": missing_ts,
        "analysis_text_kind_counts": dict(kinds),
        "raw_content_missing_or_empty_rows": content_missing_or_empty,
        "empty_or_unclassified_rows": kinds["empty_or_unclassified"],
        "attachment_notice_rows": kinds["attachment_notice"],
        "reaction_notice_rows_excluded_from_message_analytics": kinds["reaction_notice"],
        "unsent_image_marker_true_rows": unsent_marker_true,
        "unsent_media_rows_excluded_from_message_metrics": kinds["unsent_media"],
        "call_event_rows": call_event_rows,
        "structured_reaction_record_count": reaction_records,
        "source_files": parsed.get("summary", {}).get("files", []),
        "attachment_item_counts": parsed.get("summary", {}).get("attachment_item_counts", {}),
        "unmapped_sender_labels": sorted(str(sender) for sender in raw_sender_names if sender not in role_map),
        "media_binaries_available": False,
        "local_processing_only": True,
        "deleted_content_limit": "The export contains no reliable general deleted-message indicator; an absent/empty row does not establish deletion.",
        "message_handling": "Reaction notices and rows explicitly marked is_unsent_image_by_messenger_kid_parent are excluded from sent-message metrics. Attachment-only rows remain message turns for session/reply timing but are excluded from authored text/language metrics. Empty/system-like rows with timestamps remain conversation rows and are counted separately above.",
    }
