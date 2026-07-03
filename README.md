# TranscriptVault — Bulk YouTube Transcript Extractor

A standalone local app to extract transcripts from multiple YouTube videos at once, organized and ready for AI training.

## Setup (one time)

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the app

```bash
python app.py
```

Then open **http://localhost:5050** in your browser.

---

## How to use

1. Paste YouTube URLs or video IDs (one per line) into the input box
2. Click **Extract Transcripts**
3. View results — expand any video to read/copy the transcript
4. Export in your preferred format for AI training

### Supported input formats
- Full URL: `https://www.youtube.com/watch?v=VIDEO_ID`
- Short URL: `https://youtu.be/VIDEO_ID`
- Bare video ID: `dQw4w9WgXcQ`

---

## Export formats

| Format | Best for |
|--------|----------|
| Plain Text ZIP | Simple corpus, one file per video |
| Timestamped ZIP | Speech-text alignment, subtitle training |
| JSON ZIP | Full metadata + transcript per video |
| Markdown ZIP | One .md file per video, with metadata header |
| Single JSON | Drop into training pipelines directly |
| Combined TXT | Simple large text corpus |
| Single Markdown | All videos in one markdown document |

---

## Notes

- Transcripts must be available on YouTube (auto-generated or manual)
- Private or age-restricted videos will fail
- Language auto-selects English, falls back to whatever is available

---

## Project structure

```
transcript-tool/
├── app.py              # Flask backend
├── requirements.txt    # Python deps
└── public/
    └── index.html      # Frontend UI
```

---

## Deploying to Vercel

The app is a standard Vercel Python entrypoint (`app.py` exports a top-level
`app` Flask instance, static assets live in `public/`) — no extra config
needed.

```bash
vercel        # preview deploy
vercel --prod # production deploy
```

**Note:** YouTube periodically blocks transcript requests coming from cloud/
datacenter IPs (including Vercel's). If fetches start failing with
`IpBlocked`/`RequestBlocked` errors after deploy but work fine locally, that's
YouTube rate-limiting the platform's shared egress IPs, not a bug — `youtube-transcript-api`
supports routing through a proxy (see its `ProxyConfig` docs) as a workaround.

## Adding more features later

The backend (`app.py`) exposes a clean REST API:

- `POST /api/fetch` — Extract transcripts, body: `{ "urls": [...] }`
- `POST /api/export` — Export results, body: `{ "results": [...], "format": "txt|json|timestamped", "export_type": "zip|single_json|single_txt" }`

You can add new routes here for features like:
- Playlist support
- Channel-level extraction
- Automatic translation
- AI summarization of transcripts
