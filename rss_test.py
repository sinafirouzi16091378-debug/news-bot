```python
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed


# =========================================================
# RSS FEEDS
# =========================================================

FEEDS = [
    # 🩺 پزشکی و سلامت
    ("WHO", "پزشکی و سلامت", "https://www.who.int/rss-feeds/news-english.xml"),
    ("STAT", "پزشکی و سلامت", "https://www.statnews.com/feed/"),
    ("Medical Xpress", "پزشکی و سلامت", "https://medicalxpress.com/rss-feed/"),
    ("Nature Medicine", "پزشکی و سلامت", "https://www.nature.com/nm.rss"),
    ("ScienceDaily Health", "پزشکی و سلامت", "https://www.sciencedaily.com/rss/top/health.xml"),

    # 💰 اقتصاد و بازارها
    ("Federal Reserve", "اقتصاد و بازارها", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB", "اقتصاد و بازارها", "https://www.ecb.europa.eu/rss/press.html"),
    ("BIS Media Releases", "اقتصاد و بازارها", "https://www.bis.org/doclist/all_pressrels.rss"),
    ("BIS Research", "اقتصاد و بازارها", "https://www.bis.org/doclist/bis_fsi_publs.rss"),
    ("CNBC", "اقتصاد و بازارها", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("Financial Times", "اقتصاد و بازارها", "https://www.ft.com/rss/home"),

    # 🤖 هوش مصنوعی و فناوری
    ("MIT Technology Review", "هوش مصنوعی و فناوری", "https://www.technologyreview.com/feed/"),
    ("Ars Technica", "هوش مصنوعی و فناوری", "https://feeds.arstechnica.com/arstechnica/index"),
    ("The Verge", "هوش مصنوعی و فناوری", "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch", "هوش مصنوعی و فناوری", "https://techcrunch.com/feed/"),
    ("WIRED", "هوش مصنوعی و فناوری", "https://www.wired.com/feed/rss"),
    ("IEEE Spectrum", "هوش مصنوعی و فناوری", "https://spectrum.ieee.org/feeds/feed.rss"),

    # 🔬 علم
    ("Nature", "علم", "https://www.nature.com/nature.rss"),
    ("APS Physics", "علم", "https://feeds.aps.org/rss/recent/physics.xml"),
    ("NASA", "علم", "https://www.nasa.gov/news-release/feed/"),
    ("New Scientist", "علم", "https://www.newscientist.com/feed/home/"),
    ("MIT News", "علم", "https://news.mit.edu/rss/feed"),
    ("ScienceDaily Science", "علم", "https://www.sciencedaily.com/rss/top/science.xml"),

    # 🇮🇷 ایران
    ("BBC Persian", "ایران", "https://feeds.bbci.co.uk/persian/rss.xml"),
    ("Radio Farda", "ایران", "https://en.radiofarda.com/api/zp_qmtl-vomx-tpe_bimr"),
    ("Tasnim", "ایران", "https://www.tasnimnews.ir/en/rss/feed/0/0/0/0/AllStories"),

    # 🌍 جهان
    ("BBC World", "جهان", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "جهان", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("DW", "جهان", "https://rss.dw.com/xml/rss-en-all"),
    ("France 24", "جهان", "https://www.france24.com/en/rss"),
    ("Euronews", "جهان", "https://www.euronews.com/rss"),
    ("The Guardian", "جهان", "https://www.theguardian.com/world/rss"),
]


# =========================================================
# HTTP SETTINGS
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PersonalNewsBot/1.0; "
        "+https://github.com/sinafirouzi16091378-debug/news-bot)"
    )
}


# =========================================================
# TEST ONE FEED
# =========================================================

def test_feed(feed):
    name, category, url = feed

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True
        )

        status = response.status_code

        if status != 200:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "message": f"HTTP {status}"
            }

        content = response.content

        if not content:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "message": "Empty response"
            }

        # Parse XML
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "message": f"Invalid XML: {e}"
            }

        # Detect RSS / Atom
        root_tag = root.tag.lower()

        if root_tag.endswith("rss") or root_tag.endswith("feed"):
            pass
        else:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "FAIL",
                "message": f"Unknown XML root: {root.tag}"
            }

        # Count articles
        items = root.findall(".//item")
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        article_count = len(items) + len(entries)

        if article_count == 0:
            return {
                "name": name,
                "category": category,
                "url": url,
                "status": "WARN",
                "message": "Valid RSS/Atom but 0 articles"
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


# =========================================================
# MAIN
# =========================================================

def main():
    print("=" * 70)
    pr
```
