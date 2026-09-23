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

    ("هوش مصنوعی و فناوری", "MIT CSAIL", "https://www.csail.mit.edu/news/feed"),
    (
        "هوش مصنوعی و فناوری",
        "The Guardian AI",
        "https://www.theguardian.com/technology/artificialintelligenceai/rss",
    ),

    ("اقتصاد و بازارها", "ECB", "https://www.ecb.europa.eu/rss/press.html"),
    (
        "اقتصاد و بازارها",
        "Federal Reserve",
        "https://www.federalreserve.gov/feeds/press_all.xml",
    ),

    ("جهان", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    (
        "جهان",
        "Reuters",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCmC3M5e1s8wM3l6Y8J3j7Vw",
    ),

    (
        "ایران",
        "Tasnim",
        "https://www.tasnimnews.com/fa/rss/feed/1/0/0/%D8%A7%D8%AE%D8%A8%D8%A7%D8%B1",
    ),
    (
        "ایران",
        "Radio Farda",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCxJ4Qb7Wf1b8GJY7XJQkXxQ",
    ),
    (
        "ایران",
        "BBC Persian",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCc5P6Y5Jx5dG4j7n7QxQW2A",
    ),
]


# =========================================================
# BASIC HELPERS
# =========================================================

def normalize_text(text):
    if not text:
        return ""

    text = str(text).lower()

    replacements = {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "‌": " ",
        "\u200c": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\s+", " ", text).strip()

    return text


def escape(text):
    return html.escape(str(text or ""))


def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"WARNING: failed to load {path}: {e}")
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def article_similarity(a, b):
    a_title = normalize_text(a.get("title", ""))
    b_title = normalize_text(b.get("title", ""))

    if not a_title or not b_title:
        return 0.0

    return SequenceMatcher(None, a_title, b_title).ratio()


def is_duplicate(article, existing_articles):
    for existing in existing_articles:
        if article_similarity(article, existing) >= 0.90:
            return True

    return False


def clean_url(url):
    if not url:
        return ""

    url = str(url).strip()

    url = re.sub(r"[?#].*$", "", url)

    return url


# =========================================================
# DATE HELPERS
# =========================================================

def get_entry_date(entry):
    for key in ["published_parsed", "updated_parsed", "created_parsed"]:
        value = entry.get(key)

        if value:
            try:
                return datetime(
                    value.tm_year,
                    value.tm_mon,
                    value.tm_mday,
                    value.tm_hour,
                    value.tm_min,
                    value.tm_sec,
                    tzinfo=timezone.utc,
                ).astimezone(IRAN_TZ)
            except Exception:
                pass

    return datetime.now(IRAN_TZ)


def today_iran():
    return datetime.now(IRAN_TZ).date()


# =========================================================
# JALALI DATE
# =========================================================

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

    while (
        i < 11
        and j_day_no >= j_days_in_month[i]
    ):
        j_day_no -= j_days_in_month[i]
        i += 1

    jm = i + 1
    jd = j_day_no + 1

    return jy, jm, jd


def to_persian_digits(text):
    return str(text).translate(PERSIAN_DIGITS)


def jalali_date_string(dt):
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
# COLLECT NEWS
# =========================================================

def collect_news():
    print("DEBUG: starting collection...")

    seen = load_json(SEEN_FILE, [])
    pending = load_json(PENDING_FILE, [])

    if not isinstance(seen, list):
        seen = []

    if not isinstance(pending, list):
        pending = []

    seen_ids = set(str(x) for x in seen)

    existing_ids = set()

    for article in pending:
        article_id = article.get("id")

        if article_id:
            existing_ids.add(str(article_id))

    collected = []

    today = today_iran()

    for category, source, url in FEEDS:
        print(f"DEBUG: reading {source}...")

        try:
            feed = feedparser.parse(url)

            if getattr(feed, "bozo", False):
                if source == "Tasnim":
                    print(
                        "WARNING: feed parser warning for Tasnim"
                    )

            count = 0

            for entry in feed.entries[:30]:
                published_dt = get_entry_date(entry)

                if published_dt.date() != today:
                    continue

                title = (
                    entry.get("title")
                    or ""
                ).strip()

                link = clean_url(
                    entry.get("link")
                    or ""
                )

                summary = (
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                ).strip()

                if not title or not link:
                    continue

                article_id = (
                    f"{source}|"
                    f"{normalize_text(title)}|"
                    f"{link}"
                )

                if article_id in seen_ids:
                    continue

                if article_id in existing_ids:
                    continue

                article = {
                    "id": article_id,
                    "title": title,
                    "url": link,
                    "source": source,
                    "category": category,
                    "summary": summary[:MAX_SUMMARY_CHARS],
                    "content": summary[:MAX_CONTENT_CHARS],
                    "published": published_dt.isoformat(),
                }

                if is_duplicate(
                    article,
                    pending + collected
                ):
                    continue

                collected.append(article)
                existing_ids.add(article_id)

                count += 1

            print(
                f"DEBUG: {source}: "
                f"{count} new articles"
            )

        except Exception as e:
            print(
                f"WARNING: failed to collect "
                f"{source}: {e}"
            )

    pending.extend(collected)

    pending.sort(
        key=lambda x: x.get("published", ""),
        reverse=True
    )

    pending = pending[:200]

    save_json(PENDING_FILE, pending)

    print(
        f"DEBUG: collected {len(collected)} "
        f"new articles."
    )

    print(
        f"DEBUG: pending queue now contains "
        f"{len(pending)} articles."
    )


