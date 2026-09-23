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

# Maximum number of pending articles analyzed per digest
MAX_ARTICLES_FOR_AI = 25

# Minimum importance kept
MIN_IMPORTANCE = 3

# Maximum final news items in Telegram
MAX_FINAL_NEWS = 10

# Groq batch size
BATCH_SIZE = 5

# Keep article input compact to reduce token usage
MAX_CONTENT_CHARS = 1200
MAX_SUMMARY_CHARS = 600

# Groq limits
GROQ_MAX_COMPLETION_TOKENS = 1800
GROQ_REQUEST_TIMEOUT = 60

TELEGRAM_TIMEOUT = 30

# Retries
MAX_GROQ_RETRIES = 3

# Delay between Groq batches
GROQ_DELAY_SECONDS = 12

# Maximum wait after rate limit
MAX_RATE_LIMIT_WAIT = 120


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
        print(
            f"WARNING: Could not read {filename}: {e}",
            flush=True,
        )
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


def article_similarity(a, b):
    text_a = normalize_text(
        f"{a.get('title', '')} {a.get('summary', '')}"
    ).lower()

    text_b = normalize_text(
        f"{b.get('title', '')} {b.get('summary', '')}"
    ).lower()

    if not text_a or not text_b:
        return 0

    return SequenceMatcher(
        None,
        text_a,
        text_b,
    ).ratio()


def is_duplicate(article, articles, threshold=0.75):
    for existing in articles:
        if article_similarity(
            article,
            existing,
        ) >= threshold:
            return True

    return False


def get_entry_date(entry):
    """
    Try several RSS date fields and convert to Iran time.
    """

    for field in (
        "published_parsed",
        "updated_parsed",
        "created_parsed",
    ):

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
# JALALI / SHAMSI DATE CONVERSION
# =========================================================

def gregorian_to_jalali(gy, gm, gd):
    """
    Convert Gregorian date to Jalali (Persian) date.

    Returns:
        (jy, jm, jd)
    """

    g_days_in_month = [
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    ]

    j_days_in_month = [
        31, 31, 31, 31, 31, 31,
        30, 30, 30, 30, 30, 29
    ]

    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1

    g_day_no = (
        365 * gy2
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
    )

    for i in range(gm2):
        g_day_no += g_days_in_month[i]

    if gm2 > 1 and (
        gy % 4 == 0
        and (
            gy % 100 != 0
            or gy % 400 == 0
        )
    ):
        g_day_no += 1

    g_day_no += gd2

    j_day_no = g_day_no - 79

    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)

    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    i = 0

    while (
        i < 11
        and j_day_no >= j_days_in_month[i]
    ):
        j_day_no -= j_days_in_month[i]
        i += 1

    jm = i + 1
    jd = j_day_no + 1

    return jy, jm, jd


PERSIAN_MONTHS = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


PERSIAN_DIGITS = str.maketrans(
    "0123456789",
    "۰۱۲۳۴۵۶۷۸۹",
)


def to_persian_digits(value):
    return str(value).translate(
        PERSIAN_DIGITS
    )


def jalali_datetime_string(dt):
    """
    Convert datetime to a Persian/Jalali
    date and Persian digits.
    """

    jy, jm, jd = gregorian_to_jalali(
        dt.year,
        dt.month,
        dt.day,
    )

    date_part = (
        f"{to_persian_digits(jd)} "
        f"{PERSIAN_MONTHS[jm - 1]} "
        f"{to_persian_digits(jy)}"
    )

    time_part = (
        f"{to_persian_digits(dt.hour):>2}:"
        f"{to_persian_digits(dt.minute):>2}"
    )

    return (
        f"{date_part}، ساعت {time_part}"
    )


# =========================================================
# RSS COLLECTION
# =========================================================

