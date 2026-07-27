# routes/lyrics.py — GET /api/lyrics?q=<query> (or ?artist=&title=)
#
# Pairs naturally with the audio API but is intentionally independent of
# any YouTube video id — a bot can call this straight from a track's
# artist/title without resolving a video first.

from fastapi import APIRouter, Depends, HTTPException, Query

from blacapi import lyrics as lyrics_module
from blacapi import metadata
from blacapi.security import verify_api_key

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("/lyrics")
async def get_lyrics(
    q: str | None = Query(None, description="Freeform 'Artist - Title' (or 'Title by Artist') query"),
    artist: str | None = Query(None),
    title: str | None = Query(None),
):
    if not (q or (artist and title)):
        raise HTTPException(status_code=400, detail="Provide either ?q= or both ?artist= and ?title=")

    if artist and title:
        resolved_artist, resolved_title = artist, title
    else:
        resolved_artist, resolved_title = lyrics_module.split_artist_title(q)

    lyrics_text = None
    if resolved_artist and resolved_title:
        lyrics_text = await lyrics_module.fetch_lyrics(resolved_artist, resolved_title)

    if not lyrics_text and q:
        # No artist/title split worked, or lyrics.ovh didn't recognize that
        # split — fall back to a YouTube search to get a proper channel
        # name + cleaned title, then retry once with those.
        results = await metadata.search(q, 1)
        if results:
            seed_title = lyrics_module.split_artist_title(results[0].get("title", ""))[1] or results[0].get("title", "")
            seed_artist = results[0].get("channel", "")
            if seed_artist and seed_title:
                lyrics_text = await lyrics_module.fetch_lyrics(seed_artist, seed_title)
                if lyrics_text:
                    resolved_artist, resolved_title = seed_artist, seed_title

    if not lyrics_text:
        raise HTTPException(status_code=404, detail="Lyrics not found")

    return {
        "success": True,
        "artist": resolved_artist,
        "title": resolved_title,
        "lyrics": lyrics_text,
    }
