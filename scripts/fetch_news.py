#!/usr/bin/env python3
"""
Fetches BBC News, BBC Business, Al Jazeera, and ABC News Australia RSS feeds
directly (server-side, so no CORS/proxy needed), categorises stories into
Politics / Australia / Economy, finds the top 5 most-mentioned places for
the map, and writes the result to news.json in the repo root.

Designed to run inside GitHub Actions on a schedule. If a feed fails, it is
recorded honestly in "sources_failed" -- no placeholder content is invented.
"""
import json
import re
from datetime import datetime, timezone

import feedparser
import requests

FEEDS = [
    {"name": "BBC News",     "url": "https://feeds.bbci.co.uk/news/world/rss.xml",     "site": "bbc.com/news"},
    {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml",  "site": "bbc.com/news/business"},
    {"name": "Al Jazeera",   "url": "https://www.aljazeera.com/xml/rss/all.xml",        "site": "aljazeera.com"},
    {"name": "ABC News AU",  "url": "https://www.abc.net.au/news/feed/51120/rss.xml",   "site": "abc.net.au/news"},
]

POLITICAL_KW = ["election","president","minister","parliament","government","senate","congress",
                "prime minister","coup","sanction","diplomat","treaty","ballot","campaign","policy",
                "ceasefire","coalition","opposition","cabinet","impeach","summit","vote","referendum"]
ECONOMIC_KW = ["econom","inflation","interest rate","gdp","market","stocks","stock market","trade",
               "tariff","unemployment","recession","central bank","budget","deficit","currency",
               "oil price","growth","bank","imf","exports","wages","shares","earnings"]
AU_KW = ["australia","australian","canberra","sydney","melbourne","perth","brisbane","adelaide",
         "queensland","new south wales","victoria","western australia","tasmania","nsw","wa ","qld","nt ","act "]

GAZETTEER = [
    ("Washington", 38.9, -77.03), ("United States", 39.8, -98.5), ("White House", 38.9, -77.03),
    ("London", 51.5, -0.12), ("United Kingdom", 54.0, -2.0), ("Westminster", 51.5, -0.13),
    ("Moscow", 55.75, 37.6), ("Russia", 61.5, 90.0), ("Kremlin", 55.75, 37.62),
    ("Kyiv", 50.45, 30.52), ("Kiev", 50.45, 30.52), ("Ukraine", 49.0, 31.0),
    ("Beijing", 39.9, 116.4), ("China", 35.0, 105.0),
    ("Gaza", 31.5, 34.47), ("Israel", 31.5, 34.75), ("Jerusalem", 31.78, 35.22), ("Tel Aviv", 32.08, 34.78), ("Palestinian", 31.9, 35.2),
    ("Tehran", 35.7, 51.4), ("Iran", 32.0, 53.0),
    ("Beirut", 33.9, 35.5), ("Lebanon", 33.85, 35.86),
    ("Damascus", 33.5, 36.3), ("Syria", 34.8, 38.9),
    ("Brussels", 50.85, 4.35), ("European Union", 50.85, 4.35),
    ("Paris", 48.85, 2.35), ("France", 46.6, 2.2),
    ("Berlin", 52.52, 13.4), ("Germany", 51.2, 10.4),
    ("Canberra", -35.28, 149.13), ("Australia", -25.0, 133.0),
    ("Sydney", -33.87, 151.21), ("Melbourne", -37.81, 144.96), ("Perth", -31.95, 115.86),
    ("Brisbane", -27.47, 153.03), ("Adelaide", -34.93, 138.6),
    ("Wellington", -41.29, 174.78), ("New Zealand", -41.0, 174.0),
    ("Tokyo", 35.68, 139.77), ("Japan", 36.2, 138.25),
    ("Seoul", 37.57, 126.98), ("South Korea", 36.5, 127.9),
    ("Pyongyang", 39.03, 125.75), ("North Korea", 40.3, 127.5),
    ("New Delhi", 28.6, 77.2), ("India", 21.0, 78.0),
    ("Islamabad", 33.7, 73.06), ("Pakistan", 30.4, 69.3),
    ("Kabul", 34.53, 69.17), ("Afghanistan", 33.9, 67.7),
    ("Ottawa", 45.42, -75.7), ("Canada", 56.1, -106.3),
    ("Mexico City", 19.43, -99.13), ("Mexico", 23.6, -102.5),
    ("Brasilia", -15.79, -47.88), ("Brazil", -14.2, -51.9),
    ("Buenos Aires", -34.6, -58.38), ("Argentina", -38.4, -63.6),
    ("Caracas", 10.5, -66.9), ("Venezuela", 6.4, -66.6),
    ("Cairo", 30.04, 31.24), ("Egypt", 26.8, 30.8),
    ("Pretoria", -25.75, 28.19), ("South Africa", -30.6, 22.9),
    ("Lagos", 6.5, 3.4), ("Nigeria", 9.1, 8.7),
    ("Nairobi", -1.29, 36.82), ("Kenya", -0.02, 37.9),
    ("Khartoum", 15.5, 32.55), ("Sudan", 12.86, 30.22),
    ("Riyadh", 24.71, 46.68), ("Saudi Arabia", 23.9, 45.1),
    ("Ankara", 39.93, 32.86), ("Turkey", 38.96, 35.24), ("Istanbul", 41.0, 28.98),
    ("Warsaw", 52.23, 21.0), ("Poland", 51.9, 19.1),
    ("Rome", 41.9, 12.5), ("Italy", 42.5, 12.5),
    ("Madrid", 40.42, -3.7), ("Spain", 40.46, -3.7),
    ("Geneva", 46.2, 6.15), ("Switzerland", 46.8, 8.2),
    ("The Hague", 52.08, 4.31), ("Netherlands", 52.13, 5.29),
    ("Taipei", 25.03, 121.56), ("Taiwan", 23.7, 121.0),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; WorldWireBot/1.0; +https://github.com/)"}


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def fetch_one(feed):
    r = requests.get(feed["url"], headers=HEADERS, timeout=15)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"parse error: {parsed.bozo_exception}")
    items = []
    for e in parsed.entries[:25]:
        title = getattr(e, "title", "").strip()
        link = getattr(e, "link", "").strip()
        desc = strip_html(getattr(e, "summary", "") or getattr(e, "description", ""))[:220]
        if title and link:
            items.append({
                "title": title,
                "description": desc,
                "link": link,
                "source": feed["name"],
            })
    return items


def matches(text, keywords):
    return any(k in text for k in keywords)


def find_places(pool):
    counts = {}
    sample = {}
    for it in pool:
        text = (it["title"] + " " + it["description"]).lower()
        for name, lat, lon in GAZETTEER:
            key = name.lower()
            if key in text:
                counts[name] = counts.get(name, 0) + 1
                sample.setdefault(name, it)
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    coords = {name: (lat, lon) for name, lat, lon in GAZETTEER}
    return [
        {
            "name": name,
            "lat": coords[name][0],
            "lon": coords[name][1],
            "count": count,
            "story": sample[name],
        }
        for name, count in top
    ]


def main():
    pool = []
    sources_ok = []
    sources_failed = []

    for feed in FEEDS:
        try:
            items = fetch_one(feed)
            if items:
                pool.extend(items)
                sources_ok.append(feed["name"])
            else:
                sources_failed.append({"name": feed["name"], "site": feed["site"], "reason": "no items returned"})
        except Exception as e:
            sources_failed.append({"name": feed["name"], "site": feed["site"], "reason": str(e)})

    # de-dupe by title
    seen = set()
    deduped = []
    for it in pool:
        key = it["title"].strip().lower()
        if key not in seen:
            seen.add(key)
            deduped.append(it)

    australian, remainder = [], []
    for it in deduped:
        text = (it["title"] + " " + it["description"]).lower()
        if it["source"] == "ABC News AU" or matches(text, AU_KW):
            australian.append(it)
        else:
            remainder.append(it)

    political, economic = [], []
    for it in remainder:
        text = (it["title"] + " " + it["description"]).lower()
        if matches(text, POLITICAL_KW):
            political.append(it)
        if matches(text, ECONOMIC_KW):
            economic.append(it)

    places = find_places(deduped)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources_ok": sources_ok,
        "sources_failed": sources_failed,
        "political": political[:3],
        "australia": australian[:3],
        "economy": economic[:3],
        "places": places,
    }

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote news.json — ok:{sources_ok} failed:{[f['name'] for f in sources_failed]} "
          f"pol:{len(political)} au:{len(australian)} eco:{len(economic)} places:{len(places)}")


if __name__ == "__main__":
    main()