def collect_news():

    print(
        "DEBUG: starting news collection...",
        flush=True,
    )

    seen = load_json(
        SEEN_FILE,
        [],
    )

    pending = load_json(
        PENDING_FILE,
        [],
    )

    if not isinstance(seen, list):
        seen = []

    if not isinstance(pending, list):
        pending = []

    today = today_iran()

    collected = []

    total_feeds = len(FEEDS)

    for feed_index, feed_info in enumerate(
        FEEDS,
        start=1,
    ):

        print(
            f"\nDEBUG: collecting feed "
            f"{feed_index}/{total_feeds}: "
            f"{feed_info['name']}",
            flush=True,
        )

        try:

            parsed = feedparser.parse(
                feed_info["url"]
            )

            if getattr(
                parsed,
                "bozo",
                False,
            ):

                print(
                    f"WARNING: feed parser warning "
                    f"for {feed_info['name']}",
                    flush=True,
                )

            entries = parsed.entries[
                :MAX_ARTICLES_PER_FEED
            ]

            print(
                f"DEBUG: {len(entries)} "
                f"entries found",
                flush=True,
            )

            for entry in entries:

                title = normalize_text(
                    entry.get(
                        "title",
                        "",
                    )
                )

                url = clean_url(
                    entry.get(
                        "link",
                        "",
                    )
                )

                if not title or not url:
                    continue

                published_dt = get_entry_date(
                    entry
                )

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
                    entry.get(
                        "summary",
                        "",
                    )
                )

                content = normalize_text(
                    entry.get(
                        "description",
                        "",
                    )
                )

                if not content:
                    content = summary

                article = {
                    "id": article_id,
                    "title": title,
                    "url": url,
                    "source": feed_info["name"],
                    "category": feed_info["category"],
                    "published":
                        published_dt.isoformat(),
                    "summary": summary,
                    "content": content,
                }

                if is_duplicate(
                    article,
                    collected,
                ):
                    continue

                if is_duplicate(
                    article,
                    pending,
                ):
                    continue

                collected.append(article)

        except Exception as e:

            print(
                f"ERROR collecting "
                f"{feed_info['name']}: {e}",
                flush=True,
            )

    collected.sort(
        key=lambda x: x.get(
            "published",
            "",
        ),
        reverse=True,
    )

    print(
        f"\nDEBUG: collected "
        f"{len(collected)} new articles",
        flush=True,
    )

    if collected:
        pending.extend(collected)

    # Keep pending bounded
    pending = pending[-200:]

    save_json(
        PENDING_FILE,
        pending,
    )

    save_json(
        SEEN_FILE,
        seen,
    )

    print(
        f"DEBUG: pending queue now contains "
        f"{len(pending)} articles",
        flush=True,
    )


# =========================================================
# GROQ REQUEST
# =========================================================

