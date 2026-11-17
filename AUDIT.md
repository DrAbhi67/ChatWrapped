# Instagram Chat Wrapped implementation audit

## Export inspected

- Five Instagram JSON chunks share the same top-level `messages` schema and two participants.
- 40,888 unique export rows were found; exact-record deduplication removed none.
- After excluding 2,770 generated reaction-notice rows, 38,118 conversation messages remain.
- Message records contain `sender_name`, Unix-millisecond `timestamp_ms`, optional `content`, `share`, `reactions`, `photos`, `videos`, `audio_files`, `call_duration`, and Instagram flags.
- Attachment references total 199 photos, 26 videos, and 292 audio files. Media binaries were not provided.
- Of 3,506 shared links, the current URL-path classifier identifies 2,562 Reel candidates, 737 post candidates, 31 story candidates, and 176 other Instagram links; 173 links are external.
- The raw export is newest-first in each chunk. The parser combines chunks, sorts by timestamp, and preserves raw message objects.

## Existing implementation checklist

### Implemented in this pass

- [x] Multiple `message_*.json` files, dynamic participant labels, millisecond timestamps, IST conversion, and exact duplicate hashing.
- [x] Raw message preservation plus analysis text repaired for the export's UTF-8/Latin-1 emoji corruption.
- [x] Separation of known attachment and reaction notices from authored text analytics.
- [x] Conversation totals, per-role counts, text length, active days/months, weekdays, hours, and peak periods.
- [x] Eight-hour configurable sessions with 1/6/8/12/24-hour sensitivity; initiators, average/median/fastest/slowest replies, double texts, longest sessions, inactivity gap, one-word messages, questions, max consecutive runs, closed unanswered turns, dayparts, weekend/weekday, after-midnight and hourly rates.
- [x] User-confirmed Hinglish aliases (`nai`/`nahi`/`nhi`, `yr`/`yaar`/`yrr`, `h`/`hai`, `hu`/`hoon`), original and normalized words/ngrams, dictionary-based language labels, filler/slang/affectionate terms, shared and distinctive vocabulary candidates.
- [x] Unicode emoji extraction, role and combined rankings, message/reaction separation, monthly counts, adjacent combinations, emoji rates and diversity comparisons.
- [x] Attachment and shared-link counts by sender/month, Reel/post/story URL candidates, first Reel candidate date, and limitations for missing media binaries.
- [x] Configurable phrase counts for greetings, apologies, compliments, pet names, support and affectionate phrases.
- [x] Manual relationship milestone configuration; confession and relationship start confirmed as 2026-09-09; before/after era comparison.
- [x] Review-only timeline/memory candidates with manually approved memories kept separate.
- [x] Consolidated `output/wrapped_data.json`, monthly trends, definitions, availability notes, and seven local unit tests.

### Partial or intentionally conservative

- [ ] Parser targets the observed Instagram schema; alternate export layouts, deleted/unsent records, and malformed entries are not fully normalized.
- [ ] Media classification remains based on structured fields and visible URL paths; Reel topics and shared media content are not retrieved.
- [ ] Audio file references do not establish that an item is a voice note; no dependable sticker/GIF attachment fields were in this export.
- [ ] Hindi/Hinglish vs English labels use transparent configurable dictionaries; unknown tokens remain unclassified and dictionary gaps are expected.
- [ ] Phrase and sentiment meaning is not inferred. Configured phrase hits can be joking, quoted, or used in other contexts; sentiment is explicitly unavailable.
- [ ] Confession/relationship start date is manually confirmed; other relationship milestones and memory selections await manual approval.
- [ ] Month-level reply times and per-role message counts are available; month-level language, emoji, and message-type trends are currently combined across both people rather than fully split by role.

### Missing from the broader product roadmap

- [ ] React/Vite interactive Wrapped website, charts, animation, story slides, share card, optional music, and responsive visual polish.
- [ ] Media binary ingestion and any manually approved photos/audio/video for scrapbook slides.
- [ ] Final manual review of timeline/memory suggestions and personal finale letter/photo.

## Audit issues to resolve during implementation

- `normalization_rules.json` is the active rules file; `hinglish_normalization.json` now mirrors it and points back to that source of truth.
- Conversation segmentation now defaults to eight hours; the threshold is configurable.
- Timezone is configurable in `analysis_config.json`; Asia/Kolkata remains the default.
- The consolidated output is ignored by Git together with the parsed export and all raw exports.

## Reliability limits

- Raw exports provide attachment references, not the media binaries or dependable Reel descriptions.
- Reaction notice rows and structured reactions are distinct representations and must not be added together as ordinary messages.
- Reply time, unanswered-turn, conversation, language-label, and memory/timeline candidates are estimates; outputs include definitions and limitations.
- Exact message text remains private in local files. Memory/timeline candidates remain unapproved until manually selected.
