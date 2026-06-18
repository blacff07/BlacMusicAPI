#!/bin/bash
# install.sh — Run once before starting the bot.

echo "=== Blac Music API Install ==="
echo ""

echo "[1/4] Removing conflicting packages..."
pip3 uninstall pyrogram kurigram hydrogram pytgcalls py-tgcalls -y 2>/dev/null || true
for dir in \
    /usr/local/lib/python3*/dist-packages/pyrogram \
    /usr/lib/python3*/dist-packages/pyrogram \
    /usr/local/lib/python3*/dist-packages/pytgcalls \
    /usr/lib/python3*/dist-packages/pytgcalls; do
    if [ -d "$dir" ]; then
        rm -rf "$dir"
        echo "  Removed: $dir"
    fi
done
echo "  Done."

echo ""
echo "[2/4] Installing base packages..."
pip3 install -r requirements.txt \
    --break-system-packages \
    --ignore-installed \
    --quiet \
    --root-user-action=ignore
echo "  Done."

echo ""
echo "[3/4] Installing pyrogram from GitHub..."
pip3 install \
    "git+https://github.com/pyrogram/pyrogram.git" \
    --break-system-packages \
    --force-reinstall \
    --quiet \
    --root-user-action=ignore

# Verify it actually landed somewhere Python can find it
PYRO_PATH=$(python3 -c "import importlib.util; s=importlib.util.find_spec('pyrogram'); print(s.origin if s else 'NOT_FOUND')" 2>/dev/null || echo "NOT_FOUND")

if [ "$PYRO_PATH" = "NOT_FOUND" ]; then
    echo "  GitHub install not found by Python — trying with --target..."
    # Force install directly into the dist-packages Python 3.14 is using
    SITE=$(python3 -c "import sysconfig; print(sysconfig.get_path('purelib'))")
    echo "  Target: $SITE"
    pip3 install \
        "git+https://github.com/pyrogram/pyrogram.git" \
        --target="$SITE" \
        --upgrade \
        --quiet \
        --root-user-action=ignore
    PYRO_PATH=$(python3 -c "import importlib.util; s=importlib.util.find_spec('pyrogram'); print(s.origin if s else 'NOT_FOUND')" 2>/dev/null || echo "NOT_FOUND")
fi

echo "  pyrogram path: $PYRO_PATH"
echo "  Done."

echo ""
echo "[4/4] Patching py-tgcalls sync.py..."
SYNC_PY=$(find /usr/local/lib/python3*/dist-packages/pytgcalls \
               /usr/lib/python3*/dist-packages/pytgcalls \
               -name "sync.py" 2>/dev/null | head -1)

if [ -z "$SYNC_PY" ]; then
    echo "  ERROR: pytgcalls/sync.py not found"
    exit 1
fi

echo "  Found: $SYNC_PY"

if grep -q "new_event_loop" "$SYNC_PY"; then
    echo "  Already patched — OK"
else
    python3 - "$SYNC_PY" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path, "r") as f:
    src = f.read()
old = "    main_loop = asyncio.get_event_loop()"
new = ("    try:\n"
       "        main_loop = asyncio.get_event_loop()\n"
       "        if main_loop.is_closed():\n"
       "            raise RuntimeError('closed')\n"
       "    except RuntimeError:\n"
       "        main_loop = asyncio.new_event_loop()\n"
       "        asyncio.set_event_loop(main_loop)")
if old in src:
    with open(path, "w") as f:
        f.write(src.replace(old, new))
    print("  Patched OK")
else:
    print("  Already patched or pattern not found")
PYEOF
fi

echo ""
echo "=== Verifying all imports ==="
python3 - << 'PYEOF'
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
import sys
ok = True
for mod, pkg in [
    ("pyrogram",     "pyrogram (GitHub)"),
    ("pytgcalls",    "py-tgcalls"),
    ("nest_asyncio", "nest-asyncio"),
    ("fastapi",      "fastapi"),
    ("yt_dlp",       "yt-dlp"),
    ("aiohttp",      "aiohttp"),
    ("dotenv",       "python-dotenv"),
    ("py_yt",        "py-yt-search"),
]:
    try:
        m = __import__(mod)
        path = getattr(m, "__file__", "?")
        print(f"  OK  {pkg:25s} {path}")
    except Exception as e:
        print(f"  FAIL  {pkg:23s} {e}")
        ok = False
if not ok:
    sys.exit(1)
PYEOF

echo ""
echo "=== Done ==="
echo ""
echo "  1. Edit CONFIGURATION in blacmusicbot.py"
echo "  2. python3 gen_session.py"
echo "  3. python3 main.py"
echo "  4. python3 blacmusicbot.py"