def groq_request(
    messages,
    timeout=GROQ_REQUEST_TIMEOUT,
):

    api_key = os.environ.get(
        "GROQ_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set."
        )

    headers = {
        "Authorization":
            f"Bearer {api_key}",
        "Content-Type":
            "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,

        # Low randomness for consistent news analysis
        "temperature": 0.3,

        # Important for GPT-OSS token control
        "reasoning_effort": "low",
        "include_reasoning": False,

        # Prevent excessively long responses
        "max_completion_tokens":
            GROQ_MAX_COMPLETION_TOKENS,

        "response_format": {
            "type": "json_object"
        },
    }

    for attempt in range(
        1,
        MAX_GROQ_RETRIES + 1,
    ):

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
                f"with HTTP "
                f"{response.status_code}",
                flush=True,
            )

            # -----------------------------------------
            # RATE LIMIT
            # -----------------------------------------

            if response.status_code == 429:

                print(
                    "========== GROQ RATE LIMIT ==========",
                    flush=True,
                )

                print(
                    response.text[:3000],
                    flush=True,
                )

                retry_after = response.headers.get(
                    "retry-after"
                )

                reset_tokens = response.headers.get(
                    "x-ratelimit-reset-tokens"
                )

                wait_time = None

                # Prefer Retry-After
                try:

                    if retry_after is not None:
                        wait_time = float(
                            retry_after
                        )

                except (
                    TypeError,
                    ValueError,
                ):
                    wait_time = None

                # If unavailable, use token reset
                if wait_time is None:

                    try:

                        if reset_tokens:
                            reset_clean = (
                                reset_tokens
                                .replace("s", "")
                                .strip()
                            )

                            wait_time = float(
                                reset_clean
                            )

                    except (
                        TypeError,
                        ValueError,
                    ):
                        wait_time = None

                if wait_time is None:
                    wait_time = 30 * attempt

                # Add a small safety margin
                wait_time += 2

                wait_time = max(
                    5,
                    min(
                        wait_time,
                        MAX_RATE_LIMIT_WAIT,
                    ),
                )

                if attempt < MAX_GROQ_RETRIES:

                    print(
                        f"Rate limit detected. "
                        f"Waiting {wait_time:.1f}s...",
                        flush=True,
                    )

                    time.sleep(
                        wait_time
                    )

                    continue

                raise RuntimeError(
                    "Groq rate limit persisted "
                    "after maximum retries."
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
                    f"Groq HTTP "
                    f"{response.status_code}: "
                    f"{detail}"
                )

            # -----------------------------------------
            # SUCCESS
            # -----------------------------------------

            data = response.json()

            content = (
                data[
                    "choices"
                ][0][
                    "message"
                ]["content"]
            )

            result = json.loads(
                content
            )

            print(
                "DEBUG: Groq JSON parsed "
                "successfully.",
                flush=True,
            )

            return result

        except requests.exceptions.Timeout:

            print(
                "WARNING: Groq request timed out.",
                flush=True,
            )

            if attempt < MAX_GROQ_RETRIES:

                time.sleep(
                    10 * attempt
                )

                continue

            raise

        except json.JSONDecodeError:

            print(
                "WARNING: Groq returned "
                "invalid JSON.",
                flush=True,
            )

            if attempt < MAX_GROQ_RETRIES:

                time.sleep(
                    5 * attempt
                )

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

    for article in articles:

        content = normalize_text(
            article.get(
                "content",
                "",
            )
        )[:MAX_CONTENT_CHARS]

        summary = normalize_text(
            article.get(
                "summary",
                "",
            )
        )[:MAX_SUMMARY_CHARS]

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
        separators=(",", ":"),
    )

    system_prompt = """
تو یک سردبیر خبری دقیق و بی‌طرف هستی.

برای هر خبر فقط این موارد را تعیین کن:

1. importance از 1 تا 5
2. یک summary_fa کوتاه و دقیق

مقیاس اهمیت:
5 = بسیار مهم و دارای اثر گسترده یا فوری
4 = مهم و ارزشمند برای پیگیری
3 = نسبتاً مهم
2 = کم‌اهمیت
1 = حاشیه‌ای یا کم‌ارزش

فقط بر اساس اطلاعات موجود در خبر قضاوت کن.
اطلاعات جدید نساز.
ادعاها را به‌عنوان واقعیت قطعی بازنویسی نکن.

برای هر ورودی حتماً همان id را برگردان.

خلاصه فارسی هر خبر حداکثر دو جمله باشد.

فقط JSON معتبر برگردان:

{
  "articles": [
    {
      "id": "...",
      "importance": 1,
      "summary_fa": "..."
    }
  ]
}
"""

    user_prompt = (
        system_prompt
        + "\n\n"
        + "خبرهای زیر را تحلیل کن:\n"
        + articles_json
    )

    messages = [
        {
            "role": "user",
            "content": user_prompt,
        }
    ]

    return groq_request(
        messages
    )


