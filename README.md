# Blac Music API

Fast, free, self-hosted YouTube music API for Telegram bots.
Supports audio (`/play`) and video (`/vplay`). Handles 50–100 concurrent voice chats.

**By Blac** — [@blcqt](https://t.me/blcqt) | [@TechTipsCode](https://t.me/TechTipsCode)

---

## Repo Contents

| File | Purpose |
|---|---|
| `main.py` | Start the API server |
| `blacmusic.py` | SDK — copy into any bot to integrate with the API |
| `blacmusicbot.py` | Ready-made music bot — fill credentials and run |
| `requirements.txt` | All dependencies (API server + bot) |
| `blacapi/` | API server source code |
| `.env.example` | Copy to `.env` and configure |

---

## Common Install Notes (read first)

These errors come up on modern Ubuntu/Debian systems. Know them before starting.

**`error: externally-managed-environment`**
Ubuntu protects its Python from global pip installs. Add `--break-system-packages` to every `pip install` command.

**`Cannot uninstall aiohttp` / `no record file`**
Ubuntu pre-installed an older version via apt. Add `--ignore-installed` alongside `--break-system-packages`.

**Full install flag to avoid both:**
```bash
pip install -r requirements.txt --break-system-packages --ignore-installed
```

**`No module named 'dotenv'`** — run the above install command, `python-dotenv` is included.

**`No matching distribution found for py-yt`** — the old name was wrong. The correct package `py-yt-search` is already in `requirements.txt`.

---

## Part 1 — API Server

### Requirements

- Python 3.10, 3.11, or 3.12
- `ffmpeg` installed on the system (required for `/vplay`)
- 512 MB RAM minimum, 2 GB recommended for heavy load

### Install on Ubuntu / Debian

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg git

git clone https://github.com/blacff07/BlacMusicAPI
cd BlacMusicAPI

pip install -r requirements.txt --break-system-packages --ignore-installed

cp .env.example .env
```

Edit `.env` if needed. The defaults work fine for a first run.

### Run

```bash
python3 main.py
```

API is live at `http://localhost:8000`
Swagger UI at `http://localhost:8000/docs`

### Run as systemd service (keeps running after logout and reboot)

```bash
which python3
# note the path it prints, use it below
```

```bash
sudo nano /etc/systemd/system/blacapi.service
```

Paste the following. Replace `/root/BlacMusicAPI` with your actual folder path and `/usr/bin/python3` with the path from `which python3` above.

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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable blacapi
sudo systemctl start blacapi
sudo systemctl status blacapi
```

View live logs:
```bash
sudo journalctl -u blacapi -f
```

Or from the log file:
```bash
tail -f /root/BlacMusicAPI/logs/blacapi.log
```

Open the port if your firewall is active:
```bash
sudo ufw allow 8000
```

### Update the server

```bash
cd /root/BlacMusicAPI
git pull
sudo systemctl restart blacapi
```

### Docker

```bash
docker build -t blacmusicapi .

docker run -d \
  --name blacapi \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/cookies:/app/cookies \
  -v $(pwd)/downloads:/app/downloads \
  -v $(pwd)/logs:/app/logs \
  blacmusicapi
```

Logs:
```bash
docker logs -f blacapi
```

Update:
```bash
git pull
docker stop blacapi && docker rm blacapi
docker build -t blacmusicapi .
docker run -d --name blacapi --restart unless-stopped \
  -p 8000:8000 --env-file .env \
  -v $(pwd)/cookies:/app/cookies \
  -v $(pwd)/downloads:/app/downloads \
  blacmusicapi
```

### Railway

1. Push this repo to your GitHub account
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select the repo — Railway reads the `Procfile` automatically
4. Go to **Variables** and set values from `.env.example` as needed
5. Railway gives you a public URL — use it as `API_BASE_URL` in your bot

> Free tier has ephemeral disk. Downloaded files are lost on restart but the API re-downloads them on demand.

### Render

1. Go to [render.com](https://render.com) → New → Web Service
2. Connect your GitHub repo
3. Set **Build Command:** `pip install -r requirements.txt`
4. Set **Start Command:** `python main.py`
5. Add environment variables from `.env.example` under **Environment**

> Same ephemeral disk note as Railway applies here.

### Nginx reverse proxy (domain + HTTPS)

```bash
sudo apt install nginx certbot python3-certbot-nginx -y
sudo nano /etc/nginx/sites-available/blacapi
```

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300;
        proxy_send_timeout 300;
        client_max_body_size 500M;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/blacapi /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.yourdomain.com
```

Your API is now at `https://api.yourdomain.com`.

---

## Part 2 — API Reference

Every response includes `ok`, `powered_by`, `dev`, and `channel` fields.

### Endpoints

**Health**

| Method | Path | Description |
|---|---|---|
| GET | `/` | Status check |
| GET | `/ping` | Liveness ping |

**Search**

| Method | Path | Description |
|---|---|---|
| GET | `/search/youtube?q=&limit=` | Search YouTube (1–20 results) |
| GET | `/search/playlist?url=&limit=` | Get video IDs from a playlist |

**Info**

| Method | Path | Description |
|---|---|---|
| GET | `/info/youtube?id=` | Track metadata |
| GET | `/info/live?id=` | Direct stream URL for a live broadcast |

**Download**

| Method | Path | Description |
|---|---|---|
| GET | `/download?id=&type=audio` | Stream audio file — for `/play` |
| GET | `/download?id=&type=video` | Stream video file — for `/vplay` |
| GET | `/download/path?id=&type=audio` | Return local filepath (same-server bots) |

**Auth:** If `API_KEYS` is set in `.env`, every request must include header `X-Api-Key: YOUR_KEY`.

---

## Part 3 — Ready-Made Bot

### Python version

**Any Python version works — 3.10, 3.11, 3.12, 3.13, 3.14.**

The bot uses `py-tgcalls` (not `pytgcalls`), which is a pure Python library with no compiled C extensions.
No venv or version downgrade needed.

Check yours:
```bash
python3 --version
```

### Install

Run the provided install script — it handles everything including removing any conflicting system packages:

```bash
bash install.sh
```

**Why not plain `pip install`?**
Modern Ubuntu/Debian systems often have an old `pyrogram` pre-installed at the system level. When `kurigram` (the replacement) is installed alongside it, Python loads the system one first, causing:
`RuntimeError: Future attached to a different loop`

`install.sh` removes the old system `pyrogram` first, then installs everything cleanly. You only need to run it once.

If you prefer to do it manually:
```bash
pip3 uninstall pyrogram -y
pip3 install -r requirements.txt --break-system-packages --ignore-installed --force-reinstall kurigram
```

### Configure the bot

Open `blacmusicbot.py` and fill in the `CONFIGURATION` block at the top:

```python
BOT_TOKEN         = "get this from @BotFather"
OWNER_ID          = 123456789        # message @userinfobot to get your ID
API_ID            = 12345678         # from https://my.telegram.org
API_HASH          = "abc123..."      # from https://my.telegram.org
ASSISTANT_SESSION = "BQA..."         # see generation steps below
API_BASE_URL      = "http://localhost:8000"   # your API server URL
API_KEY           = None             # only set if API_KEYS is in .env
```

### Generate the assistant session string

The assistant is a **secondary Telegram account** (not your main one) that joins voice chats.

Run this once. It will ask you to log in with a phone number — use the secondary account:

```bash
python3 -c "
import asyncio
from pyrogram import Client

async def gen():
    async with Client('tmp', api_id=12345678, api_hash='your_api_hash') as c:
        print(await c.export_session_string())

asyncio.run(gen())
"
```

Copy the long string it prints and paste it into `ASSISTANT_SESSION` in `blacmusicbot.py`.

### Make sure blacmusic.py is in the same folder

`blacmusicbot.py` imports from `blacmusic.py`. They must be in the same directory.

### Run

```bash
python3 blacmusicbot.py
```

### Run as systemd service

```bash
sudo nano /etc/systemd/system/blacbot.service
```

```ini
[Unit]
Description=Blac Music Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/BlacMusicAPI
ExecStart=/usr/bin/python3 /root/BlacMusicAPI/blacmusicbot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable blacbot
sudo systemctl start blacbot
sudo systemctl status blacbot
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
| `/np` or `/now` | Show currently playing with progress |
| `/search <query>` | Pick from top 5 search results |
| `/playlist <URL>` | Queue an entire YouTube playlist |
| `/ping` | Check bot and API response times |

---

## Part 4 — Integrating into Your Own Bot

Copy `blacmusic.py` into your bot project folder. It only needs `aiohttp`.

```python
from blacmusic import BlacAPI, BlacAPIError

api = BlacAPI(
    base_url="http://YOUR_VPS_IP:8000",
    api_key=None,           # set if API_KEYS is configured on the server
    download_dir="downloads",
)
```

### Search and play audio

```python
results  = await api.search("Alan Walker Faded", limit=1)
track    = results[0]
filepath = await api.download_audio(track["id"])
await call.play(chat_id, tgtypes.MediaStream(filepath))
```

### Play video

```python
filepath = await api.download_video(track["id"])
await call.join_group_call(chat_id, VideoPiped(filepath, ...))
```

### Live stream

```python
stream_url = await api.get_live_url("VIDEO_ID_OR_URL")
await call.join_group_call(chat_id, AudioDirectPiped(stream_url))
```

### Playlist

```python
video_ids = await api.get_playlist("https://youtube.com/playlist?list=PL...", limit=50)
```

### One-shot helper

```python
track, filepath = await api.search_and_download_audio("Faded Alan Walker")
```

### Same-server path (faster — skips HTTP transfer)

```python
filepath = await api.download_path(video_id, dtype="audio")
await call.play(chat_id, tgtypes.MediaStream(filepath))
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

---

## Part 5 — Configuration

Copy `.env.example` to `.env` and edit as needed. Defaults are fine for most setups.

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Port the server listens on |
| `WORKERS` | `1` | Uvicorn worker count — keep at 1 |
| `API_KEYS` | _(blank)_ | Comma-separated keys. Blank = open API |
| `MAX_CONCURRENT_DOWNLOADS` | `30` | Max simultaneous yt-dlp downloads |
| `CACHE_TTL` | `7200` | Seconds to keep files before auto-delete |
| `COOKIELESS_FIRST` | `true` | Try without cookies first |
| `VIDEO_MAX_HEIGHT` | `1080` | Max resolution for /vplay |
| `SEARCH_CACHE_TTL` | `600` | Seconds to cache search results in memory |
| `ENABLE_DOCS` | `true` | Show `/docs` Swagger UI |

### Concurrency tuning

| VPS spec | `MAX_CONCURRENT_DOWNLOADS` | Expected capacity |
|---|---|---|
| 1 vCPU / 1 GB RAM | 10–15 | ~20–30 voice chats |
| 2 vCPU / 2 GB RAM | 20–30 | ~50–60 voice chats |
| 4 vCPU / 4 GB RAM | 40–60 | ~80–100 voice chats |
| 8 vCPU / 8 GB RAM | 80–100 | 100+ voice chats |

Files already on disk are served instantly — only new downloads consume a slot.

---

## Part 6 — Cookies (age-restricted content)

The API works without cookies for normal public YouTube videos.
Cookies are only needed for age-restricted content.

1. Install the browser extension **Get cookies.txt LOCALLY** (Chrome or Firefox)
2. Go to `youtube.com` while signed into a Google account
3. Export cookies and save the file as `cookies.txt` inside the `cookies/` folder

Multiple `.txt` files are supported — the API picks one at random per request.
Cookie files are excluded from git by `.gitignore`.

---

## Part 7 — Keeping yt-dlp Updated

YouTube changes its internals frequently. If downloads start failing, update yt-dlp:

```bash
pip install -U yt-dlp --break-system-packages
```

For Docker:
```bash
docker exec blacapi pip install -U yt-dlp && docker restart blacapi
```

---

## License

MIT — free to use and integrate. Credit appreciated.
