"""Free automatic paranormal news collection for Forbidden Realms."""

import json
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import feedparser
import requests
from googlenewsdecoder import gnewsdecoder

BASE = Path(__file__).parent
OUT = BASE / "site" / "news.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ForbiddenRealmsNews/1.0)"
}

CATEGORIES = {
    "UFO & UAP": [
        '"UAP" OR "UFO" OR "alien disclosure" when:7d',
        '"Area 51" OR "UFO hearing" when:30d',
    ],
    "Government Secrets": [
        '"declassified documents" OR "UAP congressional hearing" when:30d',
        '"government secrecy" OR "classified files" when:7d',
    ],
    "Bigfoot & Cryptids": [
        '"Bigfoot" OR "Sasquatch" OR "cryptid" when:30d',
    ],
    "Ghosts & Paranormal": [
        '"ghost sighting" OR "haunting" OR "paranormal investigation" when:30d',
    ],
    "Space & Cosmos": [
        '"NASA discovery" OR "James Webb Space Telescope" when:7d',
        '"black hole" OR "exoplanet discovery" when:7d',
    ],
    "Ancient Mysteries": [
        '"Egyptian pyramids" OR "Maya archaeology" when:30d',
        '"Aztec discovery" OR "ancient civilization archaeology" when:30d',
    ],
}


def resolve_article_url(link):
    """Decode Google News RSS links to original publisher URLs."""

    if not link.startswith("https://"):
        return ""

    hostname = (urlparse(link).hostname or "").lower()

    if hostname not in ("news.google.com", "www.news.google.com"):
        return link

    try:
        result = gnewsdecoder(link, interval=0.1)

        if result.get("status"):
            decoded = result.get("decoded_url", "")
            parsed = urlparse(decoded)

            if (
                parsed.scheme == "https"
                and parsed.hostname
                and parsed.hostname not in (
                    "news.google.com",
                    "www.news.google.com",
                )
            ):
                return decoded

    except Exception as exc:
        print("Could not decode article:", str(exc)[:150])

    # Skip unresolved Google News links to avoid broken articles.
    return ""


def fetch(query, category):
    rss_url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )

    response = requests.get(
        rss_url,
        timeout=22,
        headers=HEADERS,
    )
    response.raise_for_status()

    parsed = feedparser.parse(response.content)

    if parsed.bozo and not parsed.entries:
        raise ValueError("Invalid RSS response")

    articles = []

    for item in parsed.entries[:25]:
        original_link = item.get("link", "")

        if urlparse(original_link).scheme != "https":
            continue

        title = re.sub(
            r"\s+",
            " ",
            item.get("title", ""),
        ).strip()

        if not title:
            continue

        source = (
            item.get("source", {}).get("title", "")
            if item.get("source")
            else ""
        )

        if not source and " - " in title:
            title, source = title.rsplit(" - ", 1)

        try:
            published = parsedate_to_datetime(
                item.get("published", "")
            ).astimezone(timezone.utc)
        except (ValueError, TypeError, IndexError):
            published = datetime.now(timezone.utc)

        publisher_url = resolve_article_url(original_link)

        if not publisher_url:
            continue

        articles.append({
            "category": category,
            "title": title[:240],
            "source": source[:90],
            "url": publisher_url,
            "published": published.isoformat(),
        })

    return articles


def main():
    all_items = []
    failures = []

    for category, queries in CATEGORIES.items():
        for query in queries:
            try:
                collected = fetch(query, category)
                all_items.extend(collected)
                print(category, len(collected))
            except Exception as exc:
                failures.append(f"{category}: {exc}")
                print("ERROR", failures[-1])

    existing = []

    if OUT.exists():
        try:
            existing = json.loads(
                OUT.read_text(encoding="utf-8")
            ).get("articles", [])
        except (ValueError, OSError):
            pass

    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    seen = set()
    articles = []

    for item in all_items + existing:
        try:
            published = datetime.fromisoformat(
                item["published"].replace("Z", "+00:00")
            )

            if published < cutoff:
                continue

        except (KeyError, ValueError, TypeError):
            continue

        link = item.get("url", "")

        # Exclude old Google News links from the saved feed.
        if not link.startswith("https://"):
            continue

        hostname = (urlparse(link).hostname or "").lower()

        if hostname in ("news.google.com", "www.news.google.com"):
            continue

        key = (
            item.get("category", ""),
            re.sub(
                r"\W+",
                "",
                item.get("title", "").lower(),
            ),
        )

        if key in seen:
            continue

        seen.add(key)
        articles.append(item)

    articles.sort(
        key=lambda x: x["published"],
        reverse=True,
    )

    balanced = []

    for category in CATEGORIES:
        balanced.extend([
            item for item in articles
            if item.get("category") == category
        ][:25])

    balanced.sort(
        key=lambda x: x["published"],
        reverse=True,
    )

    if not balanced:
        raise RuntimeError(
            "No publisher links could be collected. "
            "Keeping the previous news.json unchanged."
        )

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUT.write_text(
        json.dumps(
            {
                "updated": datetime.now(
                    timezone.utc
                ).isoformat(),
                "articles": balanced,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "Saved",
        len(balanced),
        "articles; feed errors:",
        len(failures),
    )


if __name__ == "__main__":
    main()
