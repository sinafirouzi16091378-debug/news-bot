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

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"

SEEN_FILE = "seen.json"
PENDING_FILE = "pending_news.json"

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))

MAX_ARTICLES_FOR_AI = 25
BATCH_SIZE = 5

MAX_CONTENT_CHARS = 1200
MAX_SUMMARY_CHARS = 600
GROQ_MAX_COMPLETION_TOKENS = 1800
GROQ_DELAY_SECONDS = 12

MIN_IMPORTANCE = 3
MAX_FINAL_NEWS = 10


# =========================================================
# RSS FEEDS
# =========================================================

FEEDS = [
    ("پزشکی و سلامت", "NIH", "https://newsinhealth.nih.gov/rss"),
    ("پزشکی و سلامت", "WHO", "https://www.who.int/rss-feeds/news-english.xml"),

    ("هوش مصنوعی و فناوری", "MIT CSAIL",
     "https://www.csail.mit.edu/news/feed"),

    ("هوش مصنوعی و فناوری", "The Guardian AI",
     "https://www.theguardian.com/technology/artificialintelligenceai/rss"),

    ("اقتصاد و بازارها", "ECB",
     "https://www.ecb.europa.eu/rss/press.html"),

    ("اقتصاد و بازارها", "Federal Reserve",
     "https://www.federalreserve.gov/feeds/press_all.xml"),

    ("جهان", "BBC World",
     "https://feeds.bbci.co.uk/news/world/rss.xml"),

    ("جهان", "Reuters",
     "https://www.youtube.com/feeds/videos.xml?channel_id=UCmC3M5e1s8wM3l6Y8J3j7Vw"),

    ("ایران", "Tasnim",
     "https://www.tasnimnews.com/fa/rss/feed/1/0/0/%D8%A7%D8%AE%D8%A8%D8%A7%D8%B1"),

    ("ایران", "Radio Farda",
     "https://www.youtube.com/feeds/videos.xml?channel_id=UCxJ4Qb7Wf1b8GJY7XJQkXxQ"),

    ("ایران", "BBC Persian",
     "https://www.youtube.com/feeds/videos.xml?channel_id=UCc5P6Y5Jx5dG4j7n7QxQW2A"),
]


# =========================================================
# BASIC HELPERS
# =========================================================

def normalize_text(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(r"\s+", " ", text)
    text = text.strip().lower()

    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def escape(text):
    return html.escape(str(text or ""), quote=False)


def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def article_similarity(a, b):
    title_a = normalize_text(a.get("title", ""))
    title_b = normalize_text(b.get("title", ""))

    if not title_a or not title_b:
        return 0

    return SequenceMatcher(None, title_a, title_b).ratio()


def is_duplicate(article, existing_articles, threshold=0.75):
    for existing in existing_articles:
        if article_similarity(article, existing) >= threshold:
            return True

    return False


def clean_url(url):
    if not url:
        return ""

    url = str(url).strip()

    url = re.sub(
        r"([?&])(utm_[^&]+|fbclid|gclid)=[^&]*",
        "",
        url,
        flags=re.IGNORECASE
    )

    url = url.replace("?&", "?").rstrip("?&")

    return url


# =========================================================
# DATE HELPERS
# =========================================================

def get_entry_date(entry):
    for key in ["published_parsed", "updated_parsed", "created_parsed"]:
        value = entry.get(key)

        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    return None


def today_iran():
    return datetime.now(IRAN_TZ).date()


# =========================================================
# JALALI / SHAMSI
# =========================================================

def gregorian_to_jalali(gy, gm, gd):
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
        gy % 4 == 0 and
        (gy % 100 != 0 or gy % 400 == 0)
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

    while i < 11 and j_day_no >= j_days_in_month[i]:
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
    "۰۱۲۳۴۵۶۷۸۹"
)


def to_persian_digits(text):
    return str(text).translate(PERSIAN_DIGITS)


