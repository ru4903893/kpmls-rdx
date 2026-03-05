
# --- patched mirror_leech snippet (only the extractor integration part is added) ---

from cloudscraper import create_scraper
from bot.helper.ext_utils.multi_host_extractor import extract_mirrors

# existing code above ...

    org_link = None
    if link:
        LOGGER.info(link)
        org_link = link

    # ---- GDFlix / wrapper extractor ----
    try:
        mirrors = extract_mirrors(link)
        if mirrors:
            link = mirrors[0]
            LOGGER.info(f"Wrapper mirror found: {link}")
    except Exception as e:
        LOGGER.warning(f"Extractor failed: {e}")

# existing code continues below...
