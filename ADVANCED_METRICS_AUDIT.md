# Advanced metrics expansion

## Existing metrics retained and reused

- Conversation sessions, initiator counts, fastest/slowest reply summaries, double-text runs, questions, longest inactivity gap, dayparts, weekday/weekend counts, and active-day streaks.
- Existing Hinglish-normalized word/bigram/trigram profiles, language dictionary estimates, monthly combined word profiles, and configured relationship phrase groups.
- Existing message/reaction emoji separation and role-level emoji rates.
- Existing media attachment/link-path candidates, per-role counts, monthly type counts, and before/after comparison.
- Existing local parser, exact-record de-duplication, raw-message preservation, IST timestamps, and reaction-notice filtering.

## Added metrics

- Burst length distributions, triple-text runs, average rows per session, last sender per session, longest text row and average text length by role, valid reply-delay buckets, and reply speed by local reply hour.
- Midnight/working-hour counts, 30-minute local clock windows, rolling 3/7 calendar-day maxima, sender returns after configured silences, per-role activity consistency, and media-sharing streaks.
- Opening/ending tokens, repeated exact messages after normalization, vocabulary sizes/overlap/exclusive terms, monthly per-role words, abbreviations, punctuation, and all-caps counts.
- Appreciation/reassurance dictionaries, affection-phrase trends, reactions attached to shared-content rows, monthly per-role media counts, daily media peak, and media/text ratios.
- Ten statistic-backed awards. “Ghost” intentionally has no winner because message timing cannot establish intent.
- `data_quality` includes export-row handling, missing timestamps, empty/attachment/reaction rows, unsent marker observations, reaction records, calls, attachments, and source files.

## Unavailable or limited

- Voice-note and sticker counts are `null`: this export does not reliably distinguish those media subtypes. Audio attachment references are counted separately.
- Reel/post labels are visible URL-path candidates only. No linked media binaries were inspected; Reel topics and verified content classifications are unavailable.
- General deleted-message status is unavailable. The export's unsent-image marker is false for all observed rows, which does not prove that no deleted content ever existed.
- If the specific Instagram unsent-image marker is true in a future export, the row remains in `raw` but is classified as `unsent_media` and excluded from sent-message statistics.
- “Ghost” winner is `null`; intent cannot be inferred from reply gaps.
- Phrase, slang, language, and affection counts use editable dictionaries or token rules. They are not emotion/meaning classification.

## Metric definitions and assumptions

- A session ends only when the gap between adjacent timestamped non-reaction rows is **greater than** the configured inactivity threshold (currently 8 hours).
- A reply is a positive timestamp delta at a sender switch inside a session. Equal/negative timestamps are excluded. The 6+ hour bucket is therefore bounded by the session gap.
- A burst is a maximal run of same-sender export rows within a session. Attachment-only rows count as turns; reaction notices do not.
- Conversation ender means the last sender in a session, not intentional disengagement.
- A rolling N-day period sums local calendar dates inclusively. The 30-minute window aggregates a clock-time slot across all dates.
- Daily consistency uses the inclusive first-to-last export date span as denominator.
- Text lengths count Unicode code points after trimming. Repeated sentences mean exact normalized message text after case-folding and whitespace collapsing; punctuation is retained.
- “All caps” requires at least two alphabetic characters and every alphabetic character uppercase.
- Good morning, good night, affection, reassurance, appreciation, compliment, and apology hits use the phrase lists in `data/processed/language_lexicon.json`.
- Media/text ratio is unique rows with media references divided by nonempty authored-text rows; a mixed text-and-media row can be in both counts.
- Structured reactions on shared-content rows are counted, but the export does not prove whether the reaction targets the media itself or the message.

## Verification

Run `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`; the suite covers parser deduplication and timezone conversion, normalization, Unicode emoji, reply boundaries and invalid latencies, burst counts, rolling windows, vocabulary/caps, media reactions, and unavailable awards.
