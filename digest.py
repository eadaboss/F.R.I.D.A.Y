#!/usr/bin/env python3
"""
JARVIS Morning Digest
Scrapes news by category, summarizes via Claude API, sends to Telegram.
"""

import os
import json
import time
import hashlib
import logging
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from anthropic import Anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")  # optional free tier

MAX_ARTICLES_PER_SECTION = 6
HOURS_LOOKBACK = 26  # catch articles from yesterday evening too
SEEN_CACHE = "/tmp/seen_articles.json"

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ── RSS Feed Sources by Section ───────────────────────────────────────────────

SECTIONS = {
    "🌍 Geopolitics": {
        "feeds": [
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://rss.dw.com/xml/rss-en-world",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.reuters.com/reuters/worldNews",
            "https://foreignpolicy.com/feed/",
            "https://theintercept.com/feed/?rss",
        ],
        "keywords": ["war", "conflict", "geopolit", "nato", "sanction", "treaty",
                     "military", "invasion", "coup", "alliance", "diplomacy", "nuclear",
                     "protest", "revolution", "uprising", "crisis", "ceasefire"],
        "newsapi_query": "geopolitics OR war OR conflict OR coup OR revolution OR sanctions",
    },
    "🧱 BRICS & Emerging Powers": {
        "feeds": [
            "https://www.bricsinformation.com/feed",
            "https://feeds.reuters.com/reuters/businessNews",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://rss.dw.com/xml/rss-en-world",
            "https://english.news.cn/home/rss/news.xml",  # Xinhua
        ],
        "keywords": ["brics", "brazil", "russia", "india", "china", "south africa",
                     "yuan", "de-dollarization", "emerging market", "global south",
                     "shanghai cooperation", "belt and road", "g20"],
        "newsapi_query": "BRICS OR \"de-dollarization\" OR \"global south\" OR \"emerging markets\"",
    },
    "📰 Mainstream Media Watch": {
        "feeds": [
            "https://feeds.bbci.co.uk/news/rss.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "https://feeds.washingtonpost.com/rss/world",
            "https://feeds.foxnews.com/foxnews/latest",
            "https://www.npr.org/rss/rss.php?id=1001",
            "https://feeds.nbcnews.com/nbcnews/public/news",
        ],
        "keywords": [],  # grab top headlines, no keyword filter
        "newsapi_query": "",
        "top_headlines": True,
    },
    "🏙️ Ohio & Columbus": {
        "feeds": [
            "https://www.dispatch.com/rss",
            "https://www.10tv.com/feeds/syndication/rss/news",
            "https://www.nbc4i.com/feed/",
            "https://www.wbns10tv.com/rss/",
            "https://www.thisweekworthington.com/feed/",
        ],
        "keywords": ["ohio", "columbus", "worthington", "franklin county", "ohio state",
                     "osu", "governor", "statehouse", "cincinnati", "cleveland",
                     "toledo", "dayton", "akron"],
        "newsapi_query": "Ohio OR Columbus city news",
    },
    "🇪🇹 Ethiopian & Horn of Africa": {
        "feeds": [
            "https://www.ethiopiaobserver.com/feed/",
            "https://addisstandard.com/feed/",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.bbci.co.uk/news/world/africa/rss.xml",
            "https://rss.dw.com/xml/rss-en-africa",
        ],
        "keywords": ["ethiopia", "ethiopian", "addis ababa", "tigray", "amhara",
                     "oromia", "eritrea", "somalia", "horn of africa", "nile",
                     "grand renaissance dam", "gerd", "abiy ahmed"],
        "newsapi_query": "Ethiopia OR \"Horn of Africa\" OR Tigray OR Abiy",
    },
    "💻 Tech & AI Trends": {
        "feeds": [
            "https://feeds.feedburner.com/TechCrunch",
            "https://www.wired.com/feed/rss",
            "https://arstechnica.com/feed/",
            "https://feeds.feedburner.com/venturebeat/SZYF",
            "https://www.theverge.com/rss/index.xml",
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
        ],
        "keywords": ["ai", "artificial intelligence", "machine learning", "llm", "openai",
                     "anthropic", "google deepmind", "semiconductor", "robotics",
                     "quantum", "cybersecurity", "startup", "funding", "ipo"],
        "newsapi_query": "AI OR \"artificial intelligence\" OR LLM OR OpenAI OR tech trends",
    },
    "💵 US Economics": {
        "feeds": [
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://feeds.reuters.com/reuters/businessNews",
            "https://feeds.marketwatch.com/marketwatch/topstories/",
            "https://www.wsj.com/xml/rss/3_7031.xml",
            "https://feeds.feedburner.com/TheEconomist",
        ],
        "keywords": ["fed", "federal reserve", "inflation", "gdp", "recession", "jobs",
                     "unemployment", "interest rate", "treasury", "dollar", "debt",
                     "deficit", "wall street", "stock market", "tariff", "trade deficit"],
        "newsapi_query": "US economy OR Federal Reserve OR inflation OR recession OR GDP",
    },
    "🦅 US Foreign Policy": {
        "feeds": [
            "https://foreignpolicy.com/feed/",
            "https://feeds.reuters.com/reuters/worldNews",
            "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
            "https://www.state.gov/rss/services/press/feed.rss",
            "https://feeds.washingtonpost.com/rss/world",
        ],
        "keywords": ["state department", "secretary of state", "pentagon", "nato",
                     "foreign policy", "ambassador", "sanctions", "aid", "congress",
                     "senate", "white house", "pentagon", "bilateral", "multilateral"],
        "newsapi_query": "\"US foreign policy\" OR \"State Department\" OR \"Pentagon\" OR NATO",
    },
    "🌐 Global Economics": {
        "feeds": [
            "https://feeds.feedburner.com/TheEconomist",
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://feeds.reuters.com/reuters/businessNews",
            "https://www.imf.org/en/News/rss?language=eng",
            "https://feeds.ft.com/rss/home/us",
        ],
        "keywords": ["imf", "world bank", "wto", "trade war", "global growth", "oil",
                     "energy", "commodity", "currency", "euro", "yen", "yuan",
                     "debt crisis", "supply chain", "shipping", "global recession"],
        "newsapi_query": "global economy OR IMF OR World Bank OR trade war OR commodity prices",
    },
    "🚨 Breaking & General Developments": {
        "feeds": [
            "https://feeds.bbci.co.uk/news/rss.xml",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://feeds.reuters.com/reuters/topNews",
            "https://apnews.com/rss",
            "https://rss.dw.com/xml/rss-en-world",
        ],
        "keywords": ["breaking", "urgent", "earthquake", "hurricane", "tsunami",
                     "attack", "explosion", "protest", "revolution", "coup",
                     "emergency", "disaster", "outbreak", "assassination"],
        "newsapi_query": "breaking news OR emergency OR disaster OR revolution OR coup",
        "is_breaking": True,
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_seen() -> set:
    try:
        with open(SEEN_CACHE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_seen(seen: set):
    with open(SEEN_CACHE, "w") as f:
        json.dump(list(seen)[-2000:], f)  # keep last 2000 hashes

def article_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def is_recent(entry) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            dt = datetime(*t[:6], tzinfo=timezone.utc)
            return dt >= cutoff
    return True  # no date = include it

def fetch_rss(url: str) -> list[dict]:
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "JARVISDigest/1.0"})
        articles = []
        for e in feed.entries[:20]:
            link = getattr(e, "link", "")
            title = getattr(e, "title", "").strip()
            summary = getattr(e, "summary", "")[:300]
            if link and title and is_recent(e):
                articles.append({"title": title, "url": link, "summary": summary})
        return articles
    except Exception as ex:
        log.warning(f"RSS fail {url}: {ex}")
        return []

def fetch_newsapi(query: str, top: bool = False) -> list[dict]:
    if not NEWSAPI_KEY or not query:
        return []
    try:
        endpoint = "top-headlines" if top else "everything"
        params = {
            "apiKey": NEWSAPI_KEY,
            "language": "en",
            "pageSize": 20,
        }
        if top:
            params["q"] = query or "world"
            params["country"] = "us"
        else:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)).strftime("%Y-%m-%dT%H:%M:%SZ")
            params["q"] = query
            params["from"] = cutoff
            params["sortBy"] = "publishedAt"
        r = requests.get(f"https://newsapi.org/v2/{endpoint}", params=params, timeout=10)
        data = r.json()
        articles = []
        for a in data.get("articles", []):
            if a.get("title") and a.get("url") and "[Removed]" not in a.get("title", ""):
                articles.append({
                    "title": a["title"],
                    "url": a["url"],
                    "summary": a.get("description", "")[:300],
                })
        return articles
    except Exception as ex:
        log.warning(f"NewsAPI fail: {ex}")
        return []

