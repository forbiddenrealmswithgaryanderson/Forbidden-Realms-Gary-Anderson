"""Forbidden Realms automated paranormal news collector.

Collects direct publisher RSS links without Google News redirects.
"""

import json
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "site" / "news.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ForbiddenRealmsNews/1.0)"
}

FEEDS = {
    "UFO & UAP": [
        "https://thedebrief.org/feed/",
        "https://www.liberationtimes.com/home?format=rss",
    ],
    "Government Secrets": [
        "https://thedebrief.org/feed/",
        "https://www.liberationtimes.com/home?format=rss",
    ],
    "Bigfoot & Cryptids": [
        "https://www.singularfortean.com/news?format=rss",
        "https://mysteriousuniverse.org/feed/",
    ],
    "Ghosts & Paranormal": [
        "https://www.singularfortean.com/news?format=rss",
        "https://mysteriousuniverse.org/feed/",
    ],
    "Space & Cosmos": [
        "https://www.nasa.gov/news-release/feed/",
        "https://www.jpl.nasa.gov/feeds/news/",
        "https://phys.org/rss-feed/space-news/",
        "https://www.space.com/feeds/all",
    ],
    "Ancient Mysteries": [
        "https://www.sciencedaily.com/rss/fossils_ruins/archaeology.xml",
        "https://phys.org/rss-feed/other-news/archaeology/",
    ],
}

KEYWORDS = {
    "UFO & UAP": [
        "ufo", "uap", "alien", "extraterrestrial",
        "unidentified", "disclosure", "flying saucer",
        "non-human", "pentagon",
    ],
    "Government Secrets": [
        "classified", "declassified", "secret",
        "government", "congress", "intelligence",
        "whistleblower", "pentagon", "cover-up",
        "disclosure", "cia", "fbi", "military",
    ],
    "Bigfoot & Cryptids": [
        "bigfoot", "sasquatch", "cryptid", "yeti",
        "loch ness", "mothman", "cryptozoology",
        "mysterious creature", "unknown creature",
    ],
    "Ghosts & Paranormal": [
        "ghost", "haunt", "paranormal", "spirit",
        "poltergeist", "apparition", "supernatural",
        "afterlife", "near-death", "haunted",
    ],
    "Space & Cosmos": [],
    "Ancient Mysteries": [
        "archaeolog", "ancient", "egypt", "pyramid",
        "maya", "aztec", "civilization", "artifact",
        "excavation", "temple", "tomb", "prehistoric",
        "stonehenge", "ruins", "fossil",
    ],
}


def valid_link(url):
    if not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()

        return (
            parsed.scheme == "https"
            and bool(host)
            and host not in (
                "news.google.com",
                "www.news.google.com",
            )
        )
    except ValueError:
        return False


def get_date(entry):
    for key in ("published", "updated"):
        value = entry.get(key)

        if value:
            try:
                date = parsedate_to_datetime(value)

                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)

                return date.astimezone(timezone.utc)
            except (ValueError, TypeError, IndexError):
                pass

    return datetime.now(timezone.utc)


def collect(url, category):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()

    parsed = feedparser.parse(response.content)

    if not parsed.entries:
        raise ValueError("No entries in RSS feed")

    articles = []
    words = KEYWORDS[category]

    for entry in parsed.entries[:40]:
        title = re.sub(
            r"\s+",
            " ",
            entry.get("title", ""),
        ).strip()

        link = entry.get("link", "").strip()

        if not title or not valid_link(link):
            continue

        if words and not any(
            word in title.lower()
            for word in words
        ):
            continue

        articles.append({
            "category": category,
            "title": title[:240],
            "source": parsed.feed.get(
                "title", "News publisher"
            )[:90],
            "url": link,
            "published": get_date(entry).isoformat(),
        })

    return articles


def main():
    collected = []

    for category, urls in FEEDS.items():
        for url in urls:
            try:
                items = collect(url, category)
                collected.extend(items)

                print(
                    category,
                    len(items),
                    url,
                    flush=True,
                )
            except Exception as error:
                print(
                    "Feed unavailable:",
                    url,
                    str(error)[:160],
                    flush=True,
                )

    # Preserve previously collected direct publisher links.
    existing = []

    if OUTPUT.exists():
        try:
            existing = json.loads(
                OUTPUT.read_text(encoding="utf-8")
            ).get("articles", [])
        except (OSError, ValueError):
            pass

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    unique = set()
    articles = []

    for item in collected + existing:
        if not isinstance(item, dict):
            continue

        link = item.get("url", "")

        if not valid_link(link):
            continue

        category = item.get("category", "")

        if category not in FEEDS:
            continue

        try:
            date = datetime.fromisoformat(
                item["published"].replace("Z", "+00:00")
            )

            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)

            if date < cutoff:
                continue
        except (KeyError, TypeError, ValueError):
            continue

        key = (
            category,
            re.sub(
                r"\W+",
                "",
                item.get("title", "").lower(),
            ),
        )

        if key in unique:
            continue

        unique.add(key)
        articles.append(item)

    articles.sort(
        key=lambda x: x["published"],
        reverse=True,
    )

    balanced = []

    for category in FEEDS:
        matching = [
            item for item in articles
            if item["category"] == category
        ]
        balanced.extend(matching[:25])

    balanced.sort(
        key=lambda x: x["published"],
        reverse=True,
    )

    if not balanced:
        raise RuntimeError(
            "No direct publisher articles found. "
            "Previous news.json preserved."
        )

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT.write_text(
        json.dumps(
            {
                "updated": datetime.now(
                    timezone.utc
                ).isoformat(),
                "articles": balanced,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "Saved",
        len(balanced),
        "articles with direct publisher links.",
        flush=True,
    )


if __name__ == "__main__":
    main()
