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
            "parse_mode": "HTML",
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


def get_category_icon(category):
    icons = {
        "Medicine & Health": "🩺",
        "Science": "🔬",
        "AI & Technology": "🤖",
        "Economy": "💰",
        "World": "🌍",
        "Iran": "🇮🇷",
    }

    return icons.get(category, "📰")


def get_published_time(entry):
    parsed_time = None

    if entry.get("published_parsed"):
        parsed_time = entry.published_parsed
    elif entry.get("updated_parsed"):
        parsed_time = entry.updated_parsed

    if not parsed_time:
        return ""

    try:
        dt = datetime(
            parsed_time.tm_year,
            parsed_time.tm_mon,
            parsed_time.tm_mday,
            parsed_time.tm_hour,
            parsed_time.tm_min,
            parsed_time.tm_sec,
            tzinfo=timezone.utc,
        )

        return dt.strftime("%Y-%m-%d %H:%M UTC")

    except Exception:
        return ""


def create_message(feed, entry):
    category = feed["category"]
    name = feed["name"]

    title = clean_text(entry.get("title", "Untitled"))
    link = entry.get("link", "")

    icon = get_category_icon(category)
    published = get_published_time(entry)

    is_youtube = "YouTube" in name

    if is_youtube:
        link_text = "▶️ مشاهده ویدئو"
    else:
        link_text = "🔗 مطالعه خبر"

    message = (
        f"<b>{icon} {html.escape(category.upper())}</b>\n\n"
        f"<b>{html.escape(title)}</b>\n\n"
        f"📰 {html.escape(name)}"
    )

    if published:
        message += f"\n🕒 {published}"

    if link:
        safe_link = html.escape(link, quote=True)
        message += f'\n\n<a href="{safe_link}">{link_text}</a>'

    return message


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

                message = create_message(feed, entry)

                try:
                    send_telegram(message)
                    total_new += 1

                    print(
                        f"  Sent: {clean_text(entry.get('title', 'Untitled'))}"
                    )

                except Exception as e:
                    print(f"  Telegram error: {e}")
                    continue

            if current_ids:
                combined = list(
                    dict.fromkeys(current_ids + list(feed_seen))
                )
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
