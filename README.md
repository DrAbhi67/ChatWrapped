# Instagram Chat Wrapped

Private, local analysis of an Instagram message export. Raw exports, processed
messages, and generated analytics are excluded from Git by `.gitignore`.

## Current local prototype

`backend/parser.py` reads one or more `message_*.json` files, combines their
`messages` arrays, removes only exact duplicate message objects, sorts messages
oldest first, and preserves each source object under `raw`. It adds configured
local timestamps, text and normalization copies, Unicode emoji sequences,
attachment metadata, shared-link candidates, and standard message-type labels.
Known Instagram attachment and reaction notices are marked separately. The
parser writes `output/parsed_export.json`.
Rows explicitly marked `is_unsent_image_by_messenger_kid_parent` are retained
under `raw` but classified separately and excluded from sent-message metrics.

`backend/main.py` runs the analytics modules and writes
`output/wrapped_data.json`. The output includes conversation statistics,
reply and initiation patterns, language and emoji analysis, media counts,
relationship phrase counts, timeline candidates, memory suggestions, a
friendship-versus-relationship comparison, monthly trends, definitions, and
unavailable-data notes. It also keeps message emoji and reactions separate.
The advanced sections are documented in `ADVANCED_METRICS_AUDIT.md`, including
metric definitions, data limitations, and the existing-versus-new audit.
The mobile-first story site is in `frontend/`. The analytics runner also writes
`frontend/wrapped_story_data.json`, a whitelisted aggregate-only payload; it
omits raw messages, excerpts, IDs, and memory candidates. The frontend fetches
that file on every load with browser caching disabled.

The session inactivity threshold defaults to 8 hours and is configurable in
`data/processed/analysis_config.json`. The reports include sensitivity results
at 1, 6, 8, 12, and 24 hours. Timestamps are reported in Asia/Kolkata unless the
config is changed. A fixed +05:30 fallback handles Windows installations that
do not have timezone data installed.

Hinglish normalization only merges the user-confirmed aliases in
`data/processed/normalization_rules.json`. Both raw and normalized language
profiles are retained. `language_lexicon.json` contains editable dictionaries
for Hindi/Hinglish, English, stopwords, slang, affectionate words, and phrases.
Lexicon-based labels and memory/timeline candidates are suggestions, not
automatically confirmed interpretations. The milestone date 2026-09-09 is
confirmed; other dates stay pending until manually reviewed.

Media analysis uses attachment fields and visible URL paths only. The media
binaries are not present, so voice notes cannot be identified reliably and
Reel topics are not inferred from URLs. Sentiment is marked unavailable because
no locally validated Hinglish and sarcasm-aware model is configured.

## Run in VS Code PowerShell terminal

Put the Instagram JSON chunks in `data/raw/`, then run:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe backend\parser.py
.\.venv\Scripts\python.exe backend\main.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m http.server 8000 --bind 127.0.0.1 --directory frontend
```

Open `http://127.0.0.1:8000/` after starting the server. The server binds to
this computer only and exposes only the `frontend/` directory, not the raw
export or full private analytics JSON. To refresh the story stats, rerun
`backend\main.py` before opening the site.

PowerShell activation is optional. If script execution is blocked, call the
virtual environment's Python executable directly as shown above. No external
Python packages are required by this prototype.

## Publish the story with GitHub Pages

The repository includes `.github/workflows/pages.yml`. Once pushed to the
`main` branch, it publishes only `frontend/` and the aggregate
`frontend/wrapped_story_data.json` payload. The raw Instagram export, parsed
messages, and full analytics remain ignored by Git. The story JSON contains
personal aggregates and selected milestone timestamps, so anyone who can
access the public Pages URL can view those details.

1. Create a new **public** repository in the project-only GitHub account. Leave
   it empty when creating it (do not add a README or license).
2. In the VS Code PowerShell terminal at the project root, run these commands,
   replacing the placeholders in the remote URL with the new account and repo:

   ```powershell
   git init -b main
   git add .
   git commit -m "Prepare Instagram Chat Wrapped for Pages"
   git remote add origin https://github.com/NEW-USERNAME/instagram-chat-wrapped.git
   git push -u origin main
   ```

3. In the repository on GitHub, open **Settings → Pages**, select **GitHub
   Actions** as the source, and save. The workflow will publish on the first
   push and on later pushes to `main`.

The published site is public even if its repository is private on plans where
private-repository Pages is available. Do not add raw chats, photos, videos, or
audio to the published frontend.

## Current export inspection

The workspace contains five JSON chunks with the same top-level Instagram
structure. There are 40,888 unique export rows, including 2,770 generated
reaction-notice rows; excluding these leaves 38,118 conversation rows. The
export has two sender identities. It contains references to photos, videos,
and audio files, but no media binaries were added. Shared URLs are classified
by visible host and path; a Reel label is a candidate, not verified media
content. Full message text and memory candidates remain in local ignored files.
