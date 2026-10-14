"""Automatic paranormal news collection for Forbidden Realms."""

import json
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import feedparser
import requests

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
    """Try to resolve an RSS article link to its publisher."""
    if not link.startswith("https://"):
        return ""

    try:
        response = requests.get(
            link,
            headers=HEADERS,
            timeout=10,
            allow_redirects=True,
            stream=True,
        )

        final_url = response.url
        response.close()

        parsed = urlparse(final_url)

        if parsed.scheme != "https":
            return link

        if parsed.hostname not in (
            "news.google.com",
            "www.news.google.com",
        ):
            return final_url

    except requests.RequestException:
        pass

    return link


def fetch(query, category):
    url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )

    response = requests.get(
        url,
        timeout=22,
        headers=HEADERS,
    )
    response.raise_for_status()

    parsed = feedparser.parse(response.content)

    if parsed.bozo and not parsed.entries:
        raise ValueError("Invalid RSS response")

    result = []

    for item in parsed.entries[:25]:
        link = item.get("link", "")

        if urlparse(link).scheme != "https":
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
            date = parsedate_to_datetime(
                item.get("published", "")
            ).astimezone(timezone.utc)
        except (ValueError, TypeError, IndexError):
            date = datetime.now(timezone.utc)

        direct_link = resolve_article_url(link)

        result.append({
            "category": category,
            "title": title[:240],
            "source": source[:90],
            "url": direct_link,
            "published": date.isoformat(),
        })

    return result


def main():
    all_items = []
    failures = []

    for category, queries in CATEGORIES.items():
        for query in queries:
            try:
                got = fetch(query, category)
                all_items.extend(got)
                print(category, len(got))
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
            when = datetime.fromisoformat(
                item["published"].replace("Z", "+00:00")
            )
            if when < cutoff:
                continue
        except (KeyError, ValueError, TypeError):
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

        if not item.get("url", "").startswith("https://"):
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
            x for x in articles
            if x["category"] == category
        ][:25])

    balanced.sort(
        key=lambda x: x["published"],
        reverse=True,
    )

    if not balanced and failures:
        raise RuntimeError(
            "All feeds failed and no cached stories exist"
        )

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUT.write_text(
        json.dumps({
            "updated": datetime.now(
                timezone.utc
            ).isoformat(),
            "articles": balanced,
        }, ensure_ascii=False, indent=2),
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
