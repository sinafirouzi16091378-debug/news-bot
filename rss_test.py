import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

FEEDS = [
    # =========================
    # 🩺 پزشکی و سلامت
    # =========================
    ("WHO", "پزشکی و سلامت",
     "https://www.who.int/rss-feeds/news-english.xml"),
    ("STAT", "پزشکی و سلامت",
     "https://www.statnews.com/feed/"),
    ("Medical Xpress", "پزشکی و سلامت",
     "https://medicalxpress.com/rss-feed/"),
    ("Nature Medicine", "پزشکی و سلامت",
     "https://www.nature.com/nm.rss"),
    ("ScienceDaily Health", "پزشکی و سلامت",
     "https://www.sciencedaily.com/rss/top/health.xml"),

    # =========================
    # 💰 اقتصاد و بازارها
    # =========================
    ("Federal Reserve", "اقتصاد و بازارها",
     "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB", "اقتصاد و بازارها",
     "https://www.ecb.europa.eu/rss/press.html"),
    ("IMF", "اقتصاد و بازارها",
     "https://www.imf.org/en/News/RSS"),
    ("World Bank", "اقتصاد و بازارها",
     "https://www.worldbank.org/en/news/all?display=feed"),
    ("CNBC", "اقتصاد و بازارها",
     "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("Financial Times", "اقتصاد و بازارها",
     "https://www.ft.com/rss/home"),

    # =========================
    # 🤖 هوش مصنوعی و فناوری
    # =========================
    ("MIT Technology Review", "هوش مصنوعی و فناوری",
     "https://www.technologyreview.com/feed/"),
    ("Ars Technica", "هوش مصنوعی و فناوری",
     "https://feeds.arstechnica.com/arstechnica/index"),
    ("The Verge", "هوش مصنوعی و فناوری",
     "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch", "هوش مصنوعی و فناوری",
     "https://techcrunch.com/feed/"),
    ("WIRED", "هوش مصنوعی و فناوری",
     "https://www.wired.com/feed/rss"),
    ("IEEE Spectrum", "هوش مصنوعی و فناوری",
     "https://spectrum.ieee.org/feeds/feed.rss"),

    # =========================
    # 🔬 علم
    # =========================
    ("Nature", "علم",
     "https://www.nature.com/nature.rss"),
    ("Science", "علم",
     "https://www.science.org/rss/news_current.xml"),
    ("NASA", "علم",
     "https://www.nasa.gov/news-release/feed/"),
    ("New Scientist", "علم",
     "https://www.newscientist.com/feed/home/"),
    ("MIT News", "علم",
     "https://news.mit.edu/rss/feed"),
    ("ScienceDaily Science", "علم",
     "https://www.sciencedaily.com/rss/top/science.xml"),

    # =========================
    # 🇮🇷 ایران
    # =========================
    ("BBC Persian", "ایران",
     "https://feeds.bbci.co.uk/persian/rss.xml"),
    ("Radio Farda", "ایران",
     "https://en.radiofarda.com/api/zp_qmtl-vomx-tpe_bimr"),
    ("Tasnim", "ایران",
     "https://www.tasnimnews.ir/en/rss/feed/0/0/0/0/AllStories"),

    # =========================
    # 🌍 جهان
    # =========================
    ("BBC World", "جهان",
     "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "جهان",
     "https://www.aljazeera.com/xml/rss/all.xml"),
    ("DW", "جهان",
     "https://rss.dw.com/xml/rss-en-all"),
    ("France 24", "جهان",
     "https://www.france24.com/en/rss"),
    ("Euronews", "جهان",
     "https://www.euronews.com/rss"),
    ("The Guardian", "جهان",
     "https://www.theguardian.com/world/rss"),
]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PersonalNewsBot/1.0; "
        "+https://github.com/sinafirouzi16091378-debug/news-bot)"
    )
}


def test_feed(feed):
    name, category, url = feed

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True,
        )

        status = response.status_code

        if status != 200:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "detail": f"HTTP {status}",
            }

        content = response.content

        if not content:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "detail": "Empty response",
            }

        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "detail": f"Invalid XML: {str(e)[:100]}",
            }

        root_tag = root.tag.lower()

        # RSS / Atom detection
        is_rss = (
            "rss" in root_tag
            or "rdf" in root_tag
            or "feed" in root_tag
        )

        if not is_rss:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "WARN",
                "detail": f"XML but not recognized as RSS/Atom: {root.tag}",
            }

        # Count likely article entries
        items = []

        for element in root.iter():
            tag = element.tag.lower()

            if tag.endswith("item") or tag.endswith("entry"):
                items.append(element)

        if len(items) == 0:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "WARN",
                "detail": "Valid RSS/Atom but 0 articles",
            }

        return {
            "name": name,
            "category": category,
            "url": url,
            "status": "OK",
            "detail": f"{len(items)} articles",
        }

    except requests.exceptions.Timeout:
        return {
            "name": name,
            "category": category,
            "url": url,
            "status": "FAIL",
            "detail": "Timeout",
        }

    except requests.exceptions.RequestException as e:
        return {
            "name": name,
            "category": category,
            "url": url,
            "status": "FAIL",
            "detail": f"Request error: {str(e)[:100]}",
        }

    except Exception as e:
        return {
            "name": name,
            "category": category,
            "url": url,
            "status": "FAIL",
            "detail": f"Unexpected error: {str(e)[:100]}",
        }


def main():
    print("=" * 80)
    print("RSS FEED TEST")
    print("=" * 80)
    print(f"Testing {len(FEEDS)} feeds...\n")

    results = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(test_feed, feed): feed
            for feed in FEEDS
        }

        for future in as_completed(futures):
            results.append(future.result())

    # Sort by category then name
    results.sort(key=lambda x: (x["category"], x["name"]))

    ok_count = 0
    warn_count = 0
    fail_count = 0

    current_category = None

    for result in results:
        if result["category"] != current_category:
            current_category = result["category"]
            print("\n" + "=" * 80)
            print(current_category)
            print("=" * 80)

        status = result["status"]

        if status == "OK":
            symbol = "✅"
            ok_count += 1
        elif status == "WARN":
            symbol = "⚠️"
            warn_count += 1
        else:
            symbol = "❌"
            fail_count += 1

        print(
            f"{symbol} {result['name']:<25} | "
            f"{result['detail']}"
        )
        print(f"   {result['url']}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total : {len(results)}")
    print(f"OK    : {ok_count}")
    print(f"WARN  : {warn_count}")
    print(f"FAIL  : {fail_count}")
    print("=" * 80)

    # Test script itself should fail only if every feed failed
    if ok_count == 0:
        raise SystemExit("All RSS feeds failed!")


if __name__ == "__main__":
    main()