def jalali_date_string(dt):
    if not dt:
        return ""

    dt = dt.astimezone(IRAN_TZ)

    jy, jm, jd = gregorian_to_jalali(
        dt.year,
        dt.month,
        dt.day
    )

    return (
        f"{to_persian_digits(jd)} "
        f"{PERSIAN_MONTHS[jm - 1]} "
        f"{to_persian_digits(jy)}"
    )


# =========================================================
# COLLECT
# =========================================================

def collect_news():
    print("DEBUG: starting collection...")

    seen = load_json(SEEN_FILE, [])
    pending = load_json(PENDING_FILE, [])

    seen_ids = set()

    for item in seen:
        if isinstance(item, dict):
            article_id = item.get("id")
            if article_id:
                seen_ids.add(article_id)
        else:
            seen_ids.add(str(item))

    pending_ids = {
        item.get("id")
        for item in pending
        if isinstance(item, dict) and item.get("id")
    }

    today = today_iran()

    collected = []

    for category, source, url in FEEDS:
        print(f"\n### {category} / {source}")

        try:
            feed = feedparser.parse(url)

            if getattr(feed, "bozo", False):
                print(
                    f"WARNING: feed parser warning for {source}"
                )

            entries = feed.entries[:30]

            print(
                f"{source}: {len(entries)} entries"
            )

            for entry in entries:
                title = normalize_text(
                    entry.get("title", "")
                )

                if not title:
                    continue

                published = get_entry_date(entry)

                if not published:
                    continue

                published_iran = published.astimezone(
                    IRAN_TZ
                )

                if published_iran.date() != today:
                    continue

                link = clean_url(
                    entry.get("link", "")
                )

                article_id = (
                    f"{source}|"
                    f"{title}|"
                    f"{link}"
                )

                article_id = normalize_text(
                    article_id
                )

                if article_id in seen_ids:
                    continue

                if article_id in pending_ids:
                    continue

                summary = entry.get(
                    "summary",
                    ""
                )

                content = entry.get(
                    "content",
                    ""
                )

                if isinstance(content, list) and content:
                    content = content[0].get(
                        "value",
                        ""
                    )

                if not content:
                    content = summary

                article = {
                    "id": article_id,
                    "title": entry.get(
                        "title",
                        ""
                    ).strip(),
                    "category": category,
                    "source": source,
                    "url": link,
                    "published": published_iran.isoformat(),
                    "content": normalize_text(
                        content
                    )[:MAX_CONTENT_CHARS],
                    "summary": normalize_text(
                        summary
                    )[:MAX_SUMMARY_CHARS],
                }

                if is_duplicate(
                    article,
                    pending,
                    threshold=0.75
                ):
                    continue

                if is_duplicate(
                    article,
                    collected,
                    threshold=0.75
                ):
                    continue

                collected.append(article)

        except Exception as e:
            print(
                f"ERROR: {source}: {e}"
            )

    pending.extend(collected)

    if len(pending) > 200:
        pending = pending[-200:]

    save_json(
        PENDING_FILE,
        pending
    )

    print(
        f"\nDEBUG: collected "
        f"{len(collected)} new articles."
    )

    print(
        f"DEBUG: pending queue now contains "
        f"{len(pending)} articles."
    )

    return collected


# =========================================================
# GROQ REQUEST
# =========================================================

