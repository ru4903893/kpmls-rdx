import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0"}

HOST_PRIORITY = [
    "drive.google.com",
    "pixeldrain.com",
    "mega.nz",
    "mediafire.com",
    "gofile.io",
    "dropbox.com",
    "1fichier.com"
]

def extract_best_mirror(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        links = []

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if href.startswith("http"):
                links.append(href)

        # remove duplicates
        links = list(set(links))

        # priority select
        for host in HOST_PRIORITY:
            for link in links:
                if host in link:
                    return link

        return None

    except:
        return None
