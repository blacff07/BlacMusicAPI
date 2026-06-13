# blacmusicbot.py — Blac Music Bot
# Built on Blac Music API
# Dev: @blcqt | Channel: @TechTipsCode
#
# Works on Python 3.10, 3.11, 3.12, 3.13, 3.14
#
# Setup:
#   1. Fill in the CONFIGURATION block below
#   2. bash install.sh
#   3. Put blacmusic.py in the same folder as this file
#   4. python3 blacmusicbot.py
#
# Commands:
#   /play    <name or URL>   play audio in voice chat
#   /vplay   <name or URL>   play video in voice chat
#   /pause                   pause playback
#   /resume                  resume playback
#   /skip                    skip current track
#   /stop | /end             stop and leave voice chat
#   /queue | /q              show queue
#   /np    | /now            show currently playing
#   /search  <query>         pick from top 5 results
#   /playlist <URL>          queue a YouTube playlist
#   /ping                    check bot and API status

import sys
import importlib.metadata

# Guard: detect if the old system pyrogram is overriding kurigram.
# This causes: RuntimeError: Future attached to a different loop
# If caught, print a clear fix and exit before anything breaks.
def _check_pyrogram():
    try:
        importlib.metadata.version("kurigram")
        return  # kurigram is installed, all good
    except importlib.metadata.PackageNotFoundError:
        pass
    # kurigram not found — wrong pyrogram is active
    print("")
    print("ERROR: The system 'pyrogram' is overriding 'kurigram'.")
    print("This causes: RuntimeError: Future attached to a different loop")
    print("")
    print("Fix:")
    print("  bash install.sh")
    print("")
    print("Or manually:")
    print("  pip3 uninstall pyrogram -y")
    print("  pip3 install kurigram --break-system-packages --force-reinstall")
    print("")
    sys.exit(1)

_check_pyrogram()


# =============================================================================
# CONFIGURATION
# =============================================================================

# Bot token from @BotFather
BOT_TOKEN = "123456789:AAABBBCCC-your-bot-token-here"

# Your Telegram user ID — message @userinfobot to get it
OWNER_ID = 123456789

# From https://my.telegram.org
API_ID   = 12345678
API_HASH = "abcdef1234567890abcdef1234567890"

# Session string for the assistant account that joins voice chats.
# Use a secondary Telegram account — NOT your main account.
#
# Generate it (run this once, paste the output into ASSISTANT_SESSION below):
#
#   python3 -c "
#   import asyncio
#   from pyrogram import Client
#   async def gen():
#       async with Client('tmp', api_id=12345678, api_hash='your_hash') as c:
#           print(await c.export_session_string())
#   asyncio.run(gen())
#   "
#
ASSISTANT_SESSION = "BQA...your_session_string_here..."

# URL of your running Blac Music API server
#   Same machine : "http://localhost:8000"
#   Remote VPS   : "http://YOUR_IP:8000"
#   With domain  : "https://api.yourdomain.com"
API_BASE_URL = "http://localhost:8000"

# API key — only set if you added API_KEYS in the server's .env
# Leave as None for open deployments (default)
API_KEY = None

DOWNLOAD_DIR        = "downloads"
QUEUE_DISPLAY_LIMIT = 10

# =============================================================================
# END OF CONFIGURATION
# =============================================================================

import os
import time
import asyncio
import signal
from collections import defaultdict

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from pytgcalls import PyTgCalls
from pytgcalls import types as tgtypes
from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError

from blacmusic import BlacAPI, BlacAPIError

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# --- Clients ---
# All three clients must be started inside the same coroutine that
# asyncio.run() owns. Never create or set an event loop before asyncio.run().

