import os
import sys
import json
import time
import html
import re
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

import feedparser
import requests


# =========================================================
# CONFIG
# =========================================================

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

SEEN_FILE = "seen.json"
PENDING_FILE = "pending_news.json"

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))

MAX_ARTICLES_PER_FEED = 20

# Maximum number of collected articles sent to AI
MAX_ARTICLES_FOR_AI = 25

# Minimum importance kept after AI analysis
MIN_IMPORTANCE = 3

# Maximum final news items in Telegram digest
MAX_FINAL_NEWS = 10

# Batch size for Groq
BATCH_SIZE = 5

# Timeouts
GROQ_REQUEST_TIMEOUT = 60
FINAL_EDITOR_TIMEOUT = 60
TELEGRAM_TIMEOUT = 30

# Retries
MAX_GROQ_RETRIES = 3

# Delay between Groq batches
GROQ_DELAY_SECONDS = 8


# =========================================================
# FEEDS
# =========================================================

FEEDS = [
    {
        "name": "NIH News in Health",
        "category": "پزشکی و سلامت",
        "url": "https://newsinhealth.nih.gov/rss",
    },
    {
        "name": "WHO",
        "category": "پزشکی و سلامت",
        "url": "https://www.who.int/rss-feeds/news-english.xml",
    },
    {
        "name": "MIT CSAIL",
        "category": "علم",
        "url": "https://web.mit.edu/newsoffice/topic/mitcomputers-rss.xml",
    },
    {
        "name": "The Guardian AI",
        "category": "هوش مصنوعی و فناوری",
        "url": "https://www.guardian.co.uk/technology/artificialintelligenceai/rss",
    },
    {
        "name": "ECB",
        "category": "اقتصاد و بازارها",
        "url": "https://www.ecb.int/rss/press.html",
    },
    {
        "name": "Federal Reserve",
        "category": "اقتصاد و بازارها",
        "url": "https://www.fedinprint.org/rss/system.rss",
    },
    {
        "name": "BBC World",
        "category": "جهان",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "name": "Reuters",
        "category": "جهان",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UChqUTb7kYRX8-EiaN3XFrSQ",
    },
    {
        "name": "Tasnim",
        "category": "ایران",
        "url": "https://www.tasnimnews.com/fa/rss/feed/0/8/0/%D9%85%D9%87%D9%85%D8%AA%D8%B1%DB%8C%D9%86-%D8%B9%D9%86%D8%A7%D9%88%DB%8C%D9%86",
    },
    {
        "name": "Radio Farda",
        "category": "ایران",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCqYCssczpdf9f9oNJPQKiIQ",
    },
    {
        "name": "BBC Persian",
        "category": "ایران",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCHZk9MrT3DGWmVqdsj5y0EA",
    },
]


# =========================================================
# HELPERS
# =========================================================

def normalize_text(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def escape(text):
    return html.escape(str(text), quote=False)


def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"WARNING: Could not read {filename}: {e}", flush=True)
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def article_similarity(a, b):
    text_a = normalize_text(
        f"{a.get('title', '')} {a.get('summary', '')}"
    ).lower()

    text_b = normalize_text(
        f"{b.get('title', '')} {b.get('summary', '')}"
    ).lower()

    if not text_a or not text_b:
        return 0

    return SequenceMatcher(None, text_a, text_b).ratio()


def is_duplicate(article, articles, threshold=0.75):
    for existing in articles:
        if article_similarity(article, existing) >= threshold:
            return True

    return False


def get_entry_date(entry):
    """
    Try several RSS date fields and convert to Iran time.
    """
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field)

        if parsed:
            try:
                dt = datetime(
                    parsed.tm_year,
                    parsed.tm_mon,
                    parsed.tm_mday,
                    parsed.tm_hour,
                    parsed.tm_min,
                    parsed.tm_sec,
                    tzinfo=timezone.utc,
                )

                return dt.astimezone(IRAN_TZ)

            except Exception:
                pass

    return None


def today_iran():
    return datetime.now(IRAN_TZ).date()


def clean_url(url):
    if not url:
        return ""

    return str(url).strip()


# =========================================================
# RSS COLLECTION
# =========================================================

