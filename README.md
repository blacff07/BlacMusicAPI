# Blac Music API

Fast, free, self-hosted YouTube music API for Telegram bots.
Supports audio (`/play`) and video (`/vplay`). Handles 50-100 concurrent voice chats.

By Blac — [@blcqt](https://t.me/blcqt) | [@TechTipsCode](https://t.me/TechTipsCode)

## Repo Contents

| File | Purpose |
|---|---|
| `main.py` | Start the API server |
| `blacmusic.py` | SDK — copy into any bot to integrate |
| `blacmusicbot.py` | Ready-made music bot |
| `gen_session.py` | Generates the assistant session string |
| `install.sh` | One-command setup that fixes all known Python 3.14 issues |
| `requirements.txt` | All dependencies |
| `blacapi/` | API server source code |

## Quick Start

```bash
git clone https://github.com/blacff07/BlacMusicAPI
cd BlacMusicAPI
bash install.sh
cp .env.example .env
python3 main.py
```

API runs at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

## Running the Bot

```bash
python3 gen_session.py
```

Edit the `CONFIGURATION` block at the top of `blacmusicbot.py`:

```python
BOT_TOKEN            = "get this from @BotFather"
OWNER_ID             = 123456789
API_ID               = 12345678
API_HASH             = "your_api_hash"
ASSISTANT_SESSION    = "paste output from gen_session.py here"
API_BASE_URL         = "http://localhost:8000"
API_KEY              = None
```

Then:

```bash
python3 blacmusicbot.py
```

### Bot commands

| Command | Description |
|---|---|
| `/play <name or URL>` | Play audio in voice chat |
| `/vplay <name or URL>` | Play video in voice chat |
| `/pause` | Pause playback |
| `/resume` | Resume playback |
| `/skip` | Skip current track |
| `/stop` or `/end` | Stop and leave voice chat |
| `/queue` or `/q` | Show queue |
| `/np` or `/now` | Show currently playing |
| `/search <query>` | Pick from top 5 results |
| `/playlist <URL>` | Queue a YouTube playlist |
| `/ping` | Check bot and API status |

## Why install.sh instead of plain pip install

On Python 3.14, three separate compatibility issues break a normal install:

1. **PyPI pyrogram and all forks (kurigram, hydrogram)** use `asyncio.wait_for()` outside a proper Task, which Python 3.14 rejects with `RuntimeError: Timeout should be used inside a task`. Fixed by installing pyrogram directly from its GitHub master branch.

2. **py-tgcalls sync.py** calls `asyncio.get_event_loop()` at module import time with no loop running, crashing immediately. `install.sh` patches this to safely create a loop if none exists.

3. **py-tgcalls expects `GroupcallForbidden`** from pyrogram's error module, which was removed in the GitHub master branch. `install.sh` adds a compatibility stub so the import succeeds.

`install.sh` handles all three automatically. Run it once after cloning, and again any time you wipe your environment.

## API Reference

Every response includes `ok`, `powered_by`, `dev`, `channel`.

### Health
| Method | Path | Description |
|---|---|---|
| GET | `/` | Status check |
| GET | `/ping` | Liveness ping |

### Search
| Method | Path | Description |
|---|---|---|
| GET | `/search/youtube?q=&limit=` | Search YouTube (1-20 results) |
| GET | `/search/playlist?url=&limit=` | Get video IDs from a playlist |

### Info
| Method | Path | Description |
|---|---|---|
| GET | `/info/youtube?id=` | Track metadata |
| GET | `/info/live?id=` | Direct stream URL for a live broadcast |

### Download
| Method | Path | Description |
|---|---|---|
| GET | `/download?id=&type=audio` | Stream audio file — for `/play` |
| GET | `/download?id=&type=video` | Stream video file — for `/vplay` |
| GET | `/download/path?id=&type=audio` | Local filepath (same-server bots) |

If `API_KEYS` is set in `.env`, pass header `X-Api-Key: YOUR_KEY` on every request.

## Integrating into Your Own Bot

Copy `blacmusic.py` into your project. Requires `aiohttp`.

```python
from blacmusic import BlacAPI, BlacAPIError

api = BlacAPI(base_url="http://localhost:8000")

results  = await api.search("Alan Walker Faded", limit=1)
track    = results[0]
filepath = await api.download_audio(track["id"])
```

### Track object fields

| Field | Type | Description |
|---|---|---|
| `title` | str | Video title |
| `id` | str | YouTube video ID |
| `url` | str | Full YouTube URL |
| `duration` | str | Duration as MM:SS or H:MM:SS |
| `duration_sec` | int | Duration in seconds |
| `thumbnail` | str | Thumbnail URL |
| `channel` | str | Channel name |
| `views` | str | View count |

## Hosting

### Ubuntu / Debian VPS

```bash
sudo apt update && sudo apt install -y python3 python3-pip ffmpeg git
git clone https://github.com/blacff07/BlacMusicAPI
cd BlacMusicAPI
bash install.sh
cp .env.example .env
python3 main.py
```

### systemd service (API)

```bash
sudo nano /etc/systemd/system/blacapi.service
```

```ini
[Unit]
Description=Blac Music API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/BlacMusicAPI
ExecStart=/usr/bin/python3 /root/BlacMusicAPI/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable blacapi
sudo systemctl start blacapi
```

### systemd service (Bot)

```bash
sudo nano /etc/systemd/system/blacbot.service
```

```ini
[Unit]
Description=Blac Music Bot
After=network.target blacapi.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/BlacMusicAPI
ExecStart=/usr/bin/python3 /root/BlacMusicAPI/blacmusicbot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable blacbot
sudo systemctl start blacbot
```

### Docker

```bash
docker build -t blacmusicapi .
docker run -d --name blacapi --restart unless-stopped \
  -p 8000:8000 --env-file .env \
  -v $(pwd)/cookies:/app/cookies \
  -v $(pwd)/downloads:/app/downloads \
  blacmusicapi
```

### Railway / Render

Push to GitHub and connect the repo. Both read the `Procfile` automatically. Set environment variables from `.env.example` in the platform dashboard.

Disk is ephemeral on free tiers — downloaded files reset on restart, but the API re-downloads them on demand.

## Configuration

Copy `.env.example` to `.env`.

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Server port |
| `WORKERS` | `1` | Uvicorn workers — keep at 1 |
| `API_KEYS` | blank | Comma-separated auth keys. Blank = open API |
| `MAX_CONCURRENT_DOWNLOADS` | `30` | Parallel yt-dlp downloads |
| `CACHE_TTL` | `7200` | Seconds to keep files before auto-delete |
| `COOKIELESS_FIRST` | `true` | Try without cookies first |
| `VIDEO_MAX_HEIGHT` | `1080` | Max resolution for /vplay |
| `SEARCH_CACHE_TTL` | `600` | Search result cache lifetime |
| `ENABLE_DOCS` | `true` | Show /docs Swagger UI |

### Concurrency tuning

| VPS spec | `MAX_CONCURRENT_DOWNLOADS` | Handles |
|---|---|---|
| 1 vCPU / 1 GB | 10-15 | ~20-30 voice chats |
| 2 vCPU / 2 GB | 20-30 | ~50-60 voice chats |
| 4 vCPU / 4 GB | 40-60 | ~80-100 voice chats |
| 8 vCPU / 8 GB | 80-100 | 100+ voice chats |

## Cookies

Not needed for normal videos. Only needed for age-restricted content.

1. Install browser extension "Get cookies.txt LOCALLY"
2. Go to youtube.com while signed in
3. Export and save as `cookies.txt` in the `cookies/` folder

Multiple files supported — rotates between them.

## Updating yt-dlp

```bash
pip install -U yt-dlp --break-system-packages
```

## License

MIT — free to use and integrate.
