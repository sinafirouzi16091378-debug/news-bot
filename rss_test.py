import requests
import xml.etree.ElementTree as ET


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


def local_name(tag):
    """Remove XML namespace and return the simple tag name."""
    if "}" in tag:
        tag = tag.split("}", 1)[1]

    if ":" in tag:
        tag = tag.split(":", 1)[1]

    return tag.lower()


def test_feed(name, category, url):
    try:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/153.0 Safari/537.36"
                )
            },
        )

        response.raise_for_status()

        root = ET.fromstring(response.content)
        root_name = local_name(root.tag)

        if root_name not in ("rss", "rdf", "feed"):
            return "FAIL", f"Unknown XML root: {root.tag}"

        article_count = 0

        for element in root.iter():
            tag = local_name(element.tag)

            if tag in ("item", "entry"):
                article_count += 1

        if article_count == 0:
            return "WARN", "Valid RSS/Atom but 0 articles"

        return "OK", f"{article_count} articles"

    except requests.exceptions.Timeout:
        return "FAIL", "Request timeout"

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        return "FAIL", f"HTTP {status}"

    except ET.ParseError as e:
        return "FAIL", f"XML parse error: {e}"

    except requests.exceptions.RequestException as e:
        return "FAIL", f"Request error: {e}"

    except Exception as e:
        return "FAIL", f"{type(e).__name__}: {e}"


def main():
    print()
    print("RSS FEED TEST")
    print("=" * 60)

    results = {
        "OK": 0,
        "WARN": 0,
        "FAIL": 0,
    }

    current_category = None

    for name, category, url in FEEDS:

        if category != current_category:
            print()
            print(f"### {category}")
            current_category = category

        status, message = test_feed(name, category, url)

        results[status] += 1

        print(f"[{status}] {name}: {message}")

    print()
    print("=" * 60)
    print("SUMMARY")
    print(f"Total feeds: {len(FEEDS)}")
    print(f"OK: {results['OK']}")
    print(f"WARN: {results['WARN']}")
    print(f"FAIL: {results['FAIL']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
