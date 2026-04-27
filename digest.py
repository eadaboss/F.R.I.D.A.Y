#!/usr/bin/env python3
"""
F.R.I.D.A.Y Morning Digest — 100% Free Version
Uses Groq (free AI API) + Telegram + RSS feeds only.
No paid services required.
"""

import os
import json
import time
import hashlib
import logging
import requests
import feedparser
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Credentials (set these as GitHub Secrets) ─────────────────────────────────

GROQ_API_KEY      = os.environ["GROQ_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]

# ── Settings ──────────────────────────────────────────────────────────────────

MAX_ARTICLES_PER_SECTION = 6   # how many articles per section
HOURS_LOOKBACK = 26            # how far back to look (catches yesterday evening)
SEEN_CACHE = "/tmp/seen_articles.json"
GROQ_MODEL = "llama-3.3-70b-versatile"  # best free Groq model for summarization

# ── News Sections & RSS Feeds ─────────────────────────────────────────────────

SECTIONS = {

    "🌍 Geopolitics": {
        "feeds": [
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://rss.dw.com/xml/rss-en-world",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.reuters.com/reuters/worldNews",
            "https://foreignpolicy.com/feed/",
            "https://theintercept.com/feed/?rss",
            "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
            "https://feeds.bbci.co.uk/news/world/europe/rss.xml",
            "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
        ],
        "keywords": [
            "war", "conflict", "geopolit", "nato", "sanction", "treaty",
            "military", "invasion", "coup", "alliance", "diplomacy", "nuclear",
            "protest", "revolution", "uprising", "crisis", "ceasefire", "airstrike",
            "offensive", "troops", "missile", "drone strike", "occupation",
        ],
    },

    "🧱 BRICS & Emerging Powers": {
        "feeds": [
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.reuters.com/reuters/businessNews",
            "https://rss.dw.com/xml/rss-en-world",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://english.news.cn/home/rss/news.xml",
            "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",
            "https://feeds.feedburner.com/TheEconomist",
        ],
        "keywords": [
            "brics", "brazil", "russia", "india", "china", "south africa",
            "yuan", "de-dollarization", "emerging market", "global south",
            "shanghai cooperation", "belt and road", "g20", "new development bank",
            "renminbi", "petrodollar", "multipolar", "iran sanctions",
        ],
    },

    "📰 Mainstream Media Watch": {
        "feeds": [
            "https://feeds.bbci.co.uk/news/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "https://feeds.washingtonpost.com/rss/world",
            "https://feeds.foxnews.com/foxnews/latest",
            "https://www.npr.org/rss/rss.php?id=1001",
            "https://feeds.nbcnews.com/nbcnews/public/news",
            "https://www.cbsnews.com/latest/rss/main",
            "https://abcnews.go.com/abcnews/topstories",
        ],
        "keywords": [],  # no filter — grab whatever the major outlets are leading with
    },

    "🏙️ Ohio & Columbus": {
        "feeds": [
            "https://www.dispatch.com/rss",
            "https://www.10tv.com/feeds/syndication/rss/news",
            "https://www.nbc4i.com/feed/",
            "https://www.thisweeknews.com/feed/",
            "https://www.cleveland.com/arc/outboundfeeds/rss/",
            "https://www.daytondailynews.com/arc/outboundfeeds/rss/",
        ],
        "keywords": [
            "ohio", "columbus", "worthington", "franklin county", "ohio state",
            "osu", "governor", "statehouse", "cincinnati", "cleveland",
            "toledo", "dayton", "akron", "dewine", "legislature", "ohio senate",
            "ohio house", "columbus city council", "central ohio",
        ],
    },

    "🇪🇹 Ethiopia & Horn of Africa": {
        "feeds": [
            "https://www.ethiopiaobserver.com/feed/",
            "https://addisstandard.com/feed/",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.bbci.co.uk/news/world/africa/rss.xml",
            "https://rss.dw.com/xml/rss-en-africa",
            "https://feeds.reuters.com/reuters/worldNews",
        ],
        "keywords": [
            "ethiopia", "ethiopian", "addis ababa", "tigray", "amhara",
            "oromia", "eritrea", "somalia", "horn of africa", "nile",
            "grand renaissance dam", "gerd", "abiy ahmed", "fano",
            "oromo", "djibouti", "south sudan", "sudan",
        ],
    },

    "💻 Tech & AI Trends": {
        "feeds": [
            "https://feeds.feedburner.com/TechCrunch",
            "https://www.wired.com/feed/rss",
            "https://arstechnica.com/feed/",
            "https://feeds.feedburner.com/venturebeat/SZYF",
            "https://www.theverge.com/rss/index.xml",
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://rss.slashdot.org/Slashdot/slashdotMain",
            "https://www.technologyreview.com/feed/",
        ],
        "keywords": [
            "ai", "artificial intelligence", "machine learning", "llm", "openai",
            "anthropic", "google deepmind", "meta ai", "semiconductor", "robotics",
            "quantum", "cybersecurity", "startup", "funding", "ipo", "nvidia",
            "chatgpt", "gemini", "claude", "autonomous", "automation", "chip",
        ],
    },

    "💵 US Economics": {
        "feeds": [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://feeds.marketwatch.com/marketwatch/topstories/",
            "https://www.wsj.com/xml/rss/3_7031.xml",
            "https://feeds.feedburner.com/TheEconomist",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ],
        "keywords": [
            "fed", "federal reserve", "inflation", "gdp", "recession", "jobs",
            "unemployment", "interest rate", "treasury", "dollar", "debt",
            "deficit", "wall street", "stock market", "tariff", "trade",
            "cpi", "pce", "payroll", "powell", "yellen", "economy", "fiscal",
        ],
    },

    "🦅 US Foreign Policy": {
        "feeds": [
            "https://foreignpolicy.com/feed/",
            "https://feeds.reuters.com/reuters/worldNews",
            "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
            "https://www.state.gov/rss/services/press/feed.rss",
            "https://feeds.washingtonpost.com/rss/world",
            "https://theintercept.com/feed/?rss",
        ],
        "keywords": [
            "state department", "secretary of state", "pentagon", "nato",
            "foreign policy", "ambassador", "sanctions", "aid", "congress",
            "senate", "white house", "bilateral", "multilateral", "rubio",
            "blinken", "austin", "hegseth", "us troops", "us military",
            "foreign aid", "diplomacy", "us relations",
        ],
    },

    "🌐 Global Economics": {
        "feeds": [
            "https://feeds.feedburner.com/TheEconomist",
            "https://feeds.reuters.com/reuters/businessNews",
            "https://www.imf.org/en/News/rss?language=eng",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://rss.dw.com/xml/rss-en-business",
        ],
        "keywords": [
            "imf", "world bank", "wto", "trade war", "global growth", "oil",
            "energy", "commodity", "currency", "euro", "yen", "yuan",
            "debt crisis", "supply chain", "shipping", "global recession",
            "opec", "inflation global", "central bank", "interest rates global",
        ],
    },

    "🚨 Breaking & General Developments": {
        "feeds": [
            "https://feeds.bbci.co.uk/news/rss.xml",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.reuters.com/reuters/topNews",
            "https://apnews.com/rss",
            "https://rss.dw.com/xml/rss-en-world",
            "https://feeds.nbcnews.com/nbcnews/public/news",
        ],
        "keywords": [
            "breaking", "urgent", "earthquake", "hurricane", "tsunami",
            "attack", "explosion", "protest", "revolution", "coup",
            "emergency", "disaster", "outbreak", "assassination", "shooting",
            "flood", "wildfire", "volcano", "collapsed", "killed", "deadly",
            "hostage", "terror", "crash", "plane crash",
        ],
        "is_breaking": True,
    },
}

# ── Seen Article Cache (prevents duplicates across runs) ─────────────────────

def load_seen() -> set:
    try:
        with open(SEEN_CACHE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_seen(seen: set):
    with open(SEEN_CACHE, "w") as f:
        json.dump(list(seen)[-2000:], f)

def article_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

# ── RSS Fetching ──────────────────────────────────────────────────────────────

def is_recent(entry) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                dt = datetime(*t[:6], tzinfo=timezone.utc)
                return dt >= cutoff
            except Exception:
                pass
    return True  # no date = include it

def fetch_rss(url: str) -> list:
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "F.R.I.D.A.YDigest/1.0"})
        articles = []
        for e in feed.entries[:25]:
            link = getattr(e, "link", "")
            title = getattr(e, "title", "").strip()
            summary = getattr(e, "summary", "")[:400]
            if link and title and is_recent(e):
                articles.append({"title": title, "url": link, "summary": summary})
        return articles
    except Exception as ex:
        log.warning(f"RSS fail {url}: {ex}")
        return []