def keyword_match(article: dict, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text = (article["title"] + " " + article.get("summary", "")).lower()
    return any(kw.lower() in text for kw in keywords)

def collect_section(name: str, cfg: dict, seen: set) -> list[dict]:
    raw = []
    # RSS
    for url in cfg.get("feeds", []):
        raw.extend(fetch_rss(url))
        time.sleep(0.3)
    # NewsAPI
    raw.extend(fetch_newsapi(cfg.get("newsapi_query", ""), top=cfg.get("top_headlines", False)))
    # Filter by keywords
    filtered = [a for a in raw if keyword_match(a, cfg.get("keywords", []))]
    # Dedupe by URL hash
    unique = []
    for a in filtered:
        h = article_hash(a["url"])
        if h not in seen:
            seen.add(h)
            unique.append(a)
    # Limit
    return unique[:MAX_ARTICLES_PER_SECTION]

# ── Claude Summarization ──────────────────────────────────────────────────────

def summarize_section(section_name: str, articles: list[dict], is_breaking: bool = False) -> str:
    if not articles:
        return f"{section_name}\n_No new developments in the past 24h._\n"

    article_list = "\n".join(
        f"{i+1}. TITLE: {a['title']}\n   URL: {a['url']}\n   SNIPPET: {a.get('summary','')}"
        for i, a in enumerate(articles)
    )

    urgency = "Be especially concise and punchy — flag anything urgent." if is_breaking else ""

    prompt = f"""You are JARVIS, an AI briefing assistant. Summarize the following news articles for the section "{section_name}".

Rules:
- Write 1-2 sentence summary per article.
- Format each as: • [Linked headline](URL) — your summary sentence.
- Group closely related stories together.
- Flag breaking/urgent stories with 🔴 at the start.
- Be direct and informative, no fluff.
- Do NOT invent facts beyond what's in the snippet/title.
{urgency}

ARTICLES:
{article_list}

Return ONLY the formatted bullet list, no intro text."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        body = response.content[0].text.strip()
        return f"*{section_name}*\n{body}\n"
    except Exception as ex:
        log.error(f"Claude fail for {section_name}: {ex}")
        fallback = "\n".join(f"• [{a['title']}]({a['url']})" for a in articles)
        return f"*{section_name}*\n{fallback}\n"

# ── Telegram Delivery ─────────────────────────────────────────────────────────

def send_telegram(text: str):
    """Send a message, splitting if over Telegram's 4096 char limit."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = []
    while len(text) > 4000:
        # split at last newline before 4000
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
            log.error(f"Telegram send failed chunk {i}: {r.text}")
        time.sleep(0.5)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("JARVIS Digest starting...")
    seen = load_seen()
    now = datetime.now().strftime("%A, %B %d %Y — %I:%M %p")

    header = (
        f"🤖 *JARVIS Morning Digest*\n"
        f"_{now}_\n"
        f"{'─' * 30}\n"
    )
    send_telegram(header)

    for section_name, cfg in SECTIONS.items():
        log.info(f"Collecting: {section_name}")
        articles = collect_section(section_name, cfg, seen)
        log.info(f"  → {len(articles)} articles")

        summary = summarize_section(section_name, articles, is_breaking=cfg.get("is_breaking", False))
        send_telegram(summary)
        time.sleep(1)  # rate limit buffer

    footer = "─" * 30 + "\n_End of digest. Stay informed. — JARVIS_"
    send_telegram(footer)

    save_seen(seen)
    log.info("Digest complete.")

if __name__ == "__main__":
    main()
