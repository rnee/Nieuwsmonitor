"""
Nieuwsmonitor: haalt nieuws op via Google News RSS en stuurt een push via ntfy.
Draait elke 15 minuten via GitHub Actions.
"""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests

# ---------- Instellingen ----------
# Naam -> zoekopdracht (Google News ondersteunt OR en aanhalingstekens)
BEDRIJVEN = {
    "ASML": '"ASML"',
    "BESI": '"BE Semiconductor" OR "Besi"',
    "ASMI": '"ASM International"',
}

# Zet op True om alleen artikelen te melden met een van deze trefwoorden in de titel
FILTER_AAN = False
TREFWOORDEN = [
    "overname", "order", "orders", "guidance", "winst", "omzet", "resultaten",
    "export", "exportbeperking", "dividend", "inkoop", "ceo", "waarschuwing",
    "acquisition", "earnings", "revenue", "forecast", "export controls",
]

MAX_BERICHTEN_PER_RUN = 10   # voorkomt een stortvloed aan pushberichten
BEWAAR_AANTAL = 2000         # hoeveel 'gezien'-ID's we onthouden
SEEN_BESTAND = Path("seen.json")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
# ----------------------------------


def feed_url(zoekterm: str) -> str:
    # when:1d = alleen laatste 24 uur; Nederlandse editie
    q = quote(f"{zoekterm} when:1d")
    return f"https://news.google.com/rss/search?q={q}&hl=nl&gl=NL&ceid=NL:nl"


def laad_seen() -> tuple[set[str], bool]:
    if SEEN_BESTAND.exists():
        try:
            return set(json.loads(SEEN_BESTAND.read_text())), False
        except json.JSONDecodeError:
            pass
    return set(), True  # eerste run


def bewaar_seen(seen: set[str]) -> None:
    # Bewaar alleen de meest recente ID's (set is ongeordend, dus we slaan als lijst op)
    lijst = list(seen)[-BEWAAR_AANTAL:]
    SEEN_BESTAND.write_text(json.dumps(lijst, ensure_ascii=False, indent=0))


def stuur_push(titel: str, bericht: str, link: str) -> None:
    resp = requests.post(
        NTFY_SERVER,
        json={
            "topic": NTFY_TOPIC,
            "title": titel,
            "message": bericht,
            "click": link,
            "tags": ["newspaper"],
        },
        timeout=15,
    )
    resp.raise_for_status()


def main() -> int:
    if not NTFY_TOPIC:
        print("NTFY_TOPIC ontbreekt (stel in als GitHub secret).", file=sys.stderr)
        return 1

    seen, eerste_run = laad_seen()
    nieuw = []

    for naam, zoekterm in BEDRIJVEN.items():
        feed = feedparser.parse(feed_url(zoekterm))
        for entry in feed.entries:
            uid = entry.get("id") or entry.get("link")
            titel = entry.get("title", "").strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            if FILTER_AAN and not any(t in titel.lower() for t in TREFWOORDEN):
                continue
            nieuw.append((naam, titel, entry.get("link", "")))

    if eerste_run:
        # Eerste keer: alleen de huidige stand vastleggen, niets sturen
        print(f"Eerste run: {len(seen)} artikelen vastgelegd, geen berichten verstuurd.")
        bewaar_seen(seen)
        return 0

    for naam, titel, link in nieuw[:MAX_BERICHTEN_PER_RUN]:
        try:
            stuur_push(f"{naam} nieuws", titel, link)
            time.sleep(0.5)
        except requests.RequestException as e:
            print(f"Push mislukt: {e}", file=sys.stderr)

    if len(nieuw) > MAX_BERICHTEN_PER_RUN:
        extra = len(nieuw) - MAX_BERICHTEN_PER_RUN
        try:
            stuur_push("Nieuwsmonitor", f"Plus nog {extra} andere artikelen.", "")
        except requests.RequestException:
            pass

    bewaar_seen(seen)
    print(f"{len(nieuw)} nieuwe artikelen, {min(len(nieuw), MAX_BERICHTEN_PER_RUN)} gemeld.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
