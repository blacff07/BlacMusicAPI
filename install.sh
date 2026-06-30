#!/bin/bash
# install.sh — Run once before starting the bot.
# Handles all known Python 3.14 / Ubuntu compatibility issues.

echo "=== Blac Music API Install ==="
echo ""

echo "[1/5] Removing conflicting packages..."
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
echo "[2/5] Installing base packages..."
pip3 install -r requirements.txt \
    --break-system-packages \
    --ignore-installed \
    --quiet \
    --root-user-action=ignore
echo "  Done."

echo ""
echo "[3/5] Installing pyrogram from GitHub..."
SITE=$(python3 -c "import sysconfig; print(sysconfig.get_path('purelib'))")
pip3 install \
    "git+https://github.com/pyrogram/pyrogram.git" \
    --target="$SITE" \
    --upgrade \
    --quiet \
    --root-user-action=ignore
echo "  Installed to: $SITE"

echo ""
echo "[4/5] Installing py-tgcalls and applying patches..."
pip3 install "py-tgcalls==2.2.11" \
    --break-system-packages \
    --ignore-installed \
    --quiet \
    --root-user-action=ignore

TGCALLS_DIR=$(find /usr/local/lib/python3*/dist-packages/pytgcalls \
                   /usr/lib/python3*/dist-packages/pytgcalls \
                   -maxdepth 0 -type d 2>/dev/null | head -1)

if [ -z "$TGCALLS_DIR" ]; then
    echo "  ERROR: pytgcalls directory not found after install"
    exit 1
fi

SYNC_PY="$TGCALLS_DIR/sync.py"
if [ -f "$SYNC_PY" ]; then
    if grep -q "new_event_loop" "$SYNC_PY"; then
        echo "  sync.py: already patched"
    else
        python3 - "$SYNC_PY" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()
old = "    main_loop = asyncio.get_event_loop()"
new = (
    "    try:\n"
    "        main_loop = asyncio.get_event_loop()\n"
    "        if main_loop.is_closed():\n"
    "            raise RuntimeError('loop closed')\n"
    "    except RuntimeError:\n"
    "        main_loop = asyncio.new_event_loop()\n"
    "        asyncio.set_event_loop(main_loop)"
)
if old in src:
    with open(path, "w") as f:
        f.write(src.replace(old, new))
    print("  sync.py: patched OK")
else:
    print("  sync.py: target line not found (may already be fixed)")
PYEOF
    fi
fi

PYRO_CLIENT="$TGCALLS_DIR/mtproto/pyrogram_client.py"
if [ -f "$PYRO_CLIENT" ]; then
    if grep -q "class GroupcallForbidden" "$PYRO_CLIENT"; then
        echo "  pyrogram_client.py: already patched"
    elif grep -q "GroupcallForbidden" "$PYRO_CLIENT"; then
        python3 - "$PYRO_CLIENT" << 'PYEOF'
import sys, re
path = sys.argv[1]
with open(path) as f:
    src = f.read()
stub = (
    "# GroupcallForbidden was removed from pyrogram master — stub for compatibility\n"
    "try:\n"
    "    from pyrogram.errors import GroupcallForbidden\n"
    "except ImportError:\n"
    "    class GroupcallForbidden(Exception):\n"
    "        pass\n"
)
patched = re.sub(r'from pyrogram\.errors import GroupcallForbidden\n', '', src)
patched = stub + patched
with open(path, "w") as f:
    f.write(patched)
print("  pyrogram_client.py: patched OK")
PYEOF
    else
        echo "  pyrogram_client.py: no patch needed"
    fi
fi
echo "  Done."

echo ""
echo "[5/5] Verifying imports..."
python3 - << 'PYEOF'
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
import sys

ok = True
checks = [
    ("pyrogram",     "pyrogram (GitHub)"),
    ("pytgcalls",    "py-tgcalls 2.2.11"),
    ("nest_asyncio", "nest-asyncio"),
    ("fastapi",      "fastapi"),
    ("uvicorn",      "uvicorn"),
    ("yt_dlp",       "yt-dlp"),
    ("aiohttp",      "aiohttp"),
    ("dotenv",       "python-dotenv"),
    ("py_yt",        "py-yt-search"),
]
for mod, label in checks:
    try:
        __import__(mod)
        print(f"  OK    {label}")
    except Exception as e:
        print(f"  FAIL  {label}: {e}")
        ok = False

if not ok:
    print("\nOne or more packages failed. Run bash install.sh again.")
    sys.exit(1)
else:
    print("\n  All imports OK.")
PYEOF

echo ""
echo "=== Install complete ==="
echo ""
echo "  1. Edit CONFIGURATION in blacmusicbot.py"
echo "  2. python3 gen_session.py"
echo "  3. python3 main.py          (start API server)"
echo "  4. python3 blacmusicbot.py  (start bot)"
