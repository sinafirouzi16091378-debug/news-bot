```python
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed


FEEDS = [
    # پزشکی و سلامت
    ("WHO", "پزشکی و سلامت", "https://www.who.int/rss-feeds/news-english.xml"),
    ("STAT", "پزشکی و سلامت", "https://www.statnews.com/feed/"),
    ("Medical Xpress", "پزشکی و سلامت", "https://medicalxpress.com/rss-feed/"),
    ("Nature Medicine", "پزشکی و سلامت", "https://www.nature.com/nm.rss"),
    ("ScienceDaily Health", "پزشکی و سلامت", "https://www.sciencedaily.com/rss/top/health.xml"),

    # اقتصاد و بازارها
    ("Federal Reserve", "اقتصاد و بازارها", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB", "اقتصاد و بازارها", "https://www.ecb.europa.eu/rss/press.html"),
    ("BIS Media Releases", "اقتصاد و بازارها", "https://www.bis.org/doclist/all_pressrels.rss"),
    ("BIS Research", "اقتصاد و بازارها", "https://www.bis.org/doclist/bis_fsi_publs.rss"),
    ("CNBC", "اقتصاد و بازارها", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("Financial Times", "اقتصاد و بازارها", "https://www.ft.com/rss/home"),

    # هوش مصنوعی و فناوری
    ("MIT Technology Review", "هوش مصنوعی و فناوری", "https://www.technologyreview.com/feed/"),
    ("Ars Technica", "هوش مصنوعی و فناوری", "https://feeds.arstechnica.com/arstechnica/index"),
    ("The Verge", "هوش مصنوعی و فناوری", "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch", "هوش مصنوعی و فناوری", "https://techcrunch.com/feed/"),
    ("WIRED", "هوش مصنوعی و فناوری", "https://www.wired.com/feed/rss"),
    ("IEEE Spectrum", "هوش مصنوعی و فناوری", "https://spectrum.ieee.org/feeds/feed.rss"),

    # علم
    ("Nature", "علم", "https://www.nature.com/nature.rss"),
    ("APS Physics", "علم", "https://feeds.aps.org/rss/recent/physics.xml"),
    ("NASA", "علم", "https://www.nasa.gov/news-release/feed/"),
    ("New Scientist", "علم", "https://www.newscientist.com/feed/home/"),
    ("MIT News", "علم", "https://news.mit.edu/rss/feed"),
    ("ScienceDaily Science", "علم", "https://www.sciencedaily.com/rss/top/science.xml"),

    # ایران
    ("BBC Persian", "ایران", "https://feeds.bbci.co.uk/persian/rss.xml"),
    ("Radio Farda", "ایران", "https://en.radiofarda.com/api/zp_qmtl-vomx-tpe_bimr"),
    ("Tasnim", "ایران", "https://www.tasnimnews.ir/en/rss/feed/0/0/0/0/AllStories"),

    # جهان
    ("BBC World", "جهان", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "جهان", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("DW", "جهان", "https://rss.dw.com/xml/rss-en-all"),
    ("France 24", "جهان", "https://www.france24.com/en/rss"),
    ("Euronews", "جهان", "https://www.euronews.com/rss"),
    ("The Guardian", "جهان", "https://www.theguardian.com/world/rss"),
]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PersonalNewsBot/1.0; "
        "+https://github.com/sinafirouzi16091378-debug/news-bot)"
    )
}


def get_local_name(tag):
    """Remove XML namespace from a tag."""
    if "}" in tag:
        tag = tag.split("}", 1)[1]

    if ":" in tag:
        tag = tag.split(":", 1)[1]

    return tag.lower()


def count_articles(root):
    """Count RSS item / Atom entry elements regardless of namespace."""
    count = 0

    for element in root.iter():
        tag = get_local_name(element.tag)

        if tag in ("item", "entry"):
            count += 1

    return count


def test_feed(feed):
    name, category, url = feed

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True
        )

        if response.status_code != 200:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "message": f"HTTP {response.status_code}"
            }

        if not response.content:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "message": "Empty response"
            }

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "message": f"Invalid XML: {e}"
            }

        root_name = get_local_name(root.tag)

        # RSS 2.0
        # RDF/RSS 1.0
        # Atom
        if root_name not in ("rss", "rdf", "feed"):
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "message": f"Unknown XML root: {root.tag}"
            }

        article_count = count_articles(root)

        if article_count == 0:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "WARN",
                "message": "Valid RSS/Atom/RDF but 0 articles"
            }

        return {
            "name": name,
            "category": category,
            "url": url,
            "status": "OK",
            "message": f"{article_count} articles"
        }

    except requests.exceptions.RequestException as e:
        return {
            "name": name,
            "category": category,
            "url": url,
            "status": "FAIL",
            "message": f"Request error: {e}"
        }

    except Exception as e:
        return {
            "name": name,
            "category": category,
            "url": url,
            "status": "FAIL",
            "message": f"Unexpected error: {e}"
        }


def main():
    print("=" * 70)
    print("RSS FEED TEST")
    print("=" * 70)

    results = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(test_feed, feed)
            for feed in FEEDS
        ]

        for future in as_completed(futures):
            results.append(future.result())

    # حفظ ترتیب اصلی فیدها
    feed_order = {
        feed[0]: index
        for index, feed in enumerate(FEEDS)
    }

    results.sort(
        key=lambda result: feed_order[result["name"]]
    )

    # دسته‌بندی نتایج
    categories = {}

    for result in results:
        categories.setdefault(
            result["category"],
            []
        ).append(result)

    # نمایش نتایج
    for category, category_results in categories.items():

        print()
        print(f"### {category}")
        print("-" * 70)

        for result in category_results:

            if result["status"] == "OK":
                icon = "OK"
            elif result["status"] == "WARN":
                icon = "WARN"
            else:
                icon = "FAIL"

            print(
                f"[{icon}] "
                f"{result['name']}: "
                f"{result['message']}"
            )

            if result["status"] != "OK":
                print(
                    f"     URL: {result['url']}"
                )

    # خلاصه
    ok_count = sum(
        result["status"] == "OK"
        for result in results
    )

    warn_count = sum(
        result["status"] == "WARN"
        for result in results
    )

    fail_count = sum(
        result["status"] == "FAIL"
        for result in results
    )

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"Total feeds : {len(results)}")
    print(f"OK          : {ok_count}")
    print(f"WARN        : {warn_count}")
    print(f"FAIL        : {fail_count}")

    print()

    if fail_count == 0:
        print("All feeds are working!")
    elif ok_count == 0:
        print("All feeds failed!")
    else:
        print("Some feeds need attention.")


if __name__ == "__main__":
    main()
```