def groq_request(messages):
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is missing."
        )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_completion_tokens": (
            GROQ_MAX_COMPLETION_TOKENS
        ),
        "reasoning_effort": "low",
        "include_reasoning": False,
        "response_format": {
            "type": "json_object"
        },
    }

    for attempt in range(3):
        try:
            response = requests.post(
                GROQ_URL,
                headers=headers,
                json=payload,
                timeout=180
            )

            print(
                f"Groq HTTP "
                f"{response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()

                content = (
                    data["choices"][0]
                    ["message"]["content"]
                )

                return json.loads(content)

            if response.status_code == 429:
                retry_after = (
                    response.headers.get(
                        "retry-after"
                    )
                )

                wait_seconds = 30

                if retry_after:
                    try:
                        wait_seconds = int(
                            float(retry_after)
                        )
                    except Exception:
                        pass

                wait_seconds = min(
                    wait_seconds,
                    120
                )

                print(
                    f"Rate limit reached. "
                    f"Waiting "
                    f"{wait_seconds} seconds..."
                )

                time.sleep(
                    wait_seconds
                )

                continue

            print(
                "Groq error:",
                response.text[:1000]
            )

        except Exception as e:
            print(
                f"Groq request error: {e}"
            )

            if attempt < 2:
                time.sleep(15)

    return None


# =========================================================
# AI ANALYSIS
# =========================================================

def analyze_batch(batch):
    compact_articles = []

    for article in batch:
        compact_articles.append({
            "id": article["id"],
            "title": article["title"],
            "category": article["category"],
            "source": article["source"],
            "summary": article["summary"],
            "content": article["content"],
        })

    system_prompt = """
تو سردبیر یک خبرنامه روزانه فارسی هستی.

برای هر خبر:
1. اهمیت آن را از 1 تا 5 تعیین کن.
2. یک خلاصه فارسی بسیار کوتاه و دقیق بنویس.

اهمیت:
5 = بسیار مهم و دارای اثر گسترده
4 = مهم و قابل توجه
3 = نسبتاً مهم
2 = کم‌اهمیت
1 = کم‌ارزش برای خبرنامه

از حدس زدن یا اضافه کردن اطلاعاتی که در متن نیست خودداری کن.

برای هر خبر حداکثر دو جمله خلاصه بنویس.

خروجی فقط JSON باشد:

{
  "articles": [
    {
      "id": "...",
      "importance": 1,
      "summary_fa": "..."
    }
  ]
}

تمام شناسه‌های ورودی را حفظ کن.
"""

    user_prompt = json.dumps(
        compact_articles,
        ensure_ascii=False
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

    result = groq_request(
        messages
    )

    if not result:
        return []

    analyses = result.get(
        "articles",
        []
    )

    if not isinstance(
        analyses,
        list
    ):
        return []

    return analyses


def analyze_articles(articles):
    batches = [
        articles[i:i + BATCH_SIZE]
        for i in range(
            0,
            len(articles),
            BATCH_SIZE
        )
    ]

    print(
        f"DEBUG: analyzing "
        f"{len(articles)} articles "
        f"in {len(batches)} batches "
        f"of up to {BATCH_SIZE} articles."
    )

    all_analyses = []

    for index, batch in enumerate(
        batches,
        start=1
    ):

        print(
            f"DEBUG: analyzing batch "
            f"{index}/{len(batches)}..."
        )

        analyses = analyze_batch(
            batch
        )

        returned_ids = {
            item.get("id")
            for item in analyses
            if isinstance(
                item,
                dict
            )
        }

        missing = [
            article["title"]
            for article in batch
            if article["id"]
            not in returned_ids
        ]

        print(
            f"batch {index}: "
            f"{len(analyses)} analyses"
        )

        if missing:
            for title in missing:
                print(
                    f"  missing: {title}"
                )

        all_analyses.extend(
            analyses
        )

        if index < len(batches):
            time.sleep(
                GROQ_DELAY_SECONDS
            )

    print(
        f"DEBUG: total successfully "
        f"analyzed: {len(all_analyses)}"
    )

    return all_analyses


# =========================================================
# TEXT / TOPIC SIMILARITY
# =========================================================

def title_similarity(a, b):
    title_a = normalize_text(
        a.get("title", "")
    )

    title_b = normalize_text(
        b.get("title", "")
    )

    if not title_a or not title_b:
        return 0.0

    return SequenceMatcher(
        None,
        title_a,
        title_b
    ).ratio()


def combined_similarity(a, b):
    title_a = normalize_text(
        a.get("title", "")
    )

    title_b = normalize_text(
        b.get("title", "")
    )

    summary_a = normalize_text(
        a.get("summary_fa", "")
    )

    summary_b = normalize_text(
        b.get("summary_fa", "")
    )

    if not title_a or not title_b:
        return 0.0

    title_score = SequenceMatcher(
        None,
        title_a,
        title_b
    ).ratio()

    summary_score = 0.0

    if summary_a and summary_b:
        summary_score = SequenceMatcher(
            None,
            summary_a,
            summary_b
        ).ratio()

    return (
        title_score * 0.7
        + summary_score * 0.3
    )


# =========================================================
# TOKEN-BASED TOPIC SIMILARITY
# =========================================================

STOPWORDS = {
    "the", "a", "an", "and", "or", "of",
    "to", "in", "on", "for", "with",
    "as", "is", "are", "from", "by",
    "at", "after", "before", "during",
    "says", "said", "new", "news",
    "live", "how", "what", "why",

    "و", "در", "به", "از", "با",
    "برای", "که", "این", "آن",
    "را", "بر", "تا", "یک",
    "می", "شود", "شد", "است",
    "های", "ای", "اگر", "پس",
    "اما", "یا", "هم", "کرد",
    "کرده", "درباره", "روی",
}


def meaningful_tokens(text):
    text = normalize_text(text)

    # نگه داشتن کلمات فارسی و انگلیسی
    tokens = re.findall(
        r"[a-zA-Z0-9\u0600-\u06FF]+",
        text
    )

    result = set()

    for token in tokens:

        if len(token) < 3:
            continue

        if token in STOPWORDS:
            continue

        result.add(token)

    return result


def token_overlap(a, b):
    tokens_a = meaningful_tokens(
        a.get("title", "")
    )

    tokens_b = meaningful_tokens(
        b.get("title", "")
    )

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = (
        tokens_a & tokens_b
    )

    union = (
        tokens_a | tokens_b
    )

    if not union:
        return 0.0

    return len(intersection) / len(union)


def topic_similarity(a, b):
    """
    ترکیب چند معیار برای تشخیص اینکه دو خبر
    احتمالاً درباره یک رویداد/موضوع واحد هستند.
    """

    title_score = title_similarity(
        a,
        b
    )

    combined_score = combined_similarity(
        a,
        b
    )

    overlap_score = token_overlap(
        a,
        b
    )

    # اگر عنوان تقریباً یکسان باشد،
    # تقریباً قطعی است که خبر تکراری است.
    if title_score >= 0.82:
        return 1.0

    # اگر چند کلمه کلیدی اصلی مشترک باشند
    # و عنوان‌ها هم شباهت مناسبی داشته باشند.
    if (
        overlap_score >= 0.45
        and title_score >= 0.55
    ):
        return 0.90

    # اگر عنوان‌ها خیلی نزدیک باشند.
    if combined_score >= 0.78:
        return 0.85

    return max(
        combined_score,
        overlap_score * 0.85
    )


# =========================================================
# SEMANTIC / TOPIC DEDUPLICATION
# =========================================================

def semantic_deduplicate(
    analyzed_articles
):
    """
    حذف خبرهای تقریباً تکراری یا مربوط به
    یک رویداد واحد.

    در صورت تشخیص شباهت:
    - اهمیت بالاتر اولویت دارد.
    - در اهمیت برابر، خبر جدیدتر حفظ می‌شود.
    """

    if not analyzed_articles:
        return []

    sorted_articles = sorted(
        analyzed_articles,
        key=lambda x: (
            int(
                x.get(
                    "importance",
                    0
                )
            ),
            x.get(
                "published",
                ""
            )
        ),
        reverse=True
    )

    kept = []

    for article in sorted_articles:

        duplicate_found = False

        for existing in kept:

            score = topic_similarity(
                article,
                existing
            )

            if score >= 0.85:

                duplicate_found = True

                print(
                    "DEBUG: related/duplicate "
                    "story removed:"
                )

                print(
                    f"  REMOVE: "
                    f"{article.get('title')}"
                )

                print(
                    f"  KEEP:   "
                    f"{existing.get('title')}"
                )

                print(
                    f"  topic similarity: "
                    f"{score:.2f}"
                )

                break

        if not duplicate_found:
            kept.append(
                article
            )

    print(
        f"DEBUG: semantic/topic "
        f"deduplication: "
        f"{len(analyzed_articles)} "
        f"-> {len(kept)}"
    )

    return kept


# =========================================================
# FINAL SELECTION
# =========================================================

def select_final_news(
    analyzed_articles
):
    candidates = []

    for article in analyzed_articles:

        try:
            importance = int(
                article.get(
                    "importance",
                    0
                )
            )
        except Exception:
            importance = 0

        if importance < MIN_IMPORTANCE:
            continue

        article = dict(
            article
        )

        article["importance"] = (
            importance
        )

        candidates.append(
            article
        )

    # -----------------------------------------------------
    # مرحله اول:
    # اول اهمیت، سپس تازگی
    # -----------------------------------------------------

    candidates.sort(
        key=lambda x: (
            x["importance"],
            x.get(
                "published",
                ""
            )
        ),
        reverse=True
    )

    # -----------------------------------------------------
    # مرحله دوم:
    # تنوع دسته‌ها
    #
    # حداکثر 2 خبر از هر دسته در پاس اول
    # -----------------------------------------------------

    selected = []
    category_counts = {}

    for article in candidates:

        category = article.get(
            "category",
            "سایر"
        )

        count = category_counts.get(
            category,
            0
        )

        if count >= 2:
            continue

        selected.append(
            article
        )

        category_counts[category] = (
            count + 1
        )

        if len(selected) >= MAX_FINAL_NEWS:
            break

    # -----------------------------------------------------
    # اگر کمتر از 10 خبر داشتیم، از باقی خبرها پر می‌کنیم
    # -----------------------------------------------------

    if len(selected) < MAX_FINAL_NEWS:

        selected_ids = {
            article["id"]
            for article in selected
        }

        for article in candidates:

            if article["id"] in selected_ids:
                continue

            selected.append(
                article
            )

            if len(selected) >= MAX_FINAL_NEWS:
                break

    # -----------------------------------------------------
    # مرتب‌سازی نهایی:
    # اهمیت بالاتر همیشه بالاتر نمایش داده شود.
    # -----------------------------------------------------

    selected.sort(
        key=lambda x: (
            x["importance"],
            x.get(
                "published",
                ""
            )
        ),
        reverse=True
    )

    return selected


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def build_digest_message(
    final_news
):
    if not final_news:
        return (
            "📰 <b>خبرنامه روزانه</b>\n\n"
            "امروز خبر مهمی با اهمیت کافی "
            "برای ارسال پیدا نشد."
        )

    lines = []

    lines.append(
        "📰 <b>خبرنامه روزانه</b>"
    )

    lines.append(
        "📅 "
        + jalali_date_string(
            datetime.now(IRAN_TZ)
        )
    )

    lines.append("")

    for index, article in enumerate(
        final_news,
        start=1
    ):

        title = escape(
            article.get(
                "title",
                ""
            )
        )

        category = escape(
            article.get(
                "category",
                ""
            )
        )

        source = escape(
            article.get(
                "source",
                ""
            )
        )

        summary = escape(
            article.get(
                "summary_fa",
                ""
            )
        )

        url = article.get(
            "url",
            ""
        )

        lines.append(
            f"<b>{index}. {title}</b>"
        )

        lines.append(
            f"🏷 {category} | {source}"
        )

        if summary:
            lines.append(
                f"📝 {summary}"
            )

        if url:
            lines.append(
                f'<a href="'
                f'{html.escape(url, quote=True)}'
                f'">🔗 منبع خبر</a>'
            )

        lines.append("")

    return "\n".join(
        lines
    )


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(
    message
):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing."
        )

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=60
    )

    print(
        f"Telegram HTTP "
        f"{response.status_code}"
    )

    if response.status_code != 200:
        print(
            "Telegram error:",
            response.text[:1000]
        )
        return False

    return True


