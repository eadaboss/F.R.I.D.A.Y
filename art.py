#!/usr/bin/env python3
"""
FRIDAY Daily Art
Pulls the latest Inspiragio video, fetches its transcript,
generates a museum-style description via Groq, sends to Telegram.
"""

import os
import re
import time
import logging
import requests
import feedparser

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Credentials ───────────────────────────────────────────────────────────────

GROQ_API_KEY          = os.environ["GROQ_API_KEY"]
TELEGRAM_BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
ART_CHAT_ID           = os.environ["ART_CHAT_ID"]   # separate chat from digest

# ── Config ────────────────────────────────────────────────────────────────────

INSPIRAGIO_CHANNEL_ID = "UCj-_77Q1UK8qx2XJaYILagA"
INSPIRAGIO_RSS        = f"https://www.youtube.com/feeds/videos.xml?channel_id={INSPIRAGIO_CHANNEL_ID}"
GROQ_MODEL            = "llama-3.3-70b-versatile"

# ── Fetch Latest Video from RSS ───────────────────────────────────────────────

def get_latest_video() -> dict | None:
    try:
        feed = feedparser.parse(INSPIRAGIO_RSS)
        if not feed.entries:
            log.error("No entries found in Inspiragio RSS feed.")
            return None
        entry = feed.entries[0]
        video_id = entry.yt_videoid if hasattr(entry, "yt_videoid") else entry.id.split(":")[-1]
        title = entry.title.strip()
        description = entry.get("summary", "")[:1000]
        thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        url = f"https://www.youtube.com/watch?v={video_id}"
        return {
            "video_id": video_id,
            "title": title,
            "description": description,
            "thumbnail": thumbnail,
            "url": url,
        }
    except Exception as ex:
        log.error(f"RSS fetch failed: {ex}")
        return None

# ── Fetch Transcript ──────────────────────────────────────────────────────────

def get_transcript(video_id: str) -> str:
    """
    Tries to fetch the YouTube transcript using youtube-transcript-api.
    Falls back gracefully if unavailable.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US"])
        full_text = " ".join([t["text"] for t in transcript_list])
        # Trim to ~3000 chars to keep Groq prompt reasonable
        return full_text[:3000]
    except Exception as ex:
        log.warning(f"Transcript unavailable: {ex}")
        return ""

# ── Groq: Generate Museum Description ────────────────────────────────────────

def call_groq(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": 900,
        "temperature": 0.7,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def generate_museum_card(video: dict, transcript: str) -> str:
    transcript_section = (
        f"\nVIDEO TRANSCRIPT (excerpt):\n{transcript}"
        if transcript
        else "\n(No transcript available — use the title and description only.)"
    )

    prompt = f"""You are a senior curator at a world-class art museum writing the wall card for a featured artwork.

Based on the information below from an art essay video, write a museum-style artwork description. Structure it as:

1. **[Artwork Title & Artist]** — a bold header line with the artwork name and artist if identifiable
2. **Medium & Period** — one line: medium, date/period, current location if known
3. **Description** — 2 rich paragraphs describing the artwork visually and contextually. Write as if guiding someone standing in front of it.
4. **Significance** — 1 paragraph on why this work matters historically or emotionally.
5. **Curator's Note** — 1 short atmospheric closing sentence.

Tone: formal, evocative, intelligent. Like the MET or the Louvre. No fluff, no filler.

VIDEO TITLE: {video['title']}
CHANNEL DESCRIPTION: {video['description']}
{transcript_section}"""

    try:
        return call_groq(prompt)
    except Exception as ex:
        log.error(f"Groq failed: {ex}")
        return f"*{video['title']}*\n\n_{video['description']}_"

# ── Telegram Delivery ─────────────────────────────────────────────────────────

def send_photo(photo_url: str, caption: str):
    """Send thumbnail image with caption."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    # Telegram captions max 1024 chars — trim if needed
    caption = caption[:1024]
    payload = {
        "chat_id": ART_CHAT_ID,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "Markdown",
    }
    r = requests.post(url, json=payload, timeout=15)
    if not r.ok:
        log.warning(f"Photo send failed: {r.text} — falling back to text only")
        return False
    return True

def send_text(text: str):
    """Send plain text message, splitting if needed."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = []
    while len(text) > 4000:
        split_at = text.rfind("\n", 0, 4000)
        if split_at == -1:
            split_at = 4000
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    chunks.append(text)

    for chunk in chunks:
        payload = {
            "chat_id": ART_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=15)
        if not r.ok:
            log.error(f"Text send failed: {r.text}")
        time.sleep(0.5)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("FRIDAY Art starting...")

    video = get_latest_video()
    if not video:
        send_text("🎨 *FRIDAY Daily Art*\n\n_Could not retrieve today's artwork. Check back tomorrow._")
        return

    log.info(f"Latest video: {video['title']}")

    transcript = get_transcript(video["video_id"])
    log.info(f"Transcript length: {len(transcript)} chars")

    museum_card = generate_museum_card(video, transcript)
    log.info("Museum card generated.")

    # Header
    header = "🖼️ *FRIDAY — Daily Art*\n─────────────────────────\n"

    # Footer with YouTube link
    footer = f"\n─────────────────────────\n[▶️ Watch the full essay]({video['url']})"

    full_text = header + museum_card + footer

    # Try sending as photo first, fall back to text
    # Use first 900 chars of museum card as photo caption
    short_caption = (header + museum_card)[:900] + f"\n\n[▶️ Watch essay]({video['url']})"
    photo_sent = send_photo(video["thumbnail"], short_caption)

    if not photo_sent:
        # Fallback: send full text without image
        send_text(full_text)

    log.info("Art digest complete.")

if __name__ == "__main__":
    main()
