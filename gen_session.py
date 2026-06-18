# gen_session.py — Generate the assistant session string
# Run once with the secondary Telegram account that joins voice chats.
# Paste the output into ASSISTANT_SESSION in blacmusicbot.py.
#
# Usage: python3 gen_session.py

import asyncio
import sys
import os

print("Blac Music Bot — Session String Generator")
print("-" * 45)
print("Enter your credentials from https://my.telegram.org")
print("")

try:
    api_id   = int(input("API_ID   : ").strip())
    api_hash = input("API_HASH : ").strip()
except (ValueError, EOFError):
    print("Invalid input.")
    sys.exit(1)

async def generate():
    try:
        from pyrogram import Client
    except ImportError:
        print("ERROR: pyrogram not installed. Run: bash install.sh")
        sys.exit(1)

    print("")
    print("Logging in with your SECONDARY account...")
    print("")

    async with Client("_tmp_session", api_id=api_id, api_hash=api_hash) as client:
        session_string = await client.export_session_string()

    print("")
    print("=" * 60)
    print("SESSION STRING:")
    print("=" * 60)
    print(session_string)
    print("=" * 60)
    print("")
    print("Paste this into ASSISTANT_SESSION in blacmusicbot.py")

    for f in ["_tmp_session.session", "_tmp_session.session-journal"]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

asyncio.run(generate())