def keyword_match(article: dict, keywords: list) -> bool:
    if not keywords:
        return True
    text = (article["title"] + " " + article.get("summary", "")).lower()
    return any(kw.lower() in text for kw in keywords)

def collect_section(cfg: dict, seen: set) -> list:
    raw = []
    for url in cfg.get("feeds", []):
        raw.extend(fetch_rss(url))
        time.sleep(0.3)

    filtered = [a for a in raw if keyword_match(a, cfg.get("keywords", []))]

    unique = []
    for a in filtered:
        h = article_hash(a["url"])
        if h not in seen:
            seen.add(h)
            unique.append(a)

    return unique[:MAX_ARTICLES_PER_SECTION]

# ── Groq AI Summarization ─────────────────────────────────────────────────────

def call_groq(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": 900,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

def summarize_section(section_name: str, articles: list, is_breaking: bool = False) -> str:
    if not articles:
        return f"*{section_name}*\n_No new developments in the past 24h._\n"

    article_list = "\n".join(
        f"{i+1}. TITLE: {a['title']}\n   URL: {a['url']}\n   SNIPPET: {a.get('summary', '')}"
        for i, a in enumerate(articles)
    )

    urgency_note = "Flag anything urgent or major with 🔴 at the start of that bullet." if is_breaking else ""

    prompt = f"""You are F.R.I.D.A.Y, a sharp AI briefing assistant delivering a morning news digest.

Summarize the following articles for the section: "{section_name}"

Rules:
- Write exactly 1-2 sentences per article.
- Format each as: • [Article headline](URL) — your summary sentence.
- Group closely related stories together.
- Be direct and factual — no fluff, no filler phrases.
- Do not invent any facts beyond the title and snippet.
- Do not add any intro or outro text — return ONLY the bullet list.
{urgency_note}

ARTICLES:
{article_list}"""

    try:
        body = call_groq(prompt)
        return f"*{section_name}*\n{body}\n"
    except Exception as ex:
        log.error(f"Groq fail for {section_name}: {ex}")
        # fallback: just send the raw links
        fallback = "\n".join(f"• [{a['title']}]({a['url']})" for a in articles)
        return f"*{section_name}*\n{fallback}\n"

# ── Telegram Delivery ─────────────────────────────────────────────────────────

def send_telegram(text: str):
    """Send message, auto-splitting if over Telegram's 4096 char limit."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = []
    while len(text) > 4000:
        split_at = text.rfind("\n", 0, 4000)
        if split_at == -1:
            split_at = 4000
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    chunks.append(text)

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=15)
        if not r.ok:
            log.error(f"Telegram chunk {i} failed: {r.text}")
        time.sleep(0.5)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("F.R.I.D.A.Y Digest starting...")
    seen = load_seen()
    now = datetime.now().strftime("%A, %B %d %Y — %I:%M %p")

    # Header message
    send_telegram(
        f"🤖 *F.R.I.D.A.Y Morning Digest*\n"
        f"_{now}_\n"
        f"{'─' * 28}\n"
    )

    for section_name, cfg in SECTIONS.items():
        log.info(f"Processing: {section_name}")
        articles = collect_section(cfg, seen)
        log.info(f"  → {len(articles)} articles found")
        summary = summarize_section(section_name, articles, is_breaking=cfg.get("is_breaking", False))
        send_telegram(summary)
        time.sleep(1.5)  # small buffer between Groq calls

    # Footer
    send_telegram("─" * 28 + "\n_End of digest. — F.R.I.D.A.Y_")

    save_seen(seen)
    log.info("Digest complete.")

if __name__ == "__main__":
    main()
