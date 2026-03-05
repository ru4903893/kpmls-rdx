import re
from cloudscraper import create_scraper

SUPPORTED_HOSTS = [
    "drive.google.com",
    "pixeldrain.com",
    "mega.nz",
    "mediafire.com",
    "gofile.io",
    "hubcloud",
    "hubdrive",
    "drivefire",
    "sharer"
]

def extract_mirrors(url):
    try:
        scraper = create_scraper()
        r = scraper.get(url, timeout=20)

        html = r.text
        links = []

        for host in SUPPORTED_HOSTS:
            pattern = rf"https?://[^\"']*{re.escape(host)}[^\"']*"
            matches = re.findall(pattern, html)
            links.extend(matches)

        links = list(set(links))
        return links

    except Exception:
        return []