# =========================================================
# GROQ
# =========================================================

def groq_request(messages):
    if not GROQ_API_KEY:
        print("ERROR: GROQ_API_KEY is missing.")
        return None

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_completion_tokens": GROQ_MAX_COMPLETION_TOKENS,
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
                timeout=180,
            )

            print(
                f"Groq HTTP {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()

                content = (
                    data["choices"][0]["message"]
                    ["content"]
                )

                return json.loads(content)

            if response.status_code == 429:

                retry_after = response.headers.get(
                    "retry-after"
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
                    max(wait_seconds, 10),
                    120
                )

                print(
                    f"DEBUG: rate limited. "
                    f"waiting {wait_seconds}s..."
                )

                time.sleep(wait_seconds)
                continue

            print(
                "WARNING: Groq request failed:"
                f" {response.text[:500]}"
            )

        except Exception as e:
            print(
                f"WARNING: Groq request error: {e}"
            )

        if attempt < 2:
            time.sleep(10)

    return None


def analyze_batch(batch):
    articles_for_ai = []

    for article in batch:
        articles_for_ai.append({
            "id": article["id"],
            "title": article["title"],
            "source": article["source"],
            "category": article["category"],
            "content": (
                article.get("content", "")
                [:MAX_CONTENT_CHARS]
            ),
            "summary": (
                article.get("summary", "")
                [:MAX_SUMMARY_CHARS]
            ),
        })

    system_prompt = """
You are a neutral news editor.

Analyze the supplied news articles.

For each article return:
- id
- importance: integer from 1 to 5
- summary_fa: concise Persian summary in no more than two sentences

Importance should reflect:
5 = major international, national, scientific,
medical, economic or technological significance
4 = clearly significant
3 = useful and relevant
2 = minor
1 = low-value

Do not invent facts.
Do not combine different stories.
Keep summaries factual and neutral.

Return valid JSON only:

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

    user_prompt = json.dumps(
        {
            "articles": articles_for_ai
        },
        ensure_ascii=False
    )

    result = groq_request([
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": user_prompt
        }
    ])

    if not result:
        return []

    analyses = result.get("articles", [])

    if not isinstance(analyses, list):
        return []

    return analyses


def analyze_articles(articles):
    print(
        f"DEBUG: analyzing {len(articles)} articles "
        f"in batches of {BATCH_SIZE}."
    )

    all_analyses = []

    total_batches = (
        (len(articles) + BATCH_SIZE - 1)
        // BATCH_SIZE
    )

    for i in range(
        0,
        len(articles),
        BATCH_SIZE
    ):
        batch = articles[
            i:i + BATCH_SIZE
        ]

        batch_number = (
            i // BATCH_SIZE
        ) + 1

        print(
            f"DEBUG: analyzing batch "
            f"{batch_number}/{total_batches}..."
        )

        analyses = analyze_batch(batch)

        returned_ids = set()

        for item in analyses:
            article_id = item.get("id")

            if article_id:
                returned_ids.add(
                    str(article_id)
                )

        for article in batch:
            if article["id"] not in returned_ids:
                print(
                    f"  missing: "
                    f"{article['title']}"
                )

        print(
            f"  batch {batch_number}: "
            f"{len(analyses)} analyses"
        )

        all_analyses.extend(analyses)

        if (
            i + BATCH_SIZE
            < len(articles)
        ):
            time.sleep(GROQ_DELAY_SECONDS)

    print(
        f"DEBUG: total successfully analyzed: "
        f"{len(all_analyses)}"
    )

    return all_analyses


# =========================================================
# IMPROVED TOPIC / EVENT DEDUPLICATION
# =========================================================

STOPWORDS = {
    # English
    "the", "a", "an", "and", "or", "of",
    "to", "in", "on", "for", "with",
    "as", "is", "are", "from", "by",
    "at", "after", "before", "during",
    "says", "said", "new", "news",
    "live", "how", "what", "why",
    "this", "that", "these", "those",
    "will", "would", "could",
    "about", "into", "over", "under",
    "than", "their", "they", "them",
    "its", "his", "her", "our",
    "you", "your", "has", "have",
    "had", "been", "being",
    "more", "most", "some",
    "after", "ahead",

    # Persian
    "و", "در", "به", "از", "با",
    "برای", "که", "این", "آن",
    "را", "بر", "تا", "یک",
    "می", "شود", "شد", "است",
    "های", "ای", "اگر", "پس",
    "اما", "یا", "هم", "کرد",
    "کرده", "درباره", "روی",
    "برای", "پس", "نیز",
    "خواهد", "گفت", "کردند",
    "شدند", "استفاده",
    "برابر", "جدید",
}


# کلمات خیلی عمومی که برای تشخیص «رویداد واحد» ارزش کمی دارند
GENERIC_EVENT_WORDS = {
    "government",
    "president",
    "minister",
    "officials",
    "official",
    "country",
    "countries",
    "world",
    "international",
    "global",
    "report",
    "reports",
    "statement",
    "says",
    "said",
    "news",
    "latest",
    "update",
    "un",
    "assembly",
    "امریکا",
    "آمریکا",
    "ایران",
    "کشور",
    "دولت",
    "رئیس",
    "رییس",
    "مقام",
    "مقامات",
    "جهان",
    "بینالمللی",
    "گزارش",
    "خبر",
    "بیانیه",
}


def meaningful_tokens(text):
    text = normalize_text(text)

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


def strong_tokens(text):
    tokens = meaningful_tokens(text)

    return {
        token
        for token in tokens
        if token not in GENERIC_EVENT_WORDS
    }


def article_topic_text(article):
    title = article.get("title", "")
    summary = article.get("summary_fa", "")

    return (
        f"{title} {title} "
        f"{summary}"
    )


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
    text_a = normalize_text(
        article_topic_text(a)
    )

    text_b = normalize_text(
        article_topic_text(b)
    )

    if not text_a or not text_b:
        return 0.0

    return SequenceMatcher(
        None,
        text_a,
        text_b
    ).ratio()


def token_overlap(a, b):
    tokens_a = strong_tokens(
        article_topic_text(a)
    )

    tokens_b = strong_tokens(
        article_topic_text(b)
    )

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = (
        tokens_a & tokens_b
    )

    union = (
        tokens_a | tokens_b
    )

    return (
        len(intersection)
        / len(union)
    )


def shared_token_count(a, b):
    tokens_a = strong_tokens(
        article_topic_text(a)
    )

    tokens_b = strong_tokens(
        article_topic_text(b)
    )

    return len(tokens_a & tokens_b)


def sorted_token_similarity(a, b):
    tokens_a = sorted(
        strong_tokens(
            article_topic_text(a)
        )
    )

    tokens_b = sorted(
        strong_tokens(
            article_topic_text(b)
        )
    )

    if not tokens_a or not tokens_b:
        return 0.0

    return SequenceMatcher(
        None,
        " ".join(tokens_a),
        " ".join(tokens_b)
    ).ratio()


def same_story(a, b):
    """
    Conservative local detector for articles
    describing the same event/story.
    """

    title_a = normalize_text(
        a.get("title", "")
    )

    title_b = normalize_text(
        b.get("title", "")
    )

    # -----------------------------------------------------
    # 1. Exact same normalized title
    # -----------------------------------------------------

    if title_a and title_a == title_b:
        return True, 1.00, "exact title"


    # -----------------------------------------------------
    # 2. Very similar titles
    # -----------------------------------------------------

    title_score = title_similarity(a, b)

    if title_score >= 0.88:
        return True, title_score, "title similarity"


    # -----------------------------------------------------
    # 3. Title + summary similarity
    # -----------------------------------------------------

    combined_score = combined_similarity(a, b)

    if combined_score >= 0.82:
        return True, combined_score, "combined similarity"


    # -----------------------------------------------------
    # 4. Shared strong content words
    # -----------------------------------------------------

    overlap = token_overlap(a, b)
    shared = shared_token_count(a, b)
    sorted_score = sorted_token_similarity(a, b)

    # 3+ strong words shared + reasonable overlap
    if shared >= 3 and overlap >= 0.30:
        score = max(
            0.85,
            min(
                0.95,
                0.70 + overlap
            )
        )

        return True, score, "shared topic entities"


    # 4+ strong words shared can compensate for
    # lower Jaccard when titles are phrased differently.
    if shared >= 4 and overlap >= 0.25:
        return True, 0.86, "shared event terms"


    # -----------------------------------------------------
    # 5. Similar sets of important words
    # -----------------------------------------------------

    if (
        shared >= 3
        and sorted_score >= 0.70
    ):
        return True, 0.85, "topic token similarity"


    return False, max(
        title_score,
        combined_score,
        overlap
    ), "different"


def semantic_deduplicate(analyzed_articles):

    if not analyzed_articles:
        return []

    # -----------------------------------------------------
    # Remove exact duplicate IDs first
    # -----------------------------------------------------

    unique_by_id = {}

    for article in analyzed_articles:

        article_id = str(
            article.get("id", "")
        )

        if not article_id:
            continue

        if article_id not in unique_by_id:
            unique_by_id[article_id] = article

    articles = list(
        unique_by_id.values()
    )

    # -----------------------------------------------------
    # Sort so higher-importance / newer stories become
    # representatives of their topic clusters.
    # -----------------------------------------------------

    articles.sort(
        key=lambda x: (
            int(x.get("importance", 0)),
            x.get("published", "")
        ),
        reverse=True
    )

    n = len(articles)

    # -----------------------------------------------------
    # Union-Find clustering
    # -----------------------------------------------------

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]

        return x

    def union(x, y):
        root_x = find(x)
        root_y = find(y)

        if root_x != root_y:
            parent[root_y] = root_x

    # -----------------------------------------------------
    # Compare every pair.
    # This is only 25 articles, so the computational cost
    # is negligible and no API call is required.
    # -----------------------------------------------------

    for i in range(n):

        for j in range(i + 1, n):

            matched, score, reason = same_story(
                articles[i],
                articles[j]
            )

            if matched:

                union(i, j)

    # -----------------------------------------------------
    # Build clusters
    # -----------------------------------------------------

    clusters = {}

    for i in range(n):

        root = find(i)

        clusters.setdefault(
            root,
            []
        ).append(i)

    kept = []

    # -----------------------------------------------------
    # Select one representative per cluster
    # -----------------------------------------------------

    for cluster_indices in clusters.values():

        cluster_articles = [
            articles[i]
            for i in cluster_indices
        ]

        cluster_articles.sort(
            key=lambda x: (
                int(x.get("importance", 0)),
                x.get("published", "")
            ),
            reverse=True
        )

        representative = (
            cluster_articles[0]
        )

        kept.append(
            representative
        )

        if len(cluster_articles) > 1:

            for removed in cluster_articles[1:]:

                matched, score, reason = same_story(
                    representative,
                    removed
                )

                print(
                    "DEBUG: related/duplicate "
                    "story removed:"
                )

                print(
                    f"  REMOVE: "
                    f"{removed.get('title')}"
                )

                print(
                    f"  KEEP:   "
                    f"{representative.get('title')}"
                )

                print(
                    f"  topic similarity: "
                    f"{score:.2f}"
                    f" ({reason})"
                )

    # -----------------------------------------------------
    # Final order
    # -----------------------------------------------------

    kept.sort(
        key=lambda x: (
            int(x.get("importance", 0)),
            x.get("published", "")
        ),
        reverse=True
    )

    print(
        "DEBUG: semantic/topic "
        f"deduplication: "
        f"{len(analyzed_articles)} -> "
        f"{len(kept)}"
    )

    return kept


# =========================================================
# FINAL NEWS SELECTION
# =========================================================

def select_final_news(articles):

    eligible = [
        article
        for article in articles
        if int(
            article.get("importance", 0)
        ) >= MIN_IMPORTANCE
    ]

    eligible.sort(
        key=lambda x: (
            int(x.get("importance", 0)),
            x.get("published", "")
        ),
        reverse=True
    )

    selected = []
    category_count = {}

    # -----------------------------------------------------
    # First pass: maximum 2 stories per category
    # -----------------------------------------------------

    for article in eligible:

        category = article.get(
            "category",
            "سایر"
        )

        count = category_count.get(
            category,
            0
        )

        if count >= 2:
            continue

        selected.append(article)

        category_count[category] = (
            count + 1
        )

        if len(selected) >= MAX_FINAL_NEWS:
            break

    # -----------------------------------------------------
    # Second pass: fill remaining places
    # -----------------------------------------------------

    if len(selected) < MAX_FINAL_NEWS:

        selected_ids = {
            article.get("id")
            for article in selected
        }

        for article in eligible:

            if article.get("id") in selected_ids:
                continue

            selected.append(article)

            if len(selected) >= MAX_FINAL_NEWS:
                break

    # -----------------------------------------------------
    # Final ranking
    # -----------------------------------------------------

    selected.sort(
        key=lambda x: (
            int(x.get("importance", 0)),
            x.get("published", "")
        ),
        reverse=True
    )

    return selected


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN missing."
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "ERROR: TELEGRAM_CHAT_ID missing."
        )
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=60,
        )

        print(
            f"Telegram HTTP "
            f"{response.status_code}"
        )

        if response.status_code == 200:

            print(
                "DEBUG: Telegram message "
                "sent successfully."
            )

            return True

        print(
            "WARNING: Telegram failed:"
            f" {response.text[:500]}"
        )

    except Exception as e:

        print(
            f"WARNING: Telegram error: {e}"
        )

    return False


def build_digest_message(articles):

    now = datetime.now(
        IRAN_TZ
    )

    date_text = jalali_date_string(now)

    lines = [
        "<b>📰 خبرنامه روزانه</b>",
        f"📅 {escape(date_text)}",
        "",
    ]

    for index, article in enumerate(
        articles,
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
                "سایر"
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
                f'🔗 <a href="{escape(url)}">'
                f"منبع خبر</a>"
            )

        lines.append("")

    return "\n".join(lines)


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

    seen = load_json(
        SEEN_FILE,
        []
    )

    if not isinstance(pending, list):
        pending = []

    if not isinstance(seen, list):
        seen = []

    print(
        f"DEBUG: pending queue contains "
        f"{len(pending)} articles."
    )

    if not pending:

        print(
            "DEBUG: no pending articles."
        )

        return

    pending.sort(
        key=lambda x: x.get(
            "published",
            ""
        ),
        reverse=True
    )

    batch = pending[
        :MAX_ARTICLES_FOR_AI
    ]

    print(
        f"DEBUG: sending "
        f"{len(batch)} articles "
        f"to batch analysis."
    )

    analyses = analyze_articles(
        batch
    )

    if not analyses:

        print(
            "WARNING: no successful "
            "AI analyses."
        )

        return

    article_map = {
        article["id"]: article
        for article in batch
    }

    analyzed_articles = []

    successful_ids = set()

    for analysis in analyses:

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
            analysis.get(
                "summary_fa",
                ""
            ).strip()
        )

        analyzed_articles.append(
            article
        )

        successful_ids.add(
            article_id
        )

    if not analyzed_articles:

        print(
            "WARNING: no valid analyzed "
            "articles."
        )

        return

    # -----------------------------------------------------
    # Topic / event deduplication
    # -----------------------------------------------------

    deduplicated = semantic_deduplicate(
        analyzed_articles
    )

    # -----------------------------------------------------
    # Final selection
    # -----------------------------------------------------

    final_articles = select_final_news(
        deduplicated
    )

    print(
        f"DEBUG: locally selected "
        f"{len(final_articles)} "
        f"final articles."
    )

    for i, article in enumerate(
        final_articles,
        start=1
    ):

        print(
            f"#{i} "
            f"[{article.get('importance')}] "
            f"{article.get('title')}"
        )

    if not final_articles:

        print(
            "DEBUG: no articles passed "
            "minimum importance."
        )

        return

    message = build_digest_message(
        final_articles
    )

    if not send_telegram(message):
        print(
            "WARNING: digest was not sent."
        )
        return

    # -----------------------------------------------------
    # Mark all successfully analyzed
    # articles as processed.
    # Failed AI analyses remain pending.
    # -----------------------------------------------------

    for article_id in successful_ids:

        if article_id not in seen:
            seen.append(article_id)

    pending = [
        article
        for article in pending
        if article.get("id")
        not in successful_ids
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
        f"DEBUG: "
        f"{len(successful_ids)} "
        f"analyzed articles processed."
    )

    print(
        f"DEBUG: "
        f"{len(pending)} "
        f"articles remain pending."
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if len(sys.argv) < 2:

        print(
            "Usage: "
            "python news_bot.py "
            "[collect|digest]"
        )

        return

    mode = sys.argv[1].strip().lower()

    if mode == "collect":
        collect_news()

    elif mode == "digest":
        create_digest()

    else:
        print(
            "Unknown mode. "
            "Use collect or digest."
        )


if __name__ == "__main__":
    main()
