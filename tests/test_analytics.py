from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import advanced_metrics, conversation_analysis, emoji_analysis, media_analysis, parser, relationship_analysis, story_data
from backend.text_utils import normalize_text


class ParserTests(unittest.TestCase):
    def test_normalization_applies_only_configured_aliases_and_keeps_punctuation(self):
        text, words = normalize_text("Yrr, nhi hu!", {
            "yaar": ["yrr"], "nahi": ["nhi"], "hoon": ["hu"]
        })
        self.assertEqual(text, "yaar, nahi hoon!")
        self.assertEqual(words, ["yaar", "nahi", "hoon"])

    def test_parse_files_deduplicates_exact_rows_and_uses_local_timezone(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = {"sender_name": "A", "timestamp_ms": 0, "content": "hi"}
            for name in ("message_1.json", "message_2.json"):
                (root / name).write_text(json.dumps({"participants": [], "messages": [row]}), encoding="utf-8")
            rows, summary = parser.parse_files(list(root.glob("*.json")), "Asia/Kolkata", {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(summary["exact_duplicates_removed"], 1)
        self.assertEqual(rows[0]["timestamp_local"], "1970-01-01T05:30:00.000+05:30")
        self.assertEqual(rows[0]["analysis_text"], "hi")

    def test_explicit_unsent_media_marker_is_preserved_but_not_counted_as_sent(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "message_1.json"
            path.write_text(json.dumps({"messages": [{
                "sender_name": "A", "timestamp_ms": 0, "content": "Sent an attachment",
                "is_unsent_image_by_messenger_kid_parent": True,
            }]}), encoding="utf-8")
            rows, summary = parser.parse_files([path], "Asia/Kolkata", {})
        self.assertEqual(rows[0]["analysis_text_kind"], "unsent_media")
        self.assertEqual(rows[0]["message_type"], "unsent_media_event")
        self.assertEqual(summary["conversation_message_count"], 0)


class EmojiAndMediaTests(unittest.TestCase):
    def test_unicode_emoji_sequences_preserve_zwj_tone_flag_and_keycap(self):
        self.assertEqual(
            emoji_analysis.extract_emojis("❤️ 👩🏽‍💻 🇮🇳 1️⃣"),
            ["❤️", "👩🏽‍💻", "🇮🇳", "1️⃣"],
        )

    def test_media_candidate_classification(self):
        types = media_analysis.classify_types({
            "shared_links": [{"candidate_type": "shared_reel_candidate"}],
            "attachments": [{"type": "photos"}],
            "analysis_text_kind": "message_text",
        })
        self.assertEqual(types, ["shared_reel_candidate", "photo", "text"])
        self.assertEqual(media_analysis.primary_type(types), "shared_reel_candidate")


class ConversationTests(unittest.TestCase):
    def test_gap_boundary_and_reply_metrics(self):
        from datetime import datetime, timezone

        base = 1_000_000
        def message(offset_hours: float, role: str):
            stamp = base + int(offset_hours * 3_600_000)
            local = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc)
            return {"timestamp_ms": stamp, "timestamp_local": local, "role": role, "sender_name": role,
                    "category": "text", "message_id": role + str(offset_hours), "text": "hi", "words": ["hi"]}

        messages = [message(0, "you"), message(1, "her"), message(9.01, "you")]
        sessions = conversation_analysis.split_sessions(messages, 8)
        self.assertEqual([len(session) for session in sessions], [2, 1])
        replies, _ = conversation_analysis.reply_and_double_text_stats(sessions, ["you", "her"])
        self.assertEqual(replies["by_responder"]["her"]["reply_count"], 1)
        self.assertEqual(replies["by_responder"]["her"]["average_seconds"], 3600)

    def test_emoji_message_denominator_excludes_reaction_notice_rows(self):
        parsed = {"messages": [
            {"analysis_text_kind": "message_text", "timestamp_local": "2026-01-01T00:00:00+05:30",
             "raw": {"sender_name": "A", "content": "hi ❤️"}},
            {"analysis_text_kind": "reaction_notice", "timestamp_local": "2026-01-01T00:00:01+05:30",
             "raw": {"sender_name": "A", "content": "Reacted ❤️ to your message"}},
        ]}
        result = emoji_analysis.analyze(parsed, {"A": "you"})
        stats = result["message_emoji_statistics"]["roles"]["you"]
        self.assertEqual(stats["messages_total"], 1)
        self.assertEqual(stats["message_emoji_rate_percent"], 100)
        self.assertEqual(result["reaction_emoji_statistics"]["combined_reaction_count"], 0)


class RelationshipTests(unittest.TestCase):
    def test_phrase_metrics_preserve_roles_and_months(self):
        parsed = {"messages": [{
            "analysis_text_kind": "message_text", "analysis_text": "Good night jaan",
            "sender": "A", "timestamp_local": "2026-09-09T22:00:00+05:30", "raw": {"sender_name": "A"},
        }]}
        result = relationship_analysis.analyze(
            parsed, {"A": "you", "B": "her"},
            {"greetings": {"good_morning": [], "good_night": ["good night"]},
             "i_love_you_phrases": [], "compliment_phrases": [], "apology_phrases": [],
             "pet_names": ["jaan"], "support_phrases": [], "affectionate_words": []},
        )
        self.assertEqual(result["categories"]["good_night"]["occurrences_by_role"]["you"], 1)
        self.assertEqual(result["monthly_occurrences"]["2026-09"]["good_night"]["you"], 1)


class AdvancedMetricsTests(unittest.TestCase):
    def _row(self, role: str, stamp: int, text: str = "", **extra):
        return {
            "id": f"{role}-{stamp}", "sender": role, "timestamp_ms": stamp,
            "timestamp_local": __import__("datetime").datetime.fromtimestamp(stamp / 1000, __import__("datetime").timezone(__import__("datetime").timedelta(hours=5, minutes=30))).isoformat(),
            "analysis_text_kind": "message_text" if text else None, "analysis_text": text,
            "raw": {"sender_name": role, "timestamp_ms": stamp, "content": text, **extra},
            "attachments": [], "shared_links": [],
        }

    def test_burst_counts_and_valid_reply_buckets(self):
        base = 1_800_000_000_000
        parsed = {"messages": [
            self._row("A", base, "one?"), self._row("A", base + 10_000, "two"),
            self._row("A", base + 20_000, "three"), self._row("B", base + 40_000, "reply"),
        ]}
        roles = {"A": "you", "B": "her"}
        dynamic = {"conversation_summary": {"longest_by_duration": []}, "message_dynamics": {"question_mark_count_by_role": {"you": 1}}}
        result = advanced_metrics.analyze(parsed, roles, 8, dynamic, {}, {}, {})
        conv = result["advanced_conversation_dynamics"]
        self.assertEqual(conv["double_and_triple_texting"]["by_role"]["you"]["runs_of_3_plus"], 1)
        self.assertEqual(conv["conversation_sessions"]["average_messages_per_session"], 4)
        self.assertEqual(conv["valid_reply_latency"]["delay_buckets_by_responder"]["her"]["under_1_minute"], 1)
        self.assertEqual(conv["valid_reply_latency"]["valid_reply_count"], 1)

    def test_same_timestamp_reply_is_excluded_and_short_export_has_no_7_day_award_window(self):
        base = 1_800_000_000_000
        parsed = {"summary": {"timezone": "Asia/Kolkata"}, "messages": [
            self._row("A", base, "hi"), self._row("B", base, "hello"),
            self._row("A", base + 24 * 3_600_000, "back"),
        ]}
        roles = {"A": "you", "B": "her"}
        result = advanced_metrics.analyze(parsed, roles, 8, {"conversation_summary": {"longest_by_duration": []}}, {}, {}, {})
        self.assertEqual(result["advanced_conversation_dynamics"]["valid_reply_latency"]["valid_reply_count"], 0)
        self.assertEqual(result["advanced_time_analysis"]["most_active_consecutive_7_day_period"]["status"], "insufficient_export_span")
        self.assertEqual(result["advanced_time_analysis"]["timezone"], "Asia/Kolkata")

    def test_shared_content_reactions_are_counted_by_actor(self):
        row = self._row("A", 1_800_000_000_000, "check this", share={"link": "https://www.instagram.com/reel/abc"})
        row["shared_links"] = [{"candidate_type": "shared_reel_candidate"}]
        row["raw"]["reactions"] = [{"actor": "B", "reaction": "❤️"}]
        result = advanced_metrics.media_metrics(advanced_metrics._valid_rows({"messages": [row]}, {"A": "you", "B": "her"}), {"A": "you", "B": "her"})
        self.assertEqual(result["reaction_frequency_on_shared_content"]["by_reacting_role"]["her"], 1)
        self.assertEqual(result["reel_candidates_by_role"]["you"], 1)

    def test_rolling_activity_window_and_daily_consistency(self):
        from datetime import datetime, timedelta, timezone

        start = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        rows = []
        for day, amount in enumerate((1, 2, 3)):
            for index in range(amount):
                local = start + timedelta(days=day, minutes=index)
                stamp = int(local.timestamp() * 1000)
                rows.append({"id": str(stamp), "sender": "A", "timestamp_ms": stamp,
                             "timestamp_local": local.isoformat(), "analysis_text_kind": "message_text",
                             "analysis_text": "hi", "raw": {"sender_name": "A", "timestamp_ms": stamp},
                             "attachments": [], "shared_links": []})
        result = advanced_metrics.time_metrics(advanced_metrics._valid_rows({"messages": rows}, {"A": "you"}), {"A": "you"}, 8)
        self.assertEqual(result["most_active_consecutive_3_day_period"]["message_count"], 6)
        self.assertEqual(result["daily_messaging_consistency_by_role"]["you"]["active_date_percent"], 100)

    def test_normalized_opening_words_caps_and_repeated_sentences(self):
        first = self._row("A", 1_800_000_000_000, "Yrr kya hai?")
        first["normalized_text"] = "yaar kya hai?"
        second = self._row("A", 1_800_000_001_000, "Yrr kya hai?")
        second["normalized_text"] = "yaar kya hai?"
        caps = self._row("B", 1_800_000_002_000, "HAHA!")
        caps["normalized_text"] = "haha!"
        rows = advanced_metrics._valid_rows({"messages": [first, second, caps]}, {"A": "you", "B": "her"})
        result = advanced_metrics.language_metrics(rows, {"A": "you", "B": "her"}, {"yaar": ["yrr"]})
        self.assertEqual(result["by_role"]["you"]["most_common_opening_words"][0]["word"], "yaar")
        self.assertEqual(result["by_role"]["you"]["most_repeated_sentences"][0]["count"], 2)
        self.assertEqual(result["by_role"]["her"]["punctuation_and_caps"]["all_caps_messages"], 1)

    def test_ghost_award_never_claims_intent(self):
        parsed = {"summary": {"timezone": "Asia/Kolkata"}, "messages": [self._row("A", 1_800_000_000_000, "hello")]}
        roles = {"A": "you", "B": "her"}
        dynamic = {"conversation_summary": {"longest_by_duration": [], "longest_by_message_count": [], "conversations_by_initiator": {"you": 1, "her": 0}},
                   "message_dynamics": {"question_mark_count_by_role": {}, "question_messages_by_role": {}, "unanswered_final_turns_by_role": {"you": 0, "her": 0}}}
        result = advanced_metrics.analyze(parsed, roles, 8, dynamic, {"categories": {}}, {}, {})
        self.assertIsNone(result["wrapped_awards"]["Ghost"]["winner"])
        self.assertIn("cannot establish", result["wrapped_awards"]["Ghost"]["explanation"])

    def test_story_payload_whitelists_aggregates_and_omits_private_excerpts(self):
        source = {
            "schema_version": 2,
            "overview": {"participants": {"you": "A", "her": "B"}, "conversation_message_count": 7},
            "memory_discovery": {"romantic_or_affectionate_messages": {"shortlist": [{"original_text": "PRIVATE_SENTINEL"}]}},
            "advanced_language_analysis": {"by_role": {"you": {"most_repeated_sentences": [{"sentence": "PRIVATE_SENTINEL"}]}}},
        }
        payload = story_data.build_story_data(source)
        import json
        encoded = json.dumps(payload)
        self.assertNotIn("PRIVATE_SENTINEL", encoded)
        self.assertIn("No raw messages", payload["privacy"])
        self.assertEqual(payload["overview"]["total_messages"], 7)


if __name__ == "__main__":
    unittest.main()