def collect_news():
    print("DEBUG: starting news collection...", flush=True)

    seen = load_json(SEEN_FILE, [])
    pending = load_json(PENDING_FILE, [])

    if not isinstance(seen, list):
        seen = []

    if not isinstance(pending, list):
        pending = []

    today = today_iran()

    collected = []
    total_feeds = len(FEEDS)

    for feed_index, feed_info in enumerate(FEEDS, start=1):

        print(
            f"\nDEBUG: collecting feed {feed_index}/{total_feeds}: "
            f"{feed_info['name']}",
            flush=True,
        )

        try:
            parsed = feedparser.parse(feed_info["url"])

            if getattr(parsed, "bozo", False):
                print(
                    f"WARNING: feed parser warning for "
                    f"{feed_info['name']}",
                    flush=True,
                )

            entries = parsed.entries[:MAX_ARTICLES_PER_FEED]

            print(
                f"DEBUG: {len(entries)} entries found",
                flush=True,
            )

            for entry in entries:

                title = normalize_text(
                    entry.get("title", "")
                )

                url = clean_url(
                    entry.get("link", "")
                )

                if not title or not url:
                    continue

                published_dt = get_entry_date(entry)

                if published_dt is None:
                    continue

                if published_dt.date() != today:
                    continue

                article_id = url

                if article_id in seen:
                    continue

                if any(
                    x.get("id") == article_id
                    for x in pending
                ):
                    continue

                summary = normalize_text(
                    entry.get("summary", "")
                )

                content = normalize_text(
                    entry.get("description", "")
                )

                if not content:
                    content = summary

                article = {
                    "id": article_id,
                    "title": title,
                    "url": url,
                    "source": feed_info["name"],
                    "category": feed_info["category"],
                    "published": published_dt.isoformat(),
                    "summary": summary,
                    "content": content,
                }

                if is_duplicate(article, collected):
                    continue

                if is_duplicate(article, pending):
                    continue

                collected.append(article)

        except Exception as e:
            print(
                f"ERROR collecting {feed_info['name']}: {e}",
                flush=True,
            )

    # Sort newest first
    collected.sort(
        key=lambda x: x.get("published", ""),
        reverse=True,
    )

    print(
        f"\nDEBUG: collected {len(collected)} new articles",
        flush=True,
    )

    if collected:
        pending.extend(collected)

    # Keep pending reasonably bounded
    pending = pending[-200:]

    save_json(PENDING_FILE, pending)
    save_json(SEEN_FILE, seen)

    print(
        f"DEBUG: pending queue now contains "
        f"{len(pending)} articles",
        flush=True,
    )


# =========================================================
# GROQ REQUEST
# =========================================================