def analyze_articles(articles):

    all_results = []

    total = len(articles)

    batches = [
        articles[
            i:i + BATCH_SIZE
        ]
        for i in range(
            0,
            total,
            BATCH_SIZE,
        )
    ]

    print(
        f"\nDEBUG: analyzing "
        f"{total} articles in "
        f"{len(batches)} batches "
        f"of up to {BATCH_SIZE} articles.",
        flush=True,
    )

    for batch_index, batch in enumerate(
        batches,
        start=1,
    ):

        print(
            f"\nDEBUG: analyzing batch "
            f"{batch_index}/{len(batches)} "
            f"({len(batch)} articles)...",
            flush=True,
        )

        try:

            result = analyze_batch(
                batch
            )

            analyzed_items = result.get(
                "articles",
                [],
            )

            if not isinstance(
                analyzed_items,
                list,
            ):

                raise RuntimeError(
                    "Groq returned invalid "
                    "articles list."
                )

            result_map = {}

            for item in analyzed_items:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                item_id = item.get(
                    "id"
                )

                if item_id:
                    result_map[
                        item_id
                    ] = item

            returned_count = 0

            for article in batch:

                analysis = result_map.get(
                    article["id"]
                )

                if analysis is None:

                    print(
                        "WARNING: Groq did not "
                        "return analysis for: "
                        f"{article['title']}",
                        flush=True,
                    )

                    continue

                try:

                    importance = int(
                        analysis.get(
                            "importance",
                            1,
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    importance = 1

                importance = max(
                    1,
                    min(
                        importance,
                        5,
                    ),
                )

                summary_fa = normalize_text(
                    analysis.get(
                        "summary_fa",
                        "",
                    )
                )

                article_copy = dict(
                    article
                )

                article_copy.update(
                    {
                        "importance":
                            importance,

                        "summary_fa":
                            summary_fa,
                    }
                )

                all_results.append(
                    article_copy
                )

                returned_count += 1

            print(
                f"DEBUG: batch "
                f"{batch_index} completed. "
                f"{returned_count} analyses "
                f"returned.",
                flush=True,
            )

        except Exception as e:

            print(
                f"ERROR: batch "
                f"{batch_index} failed: {e}",
                flush=True,
            )

        if batch_index < len(batches):

            print(
                f"DEBUG: waiting "
                f"{GROQ_DELAY_SECONDS}s "
                f"before next batch...",
                flush=True,
            )

            time.sleep(
                GROQ_DELAY_SECONDS
            )

    print(
        f"\nDEBUG: total successfully "
        f"analyzed articles: "
        f"{len(all_results)}",
        flush=True,
    )

    return all_results


# =========================================================
# LOCAL FINAL SELECTION
# =========================================================

def select_final_news(
    analyzed_articles
):

    candidates = [
        article
        for article in analyzed_articles
        if article.get(
            "importance",
            1,
        ) >= MIN_IMPORTANCE
    ]

    if not candidates:

        print(
            "DEBUG: no articles passed "
            "importance threshold.",
            flush=True,
        )

        return {
            "digest_title":
                "گزارش اخبار مهم روز",
            "selected_ids": [],
        }

    # Newest first inside the same importance level
    candidates.sort(
        key=lambda x: (
            x.get(
                "importance",
                1,
            ),
            x.get(
                "published",
                "",
            ),
        ),
        reverse=True,
    )

    selected = []

    selected_ids = set()

    category_counts = {}

    # -----------------------------------------
    # Pass 1:
    # Prefer diversity.
    # Maximum 2 from each category.
    # -----------------------------------------

    for article in candidates:

        if len(selected) >= MAX_FINAL_NEWS:
            break

        category = article.get(
            "category",
            "سایر",
        )

        count = category_counts.get(
            category,
            0,
        )

        if count >= 2:
            continue

        article_id = article.get(
            "id"
        )

        if not article_id:
            continue

        if article_id in selected_ids:
            continue

        selected.append(
            article
        )

        selected_ids.add(
            article_id
        )

        category_counts[
            category
        ] = count + 1

    # -----------------------------------------
    # Pass 2:
    # Fill remaining positions by importance.
    # -----------------------------------------

    if len(selected) < MAX_FINAL_NEWS:

        for article in candidates:

            if len(selected) >= MAX_FINAL_NEWS:
                break

            article_id = article.get(
                "id"
            )

            if not article_id:
                continue

            if article_id in selected_ids:
                continue

            selected.append(
                article
            )

            selected_ids.add(
                article_id
            )

    # Final order:
    # importance first, then newest
    selected.sort(
        key=lambda x: (
            x.get(
                "importance",
                1,
            ),
            x.get(
                "published",
                "",
            ),
        ),
        reverse=True,
    )

    print(
        f"DEBUG: locally selected "
        f"{len(selected)} final articles.",
        flush=True,
    )

    for index, article in enumerate(
        selected,
        start=1,
    ):

        print(
            f"DEBUG: final #{index}: "
            f"[{article.get('importance', 1)}] "
            f"{article.get('title', '')}",
            flush=True,
        )

    return {
        "digest_title":
            "گزارش اخبار مهم روز",
        "selected_ids": [
            article["id"]
            for article in selected
        ],
    }


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def build_digest_message(
    final_selection,
    analyzed_articles,
):

    article_map = {
        article["id"]: article
        for article in analyzed_articles
    }

    selected_ids = final_selection.get(
        "selected_ids",
        [],
    )

    digest_title = final_selection.get(
        "digest_title",
        "گزارش اخبار مهم روز",
    )

    lines = []

    lines.append(
        f"📰 <b>{escape(str(digest_title))}</b>"
    )

    lines.append("")

    selected_articles = []

    for article_id in selected_ids:

        article = article_map.get(
            article_id
        )

        if article:
            selected_articles.append(
                article
            )

    for index, article in enumerate(
        selected_articles,
        start=1,
    ):

        title = escape(
            article.get(
                "title",
                "",
            )
        )

        source = escape(
            article.get(
                "source",
                "",
            )
        )

        category = escape(
            article.get(
                "category",
                "",
            )
        )

        summary = escape(
            article.get(
                "summary_fa",
                "",
            )
        )

        url = article.get(
            "url",
            "",
        )

        importance = article.get(
            "importance",
            1,
        )

        lines.append(
            f"<b>{index}. {title}</b>"
        )

        lines.append(
            f"🏷 {category} | {source}"
        )

        if summary:
            lines.append(
                summary
            )

        lines.append(
            f"⭐ اهمیت: {importance}/5"
        )

        if url:

            lines.append(
                f'🔗 <a href="{escape(url)}">'
                f"منبع خبر</a>"
            )

        lines.append("")

    # Current Iran time
    now_iran = datetime.now(
        IRAN_TZ
    )

    lines.append(
        "⏱ زمان تهیه: "
        + escape(
            jalali_datetime_string(
                now_iran
            )
        )
        + " به وقت ایران"
    )

    return "\n".join(
        lines
    )


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
        "chat_id":
            chat_id,

        "text":
            message,

        "parse_mode":
            "HTML",

        "disable_web_page_preview":
            True,
    }

    print(
        "DEBUG: sending digest "
        "to Telegram...",
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
            f"Telegram error: "
            f"{response.text}"
        )

    print(
        "DEBUG: Telegram message "
        "sent successfully.",
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
        [],
    )

    seen = load_json(
        SEEN_FILE,
        [],
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
            "",
        ),
        reverse=True,
    )

    articles_for_ai = pending[
        :MAX_ARTICLES_FOR_AI
    ]

    print(
        f"DEBUG: sending "
        f"{len(articles_for_ai)} "
        f"articles to batch analysis.",
        flush=True,
    )

    analyzed_articles = analyze_articles(
        articles_for_ai
    )

    if not analyzed_articles:

        print(
            "ERROR: no articles were "
            "successfully analyzed. "
            "Digest will not be sent.",
            flush=True,
        )

        return

    # -----------------------------------------
    # Local final selection
    # No second Groq request.
    # -----------------------------------------

    final_selection = select_final_news(
        analyzed_articles
    )

    selected_ids = set(
        final_selection.get(
            "selected_ids",
            [],
        )
    )

    if not selected_ids:

        print(
            "ERROR: final selection "
            "is empty. "
            "Digest will not be sent.",
            flush=True,
        )

        return

    message = build_digest_message(
        final_selection,
        analyzed_articles,
    )

    send_telegram(
        message
    )

    # -----------------------------------------
    # Mark ALL successfully analyzed articles
    # as seen.
    #
    # This prevents the same unselected
    # articles from being analyzed again
    # every day.
    # -----------------------------------------

    analyzed_ids = {
        article["id"]
        for article in analyzed_articles
        if article.get("id")
    }

    for article_id in analyzed_ids:

        if article_id not in seen:
            seen.append(
                article_id
            )

    # -----------------------------------------
    # Remove ALL successfully analyzed
    # articles from pending.
    #
    # Failed / unanalyzed articles remain
    # in pending and can be retried later.
    # -----------------------------------------

    pending = [
        article
        for article in pending
        if article.get("id")
        not in analyzed_ids
    ]

    save_json(
        SEEN_FILE,
        seen,
    )

    save_json(
        PENDING_FILE,
        pending,
    )

    print(
        f"DEBUG: digest completed "
        f"successfully. "
        f"Sent {len(selected_ids)} articles.",
        flush=True,
    )

    print(
        f"DEBUG: "
        f"{len(analyzed_ids)} analyzed articles "
        f"were processed.",
        flush=True,
    )

    print(
        f"DEBUG: {len(pending)} articles "
        f"remain in pending queue.",
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
