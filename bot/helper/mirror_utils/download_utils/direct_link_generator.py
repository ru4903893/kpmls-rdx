#!/usr/bin/env python3
from requests import Session
from urllib.parse import urlparse
from os import path
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException

# Minimal clean version focused on GoFile fix for mirror/leech bots

def direct_link_generator(link):
    domain = urlparse(link).hostname
    if not domain:
        raise DirectDownloadLinkException("ERROR: Invalid URL")

    if "gofile.io" in domain:
        return gofile(link, None)

    raise DirectDownloadLinkException(f"No Direct link function found for {link}")


def gofile(url, auth):
    try:
        _id = url.split("/")[-1]

        api = f"https://api.gofile.io/contents/{_id}?cache=true"

        session = Session()
        res = session.get(api).json()

        if res.get("status") != "ok":
            raise DirectDownloadLinkException("ERROR: Failed to fetch GoFile data")

        data = res["data"]["children"]

        details = {
            "contents": [],
            "title": res["data"].get("name", "gofile"),
            "total_size": 0,
            "header": "Referer: https://gofile.io/"
        }

        for content in data.values():
            if content.get("type") == "file":

                item = {
                    "path": details["title"],
                    "filename": content.get("name"),
                    "url": content.get("link")
                }

                if "size" in content:
                    try:
                        details["total_size"] += int(content["size"])
                    except:
                        pass

                details["contents"].append(item)

        if len(details["contents"]) == 1:
            return (details["contents"][0]["url"], details["header"])

        return details

    except Exception as e:
        raise DirectDownloadLinkException(f"Gofile ERROR: {e}")