bot = Client(
    "BlacMusicBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

assistant = Client(
    "BlacAssistant",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=ASSISTANT_SESSION,
)

call = PyTgCalls(assistant)

api = BlacAPI(
    base_url=API_BASE_URL,
    api_key=API_KEY,
    download_dir=DOWNLOAD_DIR,
)


# --- Per-chat state ---

queues:      dict[int, list[dict]] = defaultdict(list)
now_playing: dict[int, dict]       = {}
started_at:  dict[int, float]      = {}
paused:      dict[int, bool]       = defaultdict(bool)
_skip_depth: dict[int, int]        = defaultdict(int)
_play_locks: dict[int, asyncio.Lock] = {}

MAX_SKIP_DEPTH = 5


# --- Stream builders (py-tgcalls 2.x API) ---

def make_audio_stream(filepath: str) -> tgtypes.MediaStream:
    return tgtypes.MediaStream(
        filepath,
        audio_parameters=tgtypes.AudioQuality.HIGH,
        video_flags=tgtypes.MediaStream.Flags.IGNORE,
    )


def make_video_stream(filepath: str) -> tgtypes.MediaStream:
    return tgtypes.MediaStream(
        filepath,
        audio_parameters=tgtypes.AudioQuality.HIGH,
        video_flags=tgtypes.MediaStream.Flags.AUTO_DETECT,
    )


# --- Helpers ---

def fmt_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


async def safe_reply(message: Message, text: str, **kwargs):
    try:
        await message.reply(text, **kwargs)
    except Exception:
        pass


def get_play_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _play_locks:
        _play_locks[chat_id] = asyncio.Lock()
    return _play_locks[chat_id]


async def leave_vc(chat_id: int):
    try:
        await call.leave_call(chat_id)
    except Exception:
        pass
    queues[chat_id].clear()
    now_playing.pop(chat_id, None)
    started_at.pop(chat_id, None)
    paused[chat_id]      = False
    _skip_depth[chat_id] = 0


# --- Playback core ---

async def play_next(chat_id: int):
    """Play the next queued track. Lock prevents duplicate concurrent calls."""
    lock = get_play_lock(chat_id)
    if lock.locked():
        return
    async with lock:
        await _play_next_inner(chat_id)


async def _play_next_inner(chat_id: int):
    _skip_depth[chat_id] += 1
    if _skip_depth[chat_id] > MAX_SKIP_DEPTH:
        _skip_depth[chat_id] = 0
        await leave_vc(chat_id)
        try:
            await bot.send_message(chat_id, "Too many errors in a row. Stopped.")
        except Exception:
            pass
        return

    if not queues[chat_id]:
        _skip_depth[chat_id] = 0
        await leave_vc(chat_id)
        return

    track = queues[chat_id].pop(0)
    now_playing[chat_id] = track
    started_at[chat_id]  = time.time()
    paused[chat_id]      = False

    try:
        if track.get("is_video"):
            filepath = await api.download_video(track["id"])
            stream   = make_video_stream(filepath)
        else:
            filepath = await api.download_audio(track["id"])
            stream   = make_audio_stream(filepath)

        await call.change_stream(chat_id, stream)
        _skip_depth[chat_id] = 0

    except Exception:
        try:
            await bot.send_message(
                chat_id,
                f"Could not play **{track.get('title', track['id'])}** — skipping...",
            )
        except Exception:
            pass
        await _play_next_inner(chat_id)


async def join_and_play(chat_id: int, track: dict, message: Message):
    """Join VC and start playing. Adds to queue if already streaming."""
    is_video = track.get("is_video", False)

    try:
        if is_video:
            filepath = await api.download_video(track["id"])
            stream   = make_video_stream(filepath)
        else:
            filepath = await api.download_audio(track["id"])
            stream   = make_audio_stream(filepath)
    except BlacAPIError as exc:
        return await safe_reply(message, f"❌ {exc}")
    except Exception as exc:
        return await safe_reply(message, f"❌ Download failed: {exc}")

    icon = "🎬" if is_video else "🎵"

    try:
        await call.play(
            chat_id,
            stream,
            config=tgtypes.GroupCallConfig(auto_start=True),
        )
        now_playing[chat_id] = track
        started_at[chat_id]  = time.time()
        paused[chat_id]      = False
        _skip_depth[chat_id] = 0

        await safe_reply(
            message,
            f"{icon} **Now Playing**\n"
            f"**{track['title']}**\n"
            f"⏱ `{track['duration']}` | 🎙 {track.get('channel', '')}\n"
            f"🔗 [YouTube]({track['url']})",
            disable_web_page_preview=True,
        )

    except tgtypes.AlreadyActiveGroupCall:
        queues[chat_id].append(track)
        pos = len(queues[chat_id])
        await safe_reply(
            message,
            f"{icon} **Added to Queue** — #{pos}\n"
            f"**{track['title']}**\n"
            f"⏱ `{track['duration']}` | 🎙 {track.get('channel', '')}",
        )

    except NoActiveGroupCall:
        await safe_reply(message, "❌ No active voice chat. Start one in this group first.")

    except Exception as exc:
        await safe_reply(message, f"❌ Could not join voice chat: {exc}")


# --- Stream end / chat update handler ---

@call.on_update()
async def on_update(_, update: tgtypes.Update):
    if isinstance(update, tgtypes.StreamEnded):
        if update.stream_type == tgtypes.StreamEnded.Type.AUDIO:
            await play_next(update.chat_id)
    elif isinstance(update, tgtypes.ChatUpdate):
        if update.status in (
            tgtypes.ChatUpdate.Status.KICKED,
            tgtypes.ChatUpdate.Status.LEFT_GROUP,
            tgtypes.ChatUpdate.Status.CLOSED_VOICE_CHAT,
        ):
            await leave_vc(update.chat_id)


# =============================================================================
# COMMANDS
# =============================================================================

@bot.on_message(filters.command("play") & filters.group)
async def cmd_play(_, message: Message):
    query = " ".join(message.command[1:]).strip()
    if not query:
        return await message.reply("**Usage:** `/play <song name or YouTube URL>`")

    msg = await message.reply("🔍 Searching...")
    try:
        results = await api.search(query, limit=1)
        if not results:
            return await msg.edit("❌ No results found.")
        track = results[0]
        track["is_video"] = False
        await msg.delete()
        await join_and_play(message.chat.id, track, message)
    except BlacAPIError as exc:
        await msg.edit(f"❌ {exc}")
    except Exception as exc:
        await msg.edit(f"❌ {exc}")


@bot.on_message(filters.command("vplay") & filters.group)
async def cmd_vplay(_, message: Message):
    query = " ".join(message.command[1:]).strip()
    if not query:
        return await message.reply("**Usage:** `/vplay <song name or YouTube URL>`")

    msg = await message.reply("🔍 Searching...")
    try:
        results = await api.search(query, limit=1)
        if not results:
            return await msg.edit("❌ No results found.")
        track = results[0]
        track["is_video"] = True
        await msg.delete()
        await join_and_play(message.chat.id, track, message)
    except BlacAPIError as exc:
        await msg.edit(f"❌ {exc}")
    except Exception as exc:
        await msg.edit(f"❌ {exc}")


@bot.on_message(filters.command("pause") & filters.group)
async def cmd_pause(_, message: Message):
    chat_id = message.chat.id
    if chat_id not in now_playing:
        return await message.reply("❌ Nothing is playing.")
    if paused[chat_id]:
        return await message.reply("Already paused.")
    try:
        await call.pause(chat_id)
        paused[chat_id] = True
        await message.reply("⏸ Paused.")
    except NotInCallError:
        await message.reply("❌ Not in a voice chat.")
    except Exception as exc:
        await message.reply(f"❌ {exc}")


@bot.on_message(filters.command("resume") & filters.group)
async def cmd_resume(_, message: Message):
    chat_id = message.chat.id
    if not paused[chat_id]:
        return await message.reply("Nothing is paused.")
    try:
        await call.resume(chat_id)
        paused[chat_id] = False
        await message.reply("▶️ Resumed.")
    except NotInCallError:
        await message.reply("❌ Not in a voice chat.")
    except Exception as exc:
        await message.reply(f"❌ {exc}")


@bot.on_message(filters.command("skip") & filters.group)
async def cmd_skip(_, message: Message):
    chat_id = message.chat.id
    if chat_id not in now_playing:
        return await message.reply("❌ Nothing is playing.")
    await message.reply("⏭ Skipped.")
    _skip_depth[chat_id] = 0
    await play_next(chat_id)


@bot.on_message(filters.command(["stop", "end"]) & filters.group)
async def cmd_stop(_, message: Message):
    await leave_vc(message.chat.id)
    await message.reply("⏹ Stopped.")


@bot.on_message(filters.command(["queue", "q"]) & filters.group)
async def cmd_queue(_, message: Message):
    chat_id = message.chat.id
    current = now_playing.get(chat_id)
    q       = queues[chat_id]

    if not current and not q:
        return await message.reply("📭 Queue is empty.")

    lines = []
    if current:
        elapsed = int(time.time() - started_at.get(chat_id, time.time()))
        icon    = "🎬" if current.get("is_video") else "🎵"
        status  = "⏸" if paused[chat_id] else "▶️"
        lines.append(
            f"{status} **Now Playing** {icon}\n"
            f"**{current['title']}**\n"
            f"⏱ `{fmt_duration(elapsed)}` / `{current.get('duration', '?')}`"
        )

    if q:
        lines.append(f"\n📋 **Queue — {len(q)} track(s):**")
        for i, t in enumerate(q[:QUEUE_DISPLAY_LIMIT], 1):
            icon = "🎬" if t.get("is_video") else "🎵"
            lines.append(f"{i}. {icon} {t['title']} — `{t.get('duration', '?')}`")
        if len(q) > QUEUE_DISPLAY_LIMIT:
            lines.append(f"... and {len(q) - QUEUE_DISPLAY_LIMIT} more")

    await message.reply("\n".join(lines))


@bot.on_message(filters.command(["np", "now"]) & filters.group)
async def cmd_now_playing(_, message: Message):
    chat_id = message.chat.id
    current = now_playing.get(chat_id)
    if not current:
        return await message.reply("📭 Nothing is playing.")

    elapsed = int(time.time() - started_at.get(chat_id, time.time()))
    dur_sec = current.get("duration_sec", 0)
    icon    = "🎬" if current.get("is_video") else "🎵"
    status  = "⏸ Paused" if paused[chat_id] else "▶️ Playing"
    bar_len = 12
    filled  = min(int((elapsed / dur_sec) * bar_len), bar_len) if dur_sec else 0
    bar     = "▓" * filled + "░" * (bar_len - filled)

    await message.reply(
        f"{icon} **{status}**\n\n"
        f"**{current['title']}**\n"
        f"🎙 {current.get('channel', '')}\n\n"
        f"`{fmt_duration(elapsed)}` [{bar}] `{fmt_duration(dur_sec)}`\n\n"
        f"🔗 [Watch on YouTube]({current['url']})",
        disable_web_page_preview=True,
    )


@bot.on_message(filters.command("search") & filters.group)
async def cmd_search(_, message: Message):
    query = " ".join(message.command[1:]).strip()
    if not query:
        return await message.reply("**Usage:** `/search <song name>`")

    msg = await message.reply("🔍 Searching...")
    try:
        results = await api.search(query, limit=5)
        if not results:
            return await msg.edit("❌ No results found.")

        text_lines = ["🔎 **Search Results** — tap to play:\n"]
        buttons    = []
        for i, r in enumerate(results, 1):
            text_lines.append(f"`{i}.` {r['title']} — `{r['duration']}`")
            buttons.append([
                InlineKeyboardButton(f"🎵 {i}. {r['title'][:28]}", callback_data=f"play:{r['id']}"),
                InlineKeyboardButton("🎬", callback_data=f"vplay:{r['id']}"),
            ])

        await msg.edit("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(buttons))

    except BlacAPIError as exc:
        await msg.edit(f"❌ {exc}")
    except Exception as exc:
        await msg.edit(f"❌ {exc}")


@bot.on_callback_query(filters.regex(r"^(v?play):([A-Za-z0-9_-]{11})$"))
async def cb_search_result(_, cq: CallbackQuery):
    mode, video_id = cq.data.split(":", 1)
    is_video = (mode == "vplay")
    chat_id  = cq.message.chat.id

    await cq.answer("⬇️ Downloading...")
    try:
        track = await api.get_info(video_id)
        if not track:
            return await cq.answer("❌ Could not get track info.", show_alert=True)
        track["is_video"] = is_video

        try:
            await cq.message.delete()
        except Exception:
            pass

        status_msg = await bot.send_message(chat_id, "⬇️ Loading...")
        await join_and_play(chat_id, track, status_msg)
        try:
            await status_msg.delete()
        except Exception:
            pass

    except BlacAPIError as exc:
        await cq.answer(f"❌ {exc}", show_alert=True)
    except Exception as exc:
        await cq.answer(f"❌ {exc}", show_alert=True)


@bot.on_message(filters.command("playlist") & filters.group)
async def cmd_playlist(_, message: Message):
    args = message.command[1:]
    if not args:
        return await message.reply(
            "**Usage:** `/playlist <YouTube playlist URL>`\n"
            "Example: `/playlist https://youtube.com/playlist?list=PL...`"
        )

    url = args[0]
    msg = await message.reply("📋 Loading playlist...")
    try:
        video_ids = await api.get_playlist(url, limit=50)
        if not video_ids:
            return await msg.edit("❌ Playlist empty or not found.")

        await msg.edit(f"📋 Queuing **{len(video_ids)}** tracks...")

        first = await api.get_info(video_ids[0])
        first["is_video"] = False

        for vid_id in video_ids[1:]:
            queues[message.chat.id].append({
                "id":           vid_id,
                "title":        vid_id,
                "duration":     "?",
                "duration_sec": 0,
                "url":          f"https://youtube.com/watch?v={vid_id}",
                "thumbnail":    "",
                "channel":      "",
                "is_video":     False,
            })

        await msg.delete()
        await join_and_play(message.chat.id, first, message)
        if len(video_ids) > 1:
            await message.reply(f"✅ {len(video_ids) - 1} more track(s) added to queue.")

    except BlacAPIError as exc:
        await msg.edit(f"❌ {exc}")
    except Exception as exc:
        await msg.edit(f"❌ {exc}")


@bot.on_message(filters.command("ping"))
async def cmd_ping(_, message: Message):
    start  = time.time()
    msg    = await message.reply("🏓 Pinging...")
    bot_ms = round((time.time() - start) * 1000)

    try:
        t = time.time()
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{API_BASE_URL}/ping",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                api_ms     = round((time.time() - t) * 1000)
                api_status = "✅ Online" if r.status == 200 else f"⚠️ HTTP {r.status}"
    except Exception as exc:
        api_ms, api_status = 0, f"❌ Offline ({type(exc).__name__})"

    await msg.edit(
        f"🏓 **Pong!**\n\n"
        f"🤖 Bot: `{bot_ms}ms`\n"
        f"🎵 API: `{api_ms}ms` — {api_status}"
    )


@bot.on_message(filters.command("start") & filters.private)
async def cmd_start(_, message: Message):
    await message.reply(
        "👋 **Blac Music Bot**\n\n"
        "Add me to a group with an active voice chat.\n\n"
        "`/play`      — play audio\n"
        "`/vplay`     — play video\n"
        "`/pause`     — pause\n"
        "`/resume`    — resume\n"
        "`/skip`      — skip track\n"
        "`/stop`      — stop and leave\n"
        "`/queue`     — show queue\n"
        "`/np`        — now playing\n"
        "`/search`    — search and pick\n"
        "`/playlist`  — queue a playlist\n"
        "`/ping`      — status check\n\n"
        "Powered by **Blac Music API**\n"
        "[@blcqt](https://t.me/blcqt) | [@TechTipsCode](https://t.me/TechTipsCode)",
        disable_web_page_preview=True,
    )


# =============================================================================
# STARTUP
# All three clients start inside the same coroutine so they share
# the single event loop that asyncio.run() creates.
# =============================================================================

async def main():
    print("-" * 45)
    print("  Blac Music Bot  |  @blcqt  |  @TechTipsCode")
    print("-" * 45)
    print(f"  Python   : {sys.version.split()[0]}")
    print(f"  API URL  : {API_BASE_URL}")
    print(f"  Auth     : {'Enabled' if API_KEY else 'Open'}")

    await bot.start()
    await assistant.start()
    await call.start()

    me = await bot.get_me()
    print(f"  Bot      : @{me.username}")
    print("  Status   : Running")
    print("-" * 45)

    stop_event = asyncio.Event()

    def _handle_signal():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("\n  Stopping...")
        for c in (call, assistant, bot):
            try:
                await c.stop()
            except Exception:
                pass
        print("  Stopped.")


if __name__ == "__main__":
    asyncio.run(main())
