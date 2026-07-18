<div align="center">

<img src="https://files.catbox.moe/ntodvf.jpg" alt="BlacMusicAPI" width="100%" />

# BlacMusicAPI

**Fast · Cookieless · Bandwidth-conscious YouTube streaming API for Telegram bots**

Built entirely by **[Blac](https://t.me/blcqt)**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?style=flat-square&logo=fastapi&logoColor=white)](#)
[![yt--dlp](https://img.shields.io/badge/yt--dlp-cookieless-red?style=flat-square)](#)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](#)
[![Railway](https://img.shields.io/badge/Railway-primary%20target-0B0D0E?style=flat-square&logo=railway&logoColor=white)](#)
[![License](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)](#)

</div>

---

## ✨ What is this

A self-hosted backend that turns a bare YouTube video id into a ready-to-play
stream for a Telegram music/video bot — **no cookies, no browser, no
account**, and no bytes wasted. It resolves a direct source with `yt-dlp`
and reverse-proxies the media straight through to the caller, so nothing is
ever written to disk.

Every age-restricted, region-locked, or otherwise gated video is handled by
an automatic bypass ladder — no manual cookie exports, ever.

## 🧠 Why proxy bytes instead of returning a signed URL?

YouTube's signed `googlevideo.com` URLs are locked to the IP that requested
them. Hand that URL back as JSON and it only works if your bot happens to
share the API's egress IP — everywhere else it 403s. This API fetches the
bytes itself and streams them onward instead, so your bot only ever talks
to **this API** — never to googlevideo directly. That's what makes it work
from any bot host, in any region, with zero cookies.

## 🚀 Highlights

| | |
|---|---|
| 🍪 **Cookieless** | No cookie files, no login, no browser export — ever |
| 🔞 **Age-restricted videos** | Bypassed automatically via embedded-client spoofing |
| 🌍 **Region-locked videos** | Automatic geo-bypass ladder cycles through multiple regions |
| 📦 **Zero disk usage** | Streams are proxied in memory, never downloaded to disk |
| 🪶 **Low-spec VPS friendly** | Runs comfortably on a 512MB single-vCPU box |
| ⚡ **Persistent connections** | A shared, pooled HTTP client — no per-request handshake cost |
| 🎚️ **Bandwidth-aware** | 720p default video, 128kbps audio sweet spot, quality is overridable per request |
| 🔁 **Self-healing cache** | Expired signed URLs are transparently re-resolved, once, automatically |
| 🐳 **Deploy anywhere** | Railway (primary), Render, any Docker host, or bare VPS |

## 📡 Endpoints

All routes live under `/api/youtube`. If `API_KEYS` is configured, every
route needs the key as header `X-API-Key: <key>` **or** query
`?api_key=<key>` (query form exists because ffmpeg can't send custom headers
when it opens a stream URL directly).

### Streaming — primary path

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/youtube/play/audio?id=<video_id>` | Audio bytes, Range-aware |
| `GET` | `/api/youtube/play/video/hq?id=<video_id>&height=<optional>` | Video bytes — **720p by default** |
| `GET` | `/api/youtube/play/video?id=<video_id>&height=<optional>` | Video bytes — 480p lighter fallback |

Both video routes accept an optional `?height=` to trade quality for
bandwidth on a per-request basis (e.g. `height=360` for a slow connection).
Omit it to use the server's configured default.

If YouTube only exposes separate video/audio DASH streams for a video (this
is increasingly the norm), the API muxes them on the fly with
`ffmpeg -c copy` — zero re-encoding, negligible CPU. If YouTube offers no
direct or DASH format at all for a video (seen on some datacenter IPs — it
falls back to HLS-only), a third tier kicks in: ffmpeg reads the HLS
manifest directly and remuxes it into a normal stream, still with zero
cookies and zero re-encoding.

### JSON metadata — fallback tier

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/youtube/audio?id=<video_id>` | `{success, audio: {audio_streams: [...]}}` — signed URLs, IP-locked to this server |
| `GET` | `/api/youtube/stream?id=<video_id>` | `{success, stream: {url}}` — signed muxed URL, IP-locked |

### Generic metadata

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/youtube/search?q=<query>&limit=5` | Search results |
| `GET` | `/api/youtube/info?id=<video_id>` | Title / duration / thumbnail / channel |
| `GET` | `/api/youtube/playlist?url=<playlist_url>&limit=50` | Playlist entries |

### Health

`GET /` and `GET /health` — instant static responses, used for platform
health checks and bot keepalive pings.

Interactive docs live at `/docs` (set `ENABLE_DOCS=false` to hide them in
production).

## 🛡️ How age-restricted & region-locked videos are handled

Every resolution attempt escalates through a bypass ladder automatically —
nothing to configure, nothing to touch per request:

1. **Normal videos** — resolved on the first attempt using web/android/ios
   client spoofing. Covers the overwhelming majority of content.
2. **Age-gated videos** — on detecting an age-verification error, the
   request is retried using `tv_embedded`/`android` clients, which are never
   shown the age-gate prompt in the first place (embedded players skip it
   entirely) — no login, no cookies.
3. **Region-locked videos** — on detecting a geo-block error, the request is
   retried while spoofing through a rotating list of country codes
   (`US, GB, DE, CA, IN, NL, JP, SG` by default) until one succeeds.

A normal video is never slowed down by this — only a video that actually
needs the bypass pays the (single, cheap) extra retry.

## ⚙️ Configuration

Copy `sample.env` to `.env` for local runs; on Railway/Render/Heroku set the
same variables as dashboard environment variables instead. Everything has a
sane default — the ones you're most likely to touch:

| Variable | Default | What it does |
|---|---|---|
| `API_KEYS` | *(blank)* | Comma-separated keys; blank = open API |
| `WORKERS` | `1` | Keep at 1 on a single VPS — caches/locks are per-process |
| `VIDEO_HQ_MAX_HEIGHT` | `720` | Default video quality |
| `VIDEO_SD_MAX_HEIGHT` | `480` | Lighter fallback quality tier |
| `VIDEO_MAX_HEIGHT_CEILING` | `1080` | Hard cap even if a caller requests more via `?height=` |
| `RATE_LIMIT_PER_MIN` | `0` (off) | Per-IP request cap, if you ever need one |
| `PORT` | `7860` | See below |

## 🏃 Running locally

```bash
pip install -r requirements.txt
python main.py
```

On startup the console prints the base URL(s) you can reach the API on:

```
┌──────────────────────────────────┐
│  BlacMusicAPI is running         │
│  Local   : http://127.0.0.1:7860 │
│  Docs    : http://127.0.0.1:7860/docs │
│  Health  : http://127.0.0.1:7860/health │
└──────────────────────────────────┘
```

If deployed on Railway or Render, the detected public URL is printed too.

**Requires `ffmpeg` and Node.js ≥ 23.5 on PATH** — `yt-dlp` uses Node to
solve YouTube's n-signature challenge cookielessly. Without it you'll see
"Sign in to confirm you're not a bot" errors. The Docker image installs
both for you.

### Why port 7860?

`8000`, `8080`, `3000`, and `5000` are the first ports every other stack on
a VPS reaches for — collisions are common. `7860` (the Gradio/HF-Spaces
convention) is almost always free, so `python main.py` just works without
you needing to hunt for an open port first. Railway/Render inject their own
`PORT` at deploy time regardless, so this only really matters for bare-VPS
and local runs.

## ☁️ Deployment

**Railway — recommended, primary target.** `railway.toml` is included,
pointing at the Dockerfile. Push to GitHub, connect the repo on Railway, set
`API_KEYS` if you want auth, deploy. No disk usage to speak of, so even the
smallest plan is comfortable.

**Render.** `render.yaml` is included (Docker web service). Render's free
tier spins down after inactivity — the bot's keepalive ping against `/` is
designed for exactly that.

**Any VPS.**
```bash
docker build -t blacmusicapi .
docker run -p 7860:7860 --env-file .env blacmusicapi
```
Or skip Docker entirely and run `python main.py` inside `systemd`/`tmux` —
just make sure `ffmpeg` and Node are installed on the host either way.

**Heroku-style / container platforms.** `Procfile` and `app.json` are
included for one-click-deploy platforms with container support.

**Vercel — not supported, intentionally.** Vercel's Python runtime is built
for short serverless functions, not long-lived streaming responses or
spawning subprocesses (ffmpeg muxing), and its execution-time limits would
cut audio/video off mid-playback. Use Railway, Render, or a VPS instead.

## 🩺 Error responses & logging

Every failure returns a real, distinguishable status code — never a blanket
404 hiding the actual cause:

| Status | Meaning |
|---|---|
| `400` | Invalid/missing `id` in the request |
| `404` | The video genuinely doesn't exist, is private, or has no playable stream |
| `429` | YouTube is rate-limiting or blocking this server's IP |
| `500` | A required binary (Node.js or ffmpeg) is missing on the server |
| `502` | The upstream video source or network failed unexpectedly |
| `504` | Resolution didn't finish within `RESOLVE_TIMEOUT` |

Every one of these is logged server-side with the real underlying exception
before being translated to a response — check your platform's **runtime/deploy
logs** (not the build logs) for lines prefixed `[resolver]` or `[proxy]`.
Logging is explicitly flushed and the Docker image sets
`PYTHONUNBUFFERED=1`, so log lines show up immediately rather than sitting
in a buffer.

## 🎚️ Multi-quality fallback

Add `?with_fallbacks=true` to `/api/youtube/stream` to get a `qualities`
array of additional lower-resolution URLs (480p/360p/240p) alongside the
primary one — useful if a bot wants to drop quality on network jitter
without a fresh resolution round-trip. Left off by default since resolving
extra qualities costs extra yt-dlp calls; only pay for it when you use it.
`/api/youtube/audio` already returns multiple audio bitrate candidates by
default, since it's a single extraction either way.

## 📉 Bandwidth & performance notes

- **720p by default** for video — the quality/bandwidth sweet spot for
  voice-chat playback. Callers can request less via `?height=` when it
  matters (e.g. a listener on a slow connection), and never more than
  `VIDEO_MAX_HEIGHT_CEILING`.
- **Audio defaults to itag 140** (~128kbps AAC) — the widest-compatible,
  bandwidth-sane option rather than always grabbing the highest bitrate
  available.
- **Zero disk writes** during normal playback — everything streams through
  in memory in configurable chunks (`HTTP_CHUNK_SIZE`, default 256KB).
- **One shared, pooled HTTP client** for every proxied stream instead of a
  fresh connection per request — cuts per-request latency and CPU.
- **Resolved URLs are cached** (`URL_CACHE_TTL`, default 3h) and
  de-duplicated per video id — concurrent requests for the same track only
  ever trigger one `yt-dlp` extraction, and an expired cached URL is
  transparently re-resolved once rather than failing the request.
- **On-the-fly video muxing is a stream-copy** (`-c copy`) — no
  re-encoding, so even the split-stream fallback path is cheap on a
  1-vCPU box.

## 📄 License

MIT.

---

<div align="center">

Built by **[Blac](https://t.me/blcqt)** · [@blcqt](https://t.me/blcqt)

</div>