# =========================================================
# DIGEST
# =========================================================

def create_digest():
    print(
        "DEBUG: starting daily digest..."
    )

    pending = load_json(
        PENDING_FILE,
        []
    )

    print(
        f"DEBUG: pending queue "
        f"contains {len(pending)} articles."
    )

    if not pending:
        print(
            "DEBUG: no pending articles."
        )
        return

    pending_sorted = sorted(
        pending,
        key=lambda x: x.get(
            "published",
            ""
        ),
        reverse=True
    )

    articles_for_ai = (
        pending_sorted[
            :MAX_ARTICLES_FOR_AI
        ]
    )

    print(
        f"DEBUG: sending "
        f"{len(articles_for_ai)} articles "
        f"to batch analysis."
    )

    analyses = analyze_articles(
        articles_for_ai
    )

    if not analyses:
        print(
            "DEBUG: no successful "
            "AI analyses."
        )
        return

    article_map = {
        article["id"]: article
        for article in articles_for_ai
    }

    analyzed_articles = []

    for analysis in analyses:

        if not isinstance(
            analysis,
            dict
        ):
            continue

        article_id = analysis.get(
            "id"
        )

        if article_id not in article_map:
            continue

        article = dict(
            article_map[article_id]
        )

        try:
            importance = int(
                analysis.get(
                    "importance",
                    0
                )
            )
        except Exception:
            importance = 0

        article["importance"] = (
            importance
        )

        article["summary_fa"] = (
            str(
                analysis.get(
                    "summary_fa",
                    ""
                )
            ).strip()
        )

        analyzed_articles.append(
            article
        )

    # =====================================================
    # STEP 1:
    # حذف اخبار تکراری / مربوط به یک رویداد
    # =====================================================

    analyzed_articles = (
        semantic_deduplicate(
            analyzed_articles
        )
    )

    # =====================================================
    # STEP 2:
    # انتخاب نهایی با تنوع موضوعی
    # =====================================================

    final_news = select_final_news(
        analyzed_articles
    )

    print(
        f"DEBUG: locally selected "
        f"{len(final_news)} final articles."
    )

    for index, article in enumerate(
        final_news,
        start=1
    ):
        print(
            f"#{index} "
            f"[{article.get('importance')}] "
            f"{article.get('title')}"
        )

    message = build_digest_message(
        final_news
    )

    sent = send_telegram(
        message
    )

    if not sent:
        print(
            "ERROR: Telegram message failed."
        )
        return

    print(
        "DEBUG: Telegram message "
        "sent successfully."
    )

    # =====================================================
    # حذف خبرهای تحلیل‌شده موفق از pending
    # =====================================================

    successful_ids = {
        article["id"]
        for article in analyzed_articles
    }

    if successful_ids:

        seen = load_json(
            SEEN_FILE,
            []
        )

        existing_seen_ids = set()

        for item in seen:
            if isinstance(
                item,
                dict
            ):
                existing_seen_ids.add(
                    item.get("id")
                )
            else:
                existing_seen_ids.add(
                    str(item)
                )

        for article in analyzed_articles:

            article_id = article["id"]

            if article_id in existing_seen_ids:
                continue

            seen.append({
                "id": article_id,
                "title": article.get(
                    "title",
                    ""
                ),
                "source": article.get(
                    "source",
                    ""
                ),
                "processed_at": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )
            })

        save_json(
            SEEN_FILE,
            seen
        )

        pending = [
            article
            for article in pending
            if article.get("id")
            not in successful_ids
        ]

        save_json(
            PENDING_FILE,
            pending
        )

    print(
        f"DEBUG: {len(successful_ids)} "
        f"analyzed articles processed."
    )

    print(
        f"DEBUG: {len(pending)} "
        f"articles remain pending."
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
        return

    mode = sys.argv[1].lower()

    if mode == "collect":
        collect_news()

    elif mode == "digest":
        create_digest()

    else:
        print(
            f"Unknown mode: {mode}"
        )


if __name__ == "__main__":
    main()
