"""Create an aggregate-only frontend payload from the full private analytics."""

from __future__ import annotations

from typing import Any


def build_story_data(data: dict[str, Any]) -> dict[str, Any]:
    """Whitelist only presentation statistics; never copy messages or excerpts."""
    overview = data.get("overview", {})
    roles = overview.get("participants", {})
    initiation = data.get("initiation_and_replies", {})
    dynamics = data.get("advanced_conversation_dynamics", {})
    time_data = data.get("advanced_time_analysis", {})
    language = data.get("language_analysis", {})
    emoji = data.get("emoji_analysis", {}).get("message_emoji_statistics", {})
    media = data.get("media_analysis", {})
    advanced_media = data.get("advanced_media_analysis", {})
    relationship = data.get("relationship_statistics", {}).get("categories", {})
    awards = data.get("wrapped_awards", {})

    selected_categories = (
        "i_love_you", "good_morning", "good_night", "compliments", "appreciation",
        "pet_names", "apologies", "reassurance", "support", "affectionate_words",
    )
    role_profiles = language.get("profiles", {})
    presentation_roles = {**roles, "you": "Abhishek"}
    confession = data.get("confession_story", {})
    reel_link_candidates = media.get("reel_link_candidates", {})
    chat_time = time_data.get("approximate_chat_time", {})
    reel_candidate_count = reel_link_candidates.get("total")
    chat_window_hours = chat_time.get("total_elapsed_hours")
    reel_watch_assumption_seconds = 60
    if (
        isinstance(reel_candidate_count, (int, float)) and isinstance(chat_window_hours, (int, float))
        and reel_candidate_count >= 0 and chat_window_hours >= 0
    ):
        estimated_reel_hours = round(reel_candidate_count * reel_watch_assumption_seconds / 3600, 1)
        approximate_instagram_time = {
            "chat_window_hours": chat_window_hours,
            "reel_link_candidates": reel_candidate_count,
            "assumed_seconds_per_reel_link_candidate": reel_watch_assumption_seconds,
            "estimated_reel_hours": estimated_reel_hours,
            "total_hours": round(chat_window_hours + estimated_reel_hours, 1),
            "rounded_hours": round(chat_window_hours + estimated_reel_hours),
            "definition": "Approximate chat-window time plus an assumed 60 seconds for each Reel-link candidate. Reel links may not all be verified Reels or watched; actual watch time is unavailable.",
        }
    else:
        approximate_instagram_time = {}
    return {
        "schema_version": 1,
        "source_schema_version": data.get("schema_version"),
        "privacy": "Aggregate statistics only. No raw messages, timestamps per message, IDs, or memory excerpts are included.",
        "participants": presentation_roles,
        "confession_story": {
            key: confession.get(key)
            for key in (
                "status", "reason", "relationship_date", "next_date",
                "confession_prompt_at_local", "website_revealed_at_local", "website_surprise_at_local",
                "proposal_link_sent_at_local", "girlfriend_reply_at_local",
                "first_i_love_you_back_at_local", "no_button_surprise_at_local",
                "late_night_last_message_at_local", "messages_from_proposal_to_late_night",
                "messages_from_proposal_to_late_night_by_role", "seconds_from_proposal_to_late_night_end",
                "messages_by_date", "messages_by_role_and_date",
            )
            if key in confession
        },
        "overview": {
            "total_messages": overview.get("conversation_message_count"),
            "text_messages": overview.get("text_statistics", {}).get("nonempty_text_message_count"),
            "active_days": overview.get("active_calendar_dates"),
            "date_range": overview.get("export_date_range", {}),
            "most_active_day": overview.get("most_active_calendar_dates", []),
            "most_active_month": overview.get("most_active_months", []),
            "peak_messaging_hour": overview.get("peak_messaging_hours", []),
            "sessions": data.get("conversation_dynamics", {}).get("conversation_count"),
            "timezone": overview.get("timezone", "Asia/Kolkata"),
        },
        "participants_summary": {
            role: {
                "messages": overview.get("message_counts_by_role", {}).get(role),
                "average_text_length_characters": data.get("participants", {}).get(role, {}).get("average_text_length_characters"),
                "initiated_sessions": initiation.get("conversation_initiations", {}).get(role, {}).get("initiated_conversations"),
                "initiated_share_percent": initiation.get("conversation_initiations", {}).get(role, {}).get("share_of_conversations_percent"),
                "double_text_runs": dynamics.get("double_and_triple_texting", {}).get("by_role", {}).get(role, {}).get("runs_of_2_plus"),
                "triple_text_runs": dynamics.get("double_and_triple_texting", {}).get("by_role", {}).get(role, {}).get("runs_of_3_plus"),
                "maximum_consecutive_messages": dynamics.get("consecutive_message_bursts", {}).get("maximum_run_length_by_role", {}).get(role),
                "one_word_messages": initiation.get("message_turn_metrics", {}).get("one_word_messages_by_role", {}).get(role),
                "question_messages": initiation.get("message_turn_metrics", {}).get("question_messages_by_role", {}).get(role),
                "question_marks": initiation.get("message_turn_metrics", {}).get("question_mark_count_by_role", {}).get(role),
                "longest_message_characters": dynamics.get("message_lengths", {}).get("longest_single_text_message_by_role", {}).get(role, {}).get("character_count"),
                "average_message_length_characters": dynamics.get("message_lengths", {}).get("average_text_length_characters_by_role", {}).get(role),
                "total_words": role_profiles.get(role, {}).get("total_word_count"),
                "average_words_per_message": role_profiles.get(role, {}).get("average_words_per_message"),
                "top_meaningful_words": role_profiles.get(role, {}).get("top_meaningful_words", [])[:6],
                "top_bigrams": role_profiles.get(role, {}).get("top_bigrams", [])[:5],
                "top_trigrams": role_profiles.get(role, {}).get("top_trigrams", [])[:4],
                "top_emojis": emoji.get("roles", {}).get(role, {}).get("top_10", [])[:5],
                "emoji_uses": emoji.get("roles", {}).get(role, {}).get("emoji_uses_in_messages"),
                "emoji_rate_per_100_messages": emoji.get("roles", {}).get(role, {}).get("emoji_uses_per_100_messages"),
                "midnight_messages": time_data.get("midnight_00_to_05_by_role", {}).get(role),
                "working_hours_messages": time_data.get("working_hours_09_to_17_by_role", {}).get(role),
                "heart_emoji_uses": emoji.get("roles", {}).get(role, {}).get("hearts", {}).get("total_uses"),
                "top_heart_emoji": (emoji.get("roles", {}).get(role, {}).get("hearts", {}).get("most_used") or [{}])[0].get("emoji"),
                "reel_link_candidates": advanced_media.get("reel_candidates_by_role", {}).get(role),
                "shared_post_candidates": advanced_media.get("shared_post_candidates_by_role", {}).get(role),
                "external_link_candidates": advanced_media.get("shared_link_candidates_by_role", {}).get(role, {}).get("external_link", 0),
                "attachment_items": media.get("by_role", {}).get(role, {}).get("attachment_item_counts", {}),
                "median_reply_seconds": initiation.get("reply_times", {}).get("by_responder", {}).get(role, {}).get("median_seconds"),
                "average_valid_reply_seconds": dynamics.get("valid_reply_latency", {}).get("by_responder", {}).get(role, {}).get("average_seconds"),
                "good_morning_occurrences": relationship.get("good_morning", {}).get("occurrences_by_role", {}).get(role),
                "good_night_occurrences": relationship.get("good_night", {}).get("occurrences_by_role", {}).get(role),
                "compliment_occurrences": relationship.get("compliments", {}).get("occurrences_by_role", {}).get(role),
            }
            for role in roles
        },
        "reply": {
            "median_seconds_by_responder": {role: initiation.get("reply_times", {}).get("by_responder", {}).get(role, {}).get("median_seconds") for role in roles},
            "average_seconds_by_responder": {role: dynamics.get("valid_reply_latency", {}).get("by_responder", {}).get(role, {}).get("average_seconds") for role in roles},
            "fastest_valid_reply": dynamics.get("valid_reply_latency", {}).get("fastest"),
            "slowest_valid_reply": dynamics.get("valid_reply_latency", {}).get("slowest"),
            "valid_reply_count": dynamics.get("valid_reply_latency", {}).get("valid_reply_count"),
            "delay_buckets_by_responder": dynamics.get("valid_reply_latency", {}).get("delay_buckets_by_responder", {}),
        },
        "language": {
            "shared_vocabulary": language.get("shared_vocabulary", {}),
            "message_language_estimates": language.get("language_classification", {}).get("combined_message_classes", {}),
        },
        "emoji": {
            "combined_top_10": emoji.get("combined_top_10", [])[:10],
            "combined_uses": emoji.get("combined_uses"),
            "top_adjacent_combinations": emoji.get("top_adjacent_emoji_combinations", [])[:5],
            "comparison": emoji.get("comparison", {}),
        },
        "media": {
            "reel_link_candidates": media.get("reel_link_candidates", {}),
            "shared_link_types": media.get("shared_link_types", {}),
            "attachment_item_counts": media.get("attachment_item_counts", {}),
            "reactions_on_shared_content": advanced_media.get("reaction_frequency_on_shared_content", {}).get("reaction_count"),
            "unavailable": advanced_media.get("unavailable", {}),
            "candidate_note": advanced_media.get("definitions", {}).get("verified_media_content"),
        },
        "relationship": {
            "phrase_categories": {
                key: {
                    "occurrences_by_role": relationship.get(key, {}).get("occurrences_by_role", {}),
                    "messages_by_role": relationship.get(key, {}).get("messages_containing_phrase_by_role", {}),
                }
                for key in selected_categories
                if key in relationship
            },
            "monthly_affectionate_phrases": data.get("couple_statistics", {}).get("affectionate_phrase_trends_by_month", {}),
        },
        "time": {
            "night_owl_02_to_05_by_role": time_data.get("night_owl_02_to_05_by_role", {}),
            "most_active_30_minute_clock_windows": time_data.get("most_active_30_minute_clock_windows", {}),
            "most_active_consecutive_3_day_period": time_data.get("most_active_consecutive_3_day_period"),
            "most_active_consecutive_7_day_period": time_data.get("most_active_consecutive_7_day_period"),
            "daily_consistency_by_role": time_data.get("daily_messaging_consistency_by_role", {}),
            "approximate_chat_time": time_data.get("approximate_chat_time", {}),
            "approximate_instagram_time": approximate_instagram_time,
        },
        "awards": {
            key: {
                "winner": value.get("winner"), "status": value.get("status"),
                "statistic_by_role": value.get("statistic_by_role"),
                "explanation": value.get("explanation"), "note": value.get("note"),
            }
            for key, value in awards.items()
        },
        "method_notes": {
            "sessions": data.get("advanced_conversation_dynamics", {}).get("conversation_sessions", {}).get("definition"),
            "reply_time": data.get("advanced_conversation_dynamics", {}).get("valid_reply_latency", {}).get("definition"),
            "phrases": data.get("relationship_statistics", {}).get("definitions", {}).get("phrase_counts"),
            "media_candidates": advanced_media.get("definitions", {}).get("reel_and_post_labels"),
        },
    }
