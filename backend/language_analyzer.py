"""Profile Hinglish word forms with reviewable, user-confirmed normalization."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("output/parsed_export.json")
DEFAULT_ROLES = Path("data/processed/sender_roles.json")
DEFAULT_RULES = Path("data/processed/normalization_rules.json")
DEFAULT_LEXICON = Path("data/processed/language_lexicon.json")
DEFAULT_OUTPUT = Path("output/language_profile.json")
TOKEN_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)

# Suggestions are deliberately review-only. Similar spellings are not merged
# until a person confirms that they have the same meaning in this conversation.
VARIANT_GROUPS = {
    "achha": {
        "forms": ["achha", "accha", "acha"],
        "note": "Likely spelling variants; confirm against the chat context.",
    },
    "yaar": {
        "forms": ["yaar", "yrr"],
        "note": "yrr has not been confirmed as a spelling variant.",
    },
    "hoon": {
        "forms": ["hoon", "hun", "hu"],
        "note": "hu and hun can have other readings; confirm before merging.",
    },
}


def top(counter: Counter[tuple[str, ...]], limit: int) -> list[dict[str, Any]]:
    return [
        {"phrase": " ".join(phrase), "count": count}
        for phrase, count in counter.most_common(limit)
    ]


def analyze(
    parsed: dict[str, Any],
    role_map: dict[str, str],
    normalization_rules: dict[str, list[str]],
    lexicon: dict[str, Any] | None = None,
    top_word_count: int = 100,
    top_phrase_count: int = 50,
) -> dict[str, Any]:
    lexicon = lexicon or {}
    rows = parsed.get("messages")
    if not isinstance(rows, list):
        raise ValueError("Parsed export must contain a messages list")

    raw_ngrams: dict[str, Counter[tuple[str, ...]]] = defaultdict(Counter)
    normalized_ngrams: dict[str, Counter[tuple[str, ...]]] = defaultdict(Counter)
    raw_words: dict[str, Counter[str]] = defaultdict(Counter)
    normalized_words: dict[str, Counter[str]] = defaultdict(Counter)
    tokens_seen: set[str] = set()
    usable_messages: Counter[str] = Counter()
    words_by_owner: Counter[str] = Counter()
    word_classes: dict[str, Counter[str]] = defaultdict(Counter)
    slang_counts: dict[str, Counter[str]] = defaultdict(Counter)
    affectionate_counts: dict[str, Counter[str]] = defaultdict(Counter)
    filler_counts: dict[str, Counter[str]] = defaultdict(Counter)
    message_language_classes: Counter[str] = Counter()
    message_classes_by_owner: dict[str, Counter[str]] = defaultdict(Counter)
    monthly_word_counts: dict[str, Counter[str]] = defaultdict(Counter)
    monthly_word_totals: Counter[str] = Counter()
    monthly_classes: dict[str, Counter[str]] = defaultdict(Counter)
    monthly_message_totals: Counter[str] = Counter()
    canonical_forms: dict[str, str] = {}
    hindi_words = {word.casefold() for word in lexicon.get("hindi_hinglish_words", [])}
    english_words = {word.casefold() for word in lexicon.get("english_words", [])}
    slang_words = {word.casefold() for word in lexicon.get("slang_words", [])}
    affectionate_words = {word.casefold() for word in lexicon.get("affectionate_words", [])}
    stopwords = {word.casefold() for word in lexicon.get("english_stopwords", [])}
    stopwords.update(word.casefold() for word in lexicon.get("hindi_stopwords", []))
    for canonical, forms in normalization_rules.items():
        for form in [canonical, *forms]:
            form = form.casefold()
            if form in canonical_forms and canonical_forms[form] != canonical:
                raise ValueError(f"Normalization form {form!r} appears in more than one group")
            canonical_forms[form] = canonical.casefold()

    for row in rows:
        raw = row.get("raw", {})
        if row.get("analysis_text_kind", "message_text") != "message_text":
            continue
        content = row.get("analysis_text", raw.get("content"))
        if not isinstance(content, str) or not content.strip():
            continue
        sender = raw.get("sender_name")
        owner = role_map.get(sender, "unmapped") if isinstance(sender, str) else "unmapped"
        tokens = [token.casefold() for token in TOKEN_PATTERN.findall(content)]
        if not tokens:
            continue
        normalized_tokens = [canonical_forms.get(token, token) for token in tokens]
        usable_messages[owner] += 1
        words_by_owner[owner] += len(normalized_tokens)
        words_by_owner["combined"] += len(normalized_tokens)
        raw_words[owner].update(tokens)
        raw_words["combined"].update(tokens)
        normalized_words[owner].update(normalized_tokens)
        normalized_words["combined"].update(normalized_tokens)
        tokens_seen.update(tokens)
        month = (row.get("timestamp_local") or "")[:7]
        if month:
            monthly_message_totals[month] += 1
            monthly_word_totals[month] += len(normalized_tokens)
            monthly_word_counts[month].update(normalized_tokens)

        has_hindi = False
        has_english = False
        for token in normalized_tokens:
            if token in hindi_words:
                word_classes[owner]["hindi_hinglish"] += 1
                word_classes["combined"]["hindi_hinglish"] += 1
                has_hindi = True
                if month:
                    monthly_classes[month]["hindi_hinglish"] += 1
            elif token in english_words:
                word_classes[owner]["english"] += 1
                word_classes["combined"]["english"] += 1
                has_english = True
                if month:
                    monthly_classes[month]["english"] += 1
            else:
                word_classes[owner]["unclassified"] += 1
                word_classes["combined"]["unclassified"] += 1
                if month:
                    monthly_classes[month]["unclassified"] += 1
            if token in slang_words:
                slang_counts[owner][token] += 1
                slang_counts["combined"][token] += 1
            if token in affectionate_words:
                affectionate_counts[owner][token] += 1
                affectionate_counts["combined"][token] += 1
            if token in stopwords:
                filler_counts[owner][token] += 1
                filler_counts["combined"][token] += 1
        message_language = "hinglish_mixed" if has_hindi and has_english else "hinglish_or_hindi" if has_hindi else "english" if has_english else "unclassified"
        message_language_classes[message_language] += 1
        message_classes_by_owner[owner][message_language] += 1

        if month:
            monthly_classes[month][f"messages_{message_language}"] += 1
        for size in (2, 3):
            for index in range(len(tokens) - size + 1):
                raw_phrase = tuple(tokens[index:index + size])
                normalized_phrase = tuple(normalized_tokens[index:index + size])
                raw_ngrams[owner][raw_phrase] += 1
                raw_ngrams["combined"][raw_phrase] += 1
                normalized_ngrams[owner][normalized_phrase] += 1
                normalized_ngrams["combined"][normalized_phrase] += 1

    candidate_groups = []
    for canonical, group in VARIANT_GROUPS.items():
        # Already-approved aliases should not reappear as requests for review.
        observed = [
            form for form in group["forms"]
            if form in tokens_seen and (form == canonical or form not in canonical_forms)
        ]
        if len(observed) > 1:
            candidate_groups.append({
                "suggested_canonical_form": canonical,
                "observed_forms": [
                    {"form": form, "combined_count": raw_words["combined"][form]}
                    for form in observed
                ],
                "auto_merged": False,
                "review_note": group["note"],
            })

    owners = sorted(owner for owner in raw_words if owner != "combined")

    def build_profiles(word_counts: dict[str, Counter[str]], ngram_counts: dict[str, Counter[tuple[str, ...]]]) -> dict[str, Any]:
        output = {}
        for owner in ["combined", *owners]:
            token_counter = Counter({(word,): count for word, count in word_counts[owner].items()})
            meaningful_counter = Counter({(word,): count for word, count in word_counts[owner].items() if word not in stopwords})
            english_counter = Counter({(word,): count for word, count in word_counts[owner].items() if word in english_words})
            hindi_counter = Counter({(word,): count for word, count in word_counts[owner].items() if word in hindi_words})
            output[owner] = {
                "messages_with_words": usable_messages[owner] if owner != "combined" else sum(usable_messages.values()),
                "total_word_count": words_by_owner[owner],
                "average_words_per_message": round(words_by_owner[owner] / usable_messages[owner], 2) if usable_messages[owner] else None,
                "top_words": top(token_counter, top_word_count),
                "top_20_words": top(token_counter, 20),
                "top_meaningful_words": top(meaningful_counter, 50),
                "top_hindi_hinglish_words": top(hindi_counter, 50),
                "top_english_words": top(english_counter, 50),
                "top_slang": top(Counter({(word,): count for word, count in slang_counts[owner].items()}), 30),
                "top_affectionate_words": top(Counter({(word,): count for word, count in affectionate_counts[owner].items()}), 30),
                "filler_word_counts": dict(filler_counts[owner].most_common(100)),
                "word_class_counts": dict(word_classes[owner]),
                "message_language_class_counts": dict(message_classes_by_owner[owner]),
                "top_bigrams": top(Counter({phrase: count for phrase, count in ngram_counts[owner].items() if len(phrase) == 2}), top_phrase_count),
                "top_trigrams": top(Counter({phrase: count for phrase, count in ngram_counts[owner].items() if len(phrase) == 3}), top_phrase_count),
            }
        return output

    raw_profiles = build_profiles(raw_words, raw_ngrams)
    normalized_profiles = build_profiles(normalized_words, normalized_ngrams)
    role_owners = sorted(set(role_map.values()))
    shared_vocabulary = []
    distinctive_vocabulary = {owner: [] for owner in role_owners}
    distinctive_phrases = {owner: [] for owner in role_owners}
    if len(role_owners) == 2:
        left, right = role_owners
        for word, count in normalized_words[left].most_common():
            if normalized_words[right][word]:
                shared_vocabulary.append({"word": word, "you_or_role_counts": {left: count, right: normalized_words[right][word]}})
            elif count >= 3 and word not in stopwords:
                distinctive_vocabulary[left].append({"word": word, "count": count})
        for word, count in normalized_words[right].most_common():
            if normalized_words[left][word] == 0 and count >= 3 and word not in stopwords:
                distinctive_vocabulary[right].append({"word": word, "count": count})
        for owner, other in ((left, right), (right, left)):
            for phrase, count in normalized_ngrams[owner].most_common():
                if count >= 3 and normalized_ngrams[other][phrase] == 0 and any(token not in stopwords for token in phrase):
                    distinctive_phrases[owner].append({"phrase": " ".join(phrase), "count": count})
                    if len(distinctive_phrases[owner]) >= 30:
                        break
    applied_rules = []
    for canonical, forms in normalization_rules.items():
        source_forms = [form.casefold() for form in forms if form.casefold() != canonical.casefold()]
        applied_rules.append({
            "canonical_form": canonical.casefold(),
            "merged_forms": source_forms,
            "raw_counts": {form: raw_words["combined"][form] for form in source_forms},
            "canonical_total_count": normalized_words["combined"][canonical.casefold()],
        })

    return {
        "method": {
            "tokenization": "Unicode letters and numbers; case-folded for counting only.",
            "original_messages_changed": False,
            "ngram_boundary": "Phrases are counted within each message and do not cross message boundaries.",
            "spelling_normalization": "Only user-confirmed spelling groups are merged; both raw and normalized profiles are retained.",
        },
        "profiles": normalized_profiles,
        "normalized_profiles": normalized_profiles,
        "raw_profiles": raw_profiles,
        "applied_normalization_rules": applied_rules,
        "review_only_normalization_suggestions": candidate_groups,
        "shared_vocabulary": shared_vocabulary[:100],
        "distinctive_vocabulary_candidates": {
            owner: items[:100] for owner, items in distinctive_vocabulary.items()
        },
        "distinctive_phrase_candidates": distinctive_phrases,
        "monthly_language_usage": {
            month: {
                "message_count": monthly_message_totals[month],
                "word_count": monthly_word_totals[month],
                "average_words_per_message": round(monthly_word_totals[month] / monthly_message_totals[month], 2) if monthly_message_totals[month] else None,
                "word_class_counts": {key: value for key, value in monthly_classes[month].items() if not key.startswith("messages_")},
                "message_language_class_counts": {key.removeprefix("messages_"): value for key, value in monthly_classes[month].items() if key.startswith("messages_")},
                "top_20_words": top(Counter({(word,): count for word, count in monthly_word_counts[month].items()}), 20),
            }
            for month in sorted(monthly_message_totals)
        },
        "language_classification": {
            "combined_message_classes": dict(message_language_classes),
            "dictionary_word_counts": dict(word_classes["combined"]),
            "dictionary_config": "data/processed/language_lexicon.json",
            "note": "Word/message labels are dictionary-based estimates. Unknown Roman-script words remain unclassified; Roman script alone is not treated as English.",
        },
        "filler_word_classification": "Filler counts use configurable English/Hinglish stopword lists; all words remain present in raw and normalized top-word counts.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Parsed export JSON path")
    parser.add_argument("--roles", default=str(DEFAULT_ROLES), help="Sender-role mapping JSON path")
    parser.add_argument("--rules", default=str(DEFAULT_RULES), help="User-confirmed spelling normalization JSON path")
    parser.add_argument("--lexicon", default=str(DEFAULT_LEXICON), help="Hindi/Hinglish/English/slang/stopword lexicon JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Language profile output path")
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    with Path(args.roles).open("r", encoding="utf-8") as handle:
        role_map = json.load(handle)
    with Path(args.rules).open("r", encoding="utf-8") as handle:
        normalization_rules = json.load(handle)
    with Path(args.lexicon).open("r", encoding="utf-8") as handle:
        lexicon = json.load(handle)
    result = analyze(parsed, role_map, normalization_rules, lexicon)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(json.dumps({
        "output": str(output_path),
        "profiled_message_count": result["profiles"]["combined"]["messages_with_words"],
        "normalization_rules_applied": len(result["applied_normalization_rules"]),
        "unconfirmed_suggestions_for_review": len(result["review_only_normalization_suggestions"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
