import json
import os
import html
import re
from datetime import datetime, timezone

import feedparser
import requests


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = "seen.json"


FEEDS = [
    {
        "name": "NIH News in Health",
        "category": "Medicine & Health",
        "url": "https://newsinhealth.nih.gov/rss",
    },
    {
        "name": "World Health Organization",
        "category": "Medicine & Health",
        "url": "https://www.who.int/rss-feeds/news-english.xml",
    },
    {
        "name": "MIT CSAIL",
        "category": "Science",
        "url": "https://web.mit.edu/newsoffice/topic/mitcomputers-rss.xml",
    },
    {
        "name": "The Guardian AI",
        "category": "AI & Technology",
        "url": "https://www.guardian.co.uk/technology/artificialintelligenceai/rss",
    },
    {
        "name": "European Central Bank",
        "category": "Economy",
        "url": "https://www.ecb.int/rss/press.html",
    },
    {
        "name": "Federal Reserve",
        "category": "Economy",
        "url": "https://www.fedinprint.org/rss/system.rss",
    },
    {
        "name": "BBC World",
        "category": "World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "name": "Reuters YouTube",
        "category": "World",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UChqUTb7kYRX8-EiaN3XFrSQ",
    },
    {
        "name": "Tasnim",
        "category": "Iran",
        "url": "https://www.tasnimnews.com/fa/rss/feed/0/8/0/%D9%85%D9%87%D9%85%D8%AA%D8%B1%DB%8C%D9%86-%D8%B9%D9%86%D8%A7%D9%88%DB%8C%D9%86",
    },
    {
        "name": "Radio Farda YouTube",
        "category": "Iran",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCqYCssczpdf9f9oNJPQKiIQ",
    },
    {
        "name": "BBC Persian YouTube",
        "category": "Iran",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCHZk9MrT3DGWmVqdsj5y0EA",
    },
]


def clean_text(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )

    response.raise_for_status()


def entry_id(entry):
    return (
        entry.get("id")
        or entry.get("guid")
        or entry.get("link")
        or entry.get("title")
    )


def main():
    old_state = load_state()

    if old_state is None:
        old_state = {}

    new_state = dict(old_state)

    first_run = len(old_state) == 0

    total_new = 0

    for feed in FEEDS:
        print(f"Checking: {feed['name']}")

        try:
            parsed = feedparser.parse(feed["url"])

            if parsed.bozo and not parsed.entries:
                print(f"  Feed error: {feed['name']}")
                continue

            feed_seen = set(old_state.get(feed["name"], []))
            current_ids = []

            for entry in parsed.entries[:20]:
                item_id = entry_id(entry)

                if not item_id:
                    continue

                current_ids.append(item_id)

                if item_id in feed_seen:
                    continue

                if first_run:
                    continue

                title = clean_text(entry.get("title", "Untitled"))
                link = entry.get("link", "")

                message = (
                    f"📰 {feed['category']}\n\n"
                    f"{title}\n\n"
                    f"منبع: {feed['name']}\n"
                    f"{link}"
                )

                try:
                    send_telegram(message)
                    total_new += 1
                    print(f"  Sent: {title}")

                except Exception as e:
                    print(f"  Telegram error: {e}")
                    continue

            if current_ids:
                # Keep only the latest 100 IDs for each feed
                combined = list(dict.fromkeys(current_ids + list(feed_seen)))
                new_state[feed["name"]] = combined[:100]

        except Exception as e:
            print(f"  Error: {e}")

    save_state(new_state)

    if first_run:
        print("First run completed: existing articles were recorded.")
    else:
        print(f"Completed. New articles sent: {total_new}")


if __name__ == "__main__":
    main()