def groq_request(messages, timeout=GROQ_REQUEST_TIMEOUT):
    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {
            "type": "json_object"
        },
    }

    for attempt in range(1, MAX_GROQ_RETRIES + 1):

        print(
            f"DEBUG: Groq request starting "
            f"(attempt {attempt})...",
            flush=True,
        )

        try:
            response = requests.post(
                GROQ_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            print(
                f"DEBUG: Groq response received "
                f"with HTTP {response.status_code}",
                flush=True,
            )

            # -----------------------------------------
            # RATE LIMIT DIAGNOSTICS
            # -----------------------------------------

            if response.status_code == 429:

                print(
                    "========== GROQ RATE LIMIT ==========",
                    flush=True,
                )

                print(
                    "Response body:",
                    flush=True,
                )

                print(
                    response.text[:3000],
                    flush=True,
                )

                print(
                    "Relevant response headers:",
                    flush=True,
                )

                rate_headers = [
                    "retry-after",
                    "x-ratelimit-limit-requests",
                    "x-ratelimit-remaining-requests",
                    "x-ratelimit-reset-requests",
                    "x-ratelimit-limit-tokens",
                    "x-ratelimit-remaining-tokens",
                    "x-ratelimit-reset-tokens",
                ]

                for header_name in rate_headers:

                    value = response.headers.get(
                        header_name
                    )

                    if value is not None:

                        print(
                            f"{header_name}: {value}",
                            flush=True,
                        )

                print(
                    "======================================",
                    flush=True,
                )

                if attempt < MAX_GROQ_RETRIES:

                    retry_after = response.headers.get(
                        "retry-after"
                    )

                    try:
                        wait_time = float(
                            retry_after
                        )
                    except (
                        TypeError,
                        ValueError
                    ):
                        wait_time = 30 * attempt

                    wait_time = max(
                        5,
                        min(wait_time, 180)
                    )

                    print(
                        f"Rate limit. Waiting "
                        f"{wait_time}s...",
                        flush=True,
                    )

                    time.sleep(wait_time)
                    continue

                raise RuntimeError(
                    "Groq rate limit persisted after "
                    "maximum retries."
                )

            # -----------------------------------------
            # OTHER HTTP ERRORS
            # -----------------------------------------

            if response.status_code >= 400:

                try:
                    detail = response.json()
                except Exception:
                    detail = response.text

                raise RuntimeError(
                    f"Groq HTTP {response.status_code}: "
                    f"{detail}"
                )

            # -----------------------------------------
            # SUCCESS
            # -----------------------------------------

            data = response.json()

            content = data["choices"][0]["message"]["content"]

            result = json.loads(content)

            print(
                "DEBUG: Groq JSON parsed successfully.",
                flush=True,
            )

            return result

        except requests.exceptions.Timeout:

            print(
                "WARNING: Groq request timed out.",
                flush=True,
            )

            if attempt < MAX_GROQ_RETRIES:

                time.sleep(10)
                continue

            raise

        except json.JSONDecodeError:

            print(
                "WARNING: Groq returned invalid JSON.",
                flush=True,
            )

            if attempt < MAX_GROQ_RETRIES:

                time.sleep(10)
                continue

            raise

    raise RuntimeError(
        "Groq request failed."
    )
# =========================================================
# BATCH ARTICLE ANALYSIS
# =========================================================

def analyze_batch(articles):

    compact_articles = []

    for index, article in enumerate(articles):

        # Limit article text so a batch doesn't become
        # unnecessarily large.
        content = normalize_text(
            article.get("content", "")
        )[:5000]

        summary = normalize_text(
            article.get("summary", "")
        )[:2000]

        compact_articles.append(
            {
                "id": article["id"],
                "title": article["title"],
                "source": article["source"],
                "category": article["category"],
                "published": article["published"],
                "summary": summary,
                "content": content,
            }
        )

    articles_json = json.dumps(
        compact_articles,
        ensure_ascii=False,
    )

    system_prompt = """
تو یک سردبیر خبری دقیق و بی‌طرف هستی.

برای هر خبر:
1. اهمیت آن را از 1 تا 5 تعیین کن.
2. یک خلاصه فارسی کوتاه و دقیق بنویس.
3. نکات اصلی خبر را استخراج کن.
4. اگر خبر شامل ادعا، نظر یا تفسیر است، آن را از واقعیت‌های گزارش‌شده جدا کن.
5. در صورت وجود ابهام مهم، آن را ذکر کن.

مقیاس اهمیت:
5 = بسیار مهم و دارای اثر گسترده یا فوری
4 = مهم و ارزشمند برای پیگیری
3 = نسبتاً مهم
2 = کم‌اهمیت
1 = حاشیه‌ای یا کم‌ارزش

از ساختن اطلاعاتی که در متن خبر وجود ندارد خودداری کن.

حتماً برای هر خبر همان id ورودی را برگردان.

فقط JSON معتبر برگردان.
ساختار:
{
  "articles": [
    {
      "id": "...",
      "importance": 1,
      "importance_reason": "...",
      "summary_fa": "...",
      "key_facts": ["...", "..."],
      "claims_or_opinions": ["..."],
      "uncertainties": ["..."]
    }
  ]
}
"""

    user_prompt = (
        "این مجموعه خبرها را تحلیل کن:\n\n"
        + articles_json
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    return groq_request(messages)


def analyze_articles(articles):

    all_results = []

    total = len(articles)

    batches = [
        articles[i:i + BATCH_SIZE]
        for i in range(0, total, BATCH_SIZE)
    ]

    print(
        f"\nDEBUG: analyzing {total} articles "
        f"in {len(batches)} batches "
        f"of up to {BATCH_SIZE} articles.",
        flush=True,
    )

    for batch_index, batch in enumerate(
        batches,
        start=1
    ):

        print(
            f"\nDEBUG: analyzing batch "
            f"{batch_index}/{len(batches)} "
            f"({len(batch)} articles)...",
            flush=True,
        )

        try:

            result = analyze_batch(batch)

            analyzed_items = result.get(
                "articles",
                []
            )

            if not isinstance(analyzed_items, list):
                raise RuntimeError(
                    "Groq returned invalid articles list."
                )

            result_map = {}

            for item in analyzed_items:

                if isinstance(item, dict):
                    item_id = item.get("id")

                    if item_id:
                        result_map[item_id] = item

            for article in batch:

                analysis = result_map.get(
                    article["id"]
                )

                if analysis is None:

                    print(
                        "WARNING: Groq did not return "
                        f"analysis for: {article['title']}",
                        flush=True,
                    )

                    continue

                article_copy = dict(article)

                article_copy.update(
                    {
                        "importance": int(
                            analysis.get(
                                "importance",
                                1
                            )
                        ),
                        "importance_reason":
                            normalize_text(
                                analysis.get(
                                    "importance_reason",
                                    ""
                                )
                            ),
                        "summary_fa":
                            normalize_text(
                                analysis.get(
                                    "summary_fa",
                                    ""
                                )
                            ),
                        "key_facts":
                            analysis.get(
                                "key_facts",
                                []
                            ),
                        "claims_or_opinions":
                            analysis.get(
                                "claims_or_opinions",
                                []
                            ),
                        "uncertainties":
                            analysis.get(
                                "uncertainties",
                                []
                            ),
                    }
                )

                all_results.append(article_copy)

            print(
                f"DEBUG: batch {batch_index} completed. "
                f"{len(analyzed_items)} analyses returned.",
                flush=True,
            )

        except Exception as e:

            print(
                f"ERROR: batch {batch_index} failed: {e}",
                flush=True,
            )

        # Important: delay BETWEEN batches
        if batch_index < len(batches):

            print(
                f"DEBUG: waiting "
                f"{GROQ_DELAY_SECONDS}s "
                f"before next batch...",
                flush=True,
            )

            time.sleep(GROQ_DELAY_SECONDS)

    print(
        f"\nDEBUG: total successfully analyzed "
        f"articles: {len(all_results)}",
        flush=True,
    )

    return all_results


# =========================================================
# FINAL EDITOR
# =========================================================

def select_final_news(analyzed_articles):

    candidates = [
        article
        for article in analyzed_articles
        if article.get("importance", 1)
        >= MIN_IMPORTANCE
    ]

    if not candidates:
        print(
            "DEBUG: no articles passed importance threshold.",
            flush=True,
        )
        return {
            "digest_title": "گزارش اخبار مهم روز",
            "selected_ids": [],
        }

    candidates = sorted(
        candidates,
        key=lambda x: (
            x.get("importance", 1),
            x.get("published", ""),
        ),
        reverse=True,
    )

    candidates_for_editor = []

    for article in candidates:

        candidates_for_editor.append(
            {
                "id": article["id"],
                "title": article["title"],
                "source": article["source"],
                "category": article["category"],
                "importance": article["importance"],
                "importance_reason":
                    article.get(
                        "importance_reason",
                        ""
                    ),
                "summary_fa":
                    article.get(
                        "summary_fa",
                        ""
                    ),
            }
        )

    editor_json = json.dumps(
        candidates_for_editor,
        ensure_ascii=False,
    )

    system_prompt = f"""
تو سردبیر نهایی یک خبرنامه روزانه فارسی هستی.

از میان خبرهای زیر حداکثر {MAX_FINAL_NEWS}
خبر را انتخاب کن.

هدف:
- تنوع موضوعی
- اهمیت واقعی
- جلوگیری از تکرار
- ارزش خبری برای یک خواننده عمومی
- اولویت دادن به خبرهای مهم پزشکی و سلامت،
  اقتصاد و بازارها، هوش مصنوعی و فناوری، علم،
  ایران و جهان

هیچ خبری را بر اساس گرایش سیاسی انتخاب یا حذف نکن.
صرفاً اهمیت خبری و تنوع را در نظر بگیر.

فقط JSON معتبر برگردان:

{{
  "digest_title": "...",
  "selected_ids": ["...", "..."]
}}
"""

    user_prompt = (
        "خبرهای کاندیدا:\n\n"
        + editor_json
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    try:

        result = groq_request(
            messages,
            timeout=FINAL_EDITOR_TIMEOUT,
        )

        selected_ids = result.get(
            "selected_ids",
            []
        )

        if not isinstance(selected_ids, list):
            selected_ids = []

        selected_ids = selected_ids[
            :MAX_FINAL_NEWS
        ]

        return {
            "digest_title": result.get(
                "digest_title",
                "گزارش اخبار مهم روز"
            ),
            "selected_ids": selected_ids,
        }

    except Exception as e:

        print(
            f"ERROR: final editor failed: {e}",
            flush=True,
        )

        # Fallback: use top candidates without
        # another AI request.
        fallback_ids = [
            article["id"]
            for article in candidates[
                :MAX_FINAL_NEWS
            ]
        ]

        return {
            "digest_title":
                "گزارش اخبار مهم روز",
            "selected_ids":
                fallback_ids,
        }


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def build_digest_message(
    final_selection,
    analyzed_articles
):

    article_map = {
        article["id"]: article
        for article in analyzed_articles
    }

    selected_ids = final_selection.get(
        "selected_ids",
        []
    )

    digest_title = final_selection.get(
        "digest_title",
        "گزارش اخبار مهم روز"
    )

    lines = []

    lines.append(
        f"📰 <b>{escape(str(digest_title))}</b>"
    )

    lines.append("")

    selected_articles = []

    for article_id in selected_ids:

        article = article_map.get(article_id)

        if article:
            selected_articles.append(article)

    for index, article in enumerate(
        selected_articles,
        start=1
    ):

        title = escape(
            article.get("title", "")
        )

        source = escape(
            article.get("source", "")
        )

        category = escape(
            article.get("category", "")
        )

        summary = escape(
            article.get(
                "summary_fa",
                ""
            )
        )

        url = article.get("url", "")

        lines.append(
            f"<b>{index}. {title}</b>"
        )

        lines.append(
            f"🏷 {category} | {source}"
        )

        if summary:
            lines.append(summary)

        if url:
            lines.append(
                f'🔗 <a href="{escape(url)}">'
                f"منبع خبر</a>"
            )

        lines.append("")

    lines.append(
        "⏱ زمان تهیه: "
        + datetime.now(
            IRAN_TZ
        ).strftime("%Y-%m-%d %H:%M")
        + " به وقت ایران"
    )

    return "\n".join(lines)


def send_telegram(message):

    bot_token = os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.environ.get(
        "TELEGRAM_CHAT_ID"
    )

    if not bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set."
        )

    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is not set."
        )

    url = (
        f"https://api.telegram.org/bot"
        f"{bot_token}/sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    print(
        "DEBUG: sending digest to Telegram...",
        flush=True,
    )

    response = requests.post(
        url,
        json=payload,
        timeout=TELEGRAM_TIMEOUT,
    )

    print(
        f"DEBUG: Telegram response "
        f"HTTP {response.status_code}",
        flush=True,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Telegram error: {response.text}"
        )

    print(
        "DEBUG: Telegram message sent successfully.",
        flush=True,
    )


# =========================================================
# DIGEST
# =========================================================

def create_digest():

    print(
        "DEBUG: starting daily digest...",
        flush=True,
    )

    pending = load_json(
        PENDING_FILE,
        []
    )

    seen = load_json(
        SEEN_FILE,
        []
    )

    if not pending:

        print(
            "DEBUG: pending queue is empty.",
            flush=True,
        )

        return

    print(
        f"DEBUG: pending queue contains "
        f"{len(pending)} articles.",
        flush=True,
    )

    # Newest first
    pending.sort(
        key=lambda x: x.get(
            "published",
            ""
        ),
        reverse=True,
    )

    articles_for_ai = pending[
        :MAX_ARTICLES_FOR_AI
    ]

    print(
        f"DEBUG: sending {len(articles_for_ai)} "
        f"articles to batch analysis.",
        flush=True,
    )

    analyzed_articles = analyze_articles(
        articles_for_ai
    )

    if not analyzed_articles:

        print(
            "ERROR: no articles were successfully "
            "analyzed. Digest will not be sent.",
            flush=True,
        )

        return

    final_selection = select_final_news(
        analyzed_articles
    )

    message = build_digest_message(
        final_selection,
        analyzed_articles
    )

    selected_ids = set(
        final_selection.get(
            "selected_ids",
            []
        )
    )

    if not selected_ids:

        print(
            "ERROR: final selection is empty. "
            "Digest will not be sent.",
            flush=True,
        )

        return

    send_telegram(message)

    # Mark selected articles as seen
    for article in analyzed_articles:

        if article["id"] in selected_ids:

            if article["id"] not in seen:
                seen.append(article["id"])

    # Remove selected articles from pending
    pending = [
        article
        for article in pending
        if article.get("id")
        not in selected_ids
    ]

    save_json(
        SEEN_FILE,
        seen
    )

    save_json(
        PENDING_FILE,
        pending
    )

    print(
        f"DEBUG: digest completed successfully. "
        f"Sent {len(selected_ids)} articles.",
        flush=True,
    )

    print(
        f"DEBUG: {len(pending)} articles remain "
        f"in pending queue.",
        flush=True,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if len(sys.argv) < 2:

        print(
            "Usage: python news_bot.py "
            "[collect|digest]"
        )

        sys.exit(1)

    mode = sys.argv[1].strip().lower()

    if mode == "collect":

        collect_news()

    elif mode == "digest":

        create_digest()

    else:

        print(
            f"Unknown mode: {mode}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
