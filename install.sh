#!/bin/bash
# install.sh — run this once to set up all dependencies

set -e

echo "Removing conflicting system pyrogram files..."

# The system pyrogram sits at a fixed path and cannot be removed by pip.
# We delete it directly so kurigram can take its place.
PYRO_PATH="/usr/local/lib/python3.14/dist-packages/pyrogram"
PYRO_DIST="/usr/local/lib/python3.14/dist-packages/Pyrogram-2.0.106.dist-info"

if [ -d "$PYRO_PATH" ]; then
    rm -rf "$PYRO_PATH"
    echo "  Removed: $PYRO_PATH"
fi

if [ -d "$PYRO_DIST" ]; then
    rm -rf "$PYRO_DIST"
    echo "  Removed: $PYRO_DIST"
fi

# Also remove from any other common dist-packages paths
for path in \
    /usr/lib/python3/dist-packages/pyrogram \
    /usr/local/lib/python3*/dist-packages/pyrogram \
    /usr/lib/python3*/dist-packages/pyrogram
do
    if [ -d "$path" ]; then
        rm -rf "$path"
        echo "  Removed: $path"
    fi
done

echo ""
echo "Installing dependencies..."
pip3 install -r requirements.txt \
    --break-system-packages \
    --ignore-installed

echo ""
echo "Verifying kurigram is active..."
python3 -c "
import importlib.metadata
try:
    v = importlib.metadata.version('kurigram')
    print(f'  kurigram {v} — OK')
except Exception:
    print('  WARNING: kurigram not found')
import pyrogram
import importlib.util
spec = importlib.util.find_spec('pyrogram')
print(f'  pyrogram loaded from: {spec.origin}')
"

echo ""
echo "Done. Run: python3 blacmusicbot.py"
