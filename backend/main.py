"""Run the local extraction pipeline and write one Wrapped-ready JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from . import advanced_metrics, analyzer, conversation_analysis, emoji_analysis, language_analyzer
    from . import confession_analysis, media_analysis, memory_finder, relationship_analysis, story_data, timeline_analysis
except ImportError:
    import advanced_metrics, analyzer, conversation_analysis, emoji_analysis, language_analyzer
    import confession_analysis, media_analysis, memory_finder, relationship_analysis, story_data, timeline_analysis


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PARSED = ROOT / "output/parsed_export.json"
DEFAULT_OUTPUT = ROOT / "output/wrapped_data.json"


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def analyze(parsed: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    roles = read_json(root / "data/processed/sender_roles.json")
    rules = read_json(root / "data/processed/normalization_rules.json")
    lexicon = read_json(root / "data/processed/language_lexicon.json")
    config = read_json(root / "data/processed/analysis_config.json")
    milestones = read_json(root / "data/processed/milestones.json")
    approved_memories = read_json(root / "data/processed/approved_memories.json")
    gap_hours = float(config.get("conversation_gap_hours", 8))

    # Add concise type labels to each parsed row while keeping every raw item.
    for row in parsed.get("messages", []):
        types = media_analysis.classify_types(row)
        row["message_types"] = types
        row["primary_message_type"] = media_analysis.primary_type(types)

    basic = analyzer.analyze(parsed, roles)
    dynamics = conversation_analysis.analyze(parsed, roles, gap_hours)
    language = language_analyzer.analyze(parsed, roles, rules, lexicon)
    emojis = emoji_analysis.analyze(parsed, roles)
    media = media_analysis.analyze(parsed, roles)
    relationship = relationship_analysis.analyze(parsed, roles, lexicon)
    timeline = timeline_analysis.analyze(parsed, roles, rules, milestones)
    memories = memory_finder.analyze(parsed, roles, rules, approved_memories)
    advanced = advanced_metrics.analyze(parsed, roles, gap_hours, dynamics, relationship, emojis, rules, language, lexicon)

    monthly: dict[str, Any] = {}
    for month, count in dynamics["activity"]["messages_by_month"].items():
        monthly[month] = {
            "conversation_message_count": count,
            "conversation_messages_by_role": dynamics["activity"]["messages_by_month_and_role"].get(month, {}),
        }
    for month, profile in dynamics["reply_times"]["by_month"].items():
        monthly.setdefault(month, {})["reply_times"] = profile
    for month, profile in language["monthly_language_usage"].items():
        monthly.setdefault(month, {})["language"] = profile
    for month, profile in emojis["message_emoji_statistics"]["by_month"].items():
        monthly.setdefault(month, {})["emojis"] = profile
    for month, profile in media["messages_by_month_and_type"].items():
        monthly.setdefault(month, {})["message_types"] = profile
    for month in sorted(monthly):
        monthly[month].setdefault("conversation_message_count", 0)

    return {
        "schema_version": 2,
        "generated_from": "local Instagram JSON export",
        "overview": {
            "timezone": parsed.get("summary", {}).get("timezone", config.get("timezone", "Asia/Kolkata")),
            "participants": {role: sender for sender, role in roles.items()},
            "total_export_rows": parsed.get("summary", {}).get("unique_export_row_count", len(parsed.get("messages", []))),
            "conversation_message_count": dynamics["conversation_message_count"],
            "reaction_notice_rows": dynamics["reaction_notice_rows_excluded_from_message_metrics"],
            "message_counts_by_role": dynamics["messages_by_role"],
            "first_message": basic["first_message"],
            "last_message_local": parsed.get("summary", {}).get("last_message_local"),
            "export_date_range": {
                "first_local": parsed.get("summary", {}).get("first_message_local"),
                "last_local": parsed.get("summary", {}).get("last_message_local"),
            },
            "text_statistics": basic["text_statistics"],
            "session_gap_hours": gap_hours,
            "active_calendar_dates": dynamics["activity"]["active_calendar_dates"],
            "most_active_calendar_dates": dynamics["activity"]["most_active_calendar_dates"],
            "most_active_months": basic["activity"].get("most_active_months", []),
            "peak_messaging_hours": basic["activity"]["peak_messaging_hours"],
        },
        "participants": basic["role_statistics"],
        "conversation_dynamics": dynamics["conversation_summary"],
        "initiation_and_replies": {
            "conversation_initiations": dynamics["conversation_summary"]["by_role"],
            "reply_times": dynamics["reply_times"],
            "double_texting": dynamics["double_texting"],
            "message_turn_metrics": dynamics["message_dynamics"],
            "first_conversation_message": dynamics["first_conversation_message"],
        },
        "time_activity": dynamics["activity"],
        "language_analysis": language,
        "emoji_analysis": emojis,
        "media_analysis": media,
        "relationship_statistics": relationship,
        "timeline": timeline["timeline"],
        "confession_story": confession_analysis.analyze(parsed, roles, milestones),
        "before_after_comparison": timeline["before_after_comparison"],
        "memory_discovery": memories,
        "monthly_trends": monthly,
        "sentiment_analysis": {
            "status": "not_calculated",
            "reason": "No locally validated Hinglish and sarcasm-aware sentiment model is configured. Dictionary sentiment would be misleading for this conversation.",
        },
        "data_quality_and_limits": {
            "exact_duplicate_rows_removed": parsed.get("summary", {}).get("exact_duplicates_removed", 0),
            "attachment_item_counts": parsed.get("summary", {}).get("attachment_item_counts", {}),
            "shared_content_message_count": parsed.get("summary", {}).get("shared_content_message_count", 0),
            "unmapped_sender_names": basic["unmapped_sender_names"],
            "message_types_and_urls_are_candidates": True,
            "media_binaries_included": False,
            "source_export_untouched": True,
        },
        **advanced,
        "definitions": {
            "session": dynamics["definitions"]["conversation_session"],
            "reply_time": dynamics["definitions"]["reply_time"],
            "normalization": language["method"]["spelling_normalization"],
            "emoji_sources": "Message emoji and reaction emoji counts are separate.",
            "media_candidates": media["definitions"]["link_types"],
            "relationship_phrases": relationship["definitions"]["phrase_counts"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_PARSED), help="Parsed export JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Consolidated analytics JSON path")
    args = parser.parse_args()
    parsed = read_json(Path(args.input))
    wrapped = analyze(parsed)
    output_path = Path(args.output)
    write_json(output_path, wrapped)
    story_path = ROOT / "frontend/wrapped_story_data.json"
    write_json(story_path, story_data.build_story_data(wrapped))
    print(json.dumps({
        "output": str(output_path),
        "frontend_safe_output": str(story_path),
        "conversation_message_count": wrapped["overview"]["conversation_message_count"],
        "total_export_rows": wrapped["overview"]["total_export_rows"],
        "session_gap_hours": wrapped["overview"]["session_gap_hours"],
        "monthly_trend_count": len(wrapped["monthly_trends"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
