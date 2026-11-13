"""Daglig synk: HC Wetterns kalender (svenskalag iCal) + klubbloggor (swehockey/svenskalag).

Skriver docs/data/matches.json och laddar ner saknade loggor till docs/logos/.
Körs av GitHub Actions en gång per dygn, men går också att köra lokalt:
    python scripts/sync.py
"""
from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
LOGOS = DOCS / "logos"
DATA = DOCS / "data" / "matches.json"
ALIASES = ROOT / "scripts" / "aliases.json"

ICS_URL = "https://cal.svenskalag.se/10862"
OWN_CLUB = "HC Wettern"
DISTRICTS = [
    "Ostergotland", "Smaland", "Vastergotland", "Orebro", "Sodermanland",
    "Stockholm", "Uppland", "Vastmanland", "Varmland", "Skane", "Blekinge",
    "Goteborg", "BohuslanDals", "Halland", "Dalarna", "Gastrikland", "Gotland",
]
UA = {"User-Agent": "Mozilla/5.0 (matchaffisch-sync)"}

# Lagfärger/varianter som ska strippas för att hitta klubben (t.ex. "Linköping HC Gul").
COLOR_WORDS = {
    "blå", "vit", "röd", "gul", "grön", "svart", "grå", "rosa", "lila", "brun",
    "orange", "silver", "guld", "turkos",
}


def fetch(url: str, binary: bool = False, timeout: int = 30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def norm(s: str) -> str:
    """Jämförelsenyckel: gemener, utan diakritik och skiljetecken."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s: str) -> str:
    return norm(s).replace(" ", "-") or "okand"


def strip_variant(team: str) -> tuple[str, str]:
    """'Linköping HC Gul' -> ('Linköping HC', 'Gul')."""
    words = team.split()
    variant = []
    while len(words) > 1 and words[-1].lower() in COLOR_WORDS:
        variant.insert(0, words.pop())
    return " ".join(words), " ".join(variant)


# ---------------------------------------------------------------- kalender
def parse_ics(text: str) -> list[dict]:
    text = re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))
    out = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        ev: dict[str, str] = {}
        for line in block.split("\n"):
            key, _, val = line.partition(":")
            ev.setdefault(key.split(";")[0], val)
        summary = ev.get("SUMMARY", "")
        if not summary.startswith("Match"):
            continue
        if ev.get("STATUS", "").upper() == "CANCELLED":
            continue
        m = parse_match(summary, ev)
        if m:
            out.append(m)
    out.sort(key=lambda m: m["start"])
    return out


def ics_time(v: str) -> str:
    v = v.strip()
    if "T" in v:
        return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").strftime("%Y-%m-%dT%H:%M")
    return datetime.strptime(v[:8], "%Y%m%d").strftime("%Y-%m-%d")


def unescape_ics(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_match(summary: str, ev: dict) -> dict | None:
    body = summary.split(":", 1)[1].strip()
    body, _, group = body.partition(" // ")
    series = ""
    sm = re.search(r"\(([^()]*)\)\s*$", body)
    if sm:
        series = sm.group(1).strip()
        body = body[: sm.start()].strip()
    if " - " not in body:
        return None
    home, away = (p.strip() for p in body.split(" - ", 1))
    home_is_us = norm(home).startswith(norm(OWN_CLUB))
    away_is_us = norm(away).startswith(norm(OWN_CLUB))
    if not (home_is_us or away_is_us):
        return None
    us, them = (home, away) if home_is_us else (away, home)

    # Lagnamn från " // U12 - Team 14/15 - HC Wettern"
    group = re.sub(r"\s*-\s*HC Wettern\s*$", "", group.strip())
    desc = unescape_ics(ev.get("DESCRIPTION", ""))
    team_url = re.search(r"www\.svenskalag\.se/([\w-]+)", desc)
    meet = re.search(r"Samling:\s*kl\s*([\d:.]+)", desc)
    uid = re.search(r"cal(\d+)", ev.get("UID", ""))

    return {
        "id": uid.group(1) if uid else ev.get("UID", ""),
        "start": ics_time(ev.get("DTSTART", "")),
        "end": ics_time(ev.get("DTEND", "")) if ev.get("DTEND") else None,
        "meet": meet.group(1).replace(".", ":") if meet else None,
        "location": unescape_ics(ev.get("LOCATION", "")).strip(),
        "series": series,
        "team": group or "HC Wettern",
        "teamSlug": team_url.group(1) if team_url else None,
        "home": home,
        "away": away,
        "homeGame": home_is_us,
        "us": us,
        "opponent": them,
    }


# ---------------------------------------------------------------- loggor
def swehockey_clubs() -> dict[str, str]:
    """norm(klubbnamn) -> logo-URL från stats.swehockey.se distriktssidor."""
    clubs: dict[str, str] = {}
    pat = re.compile(
        r"pageVisited\('[^']*','([^']*)'\)\">\s*<figure[^>]*>\s*<img[^>]*src=\"([^\"]+)\""
    )
    for d in DISTRICTS:
        try:
            page = fetch(f"https://stats.swehockey.se/District/{d}")
        except Exception as e:  # ett distrikt som strular ska inte stoppa synken
            print(f"  ! swehockey {d}: {e}", file=sys.stderr)
            continue
        for name, img in pat.findall(page):
            if "blob" in img:
                clubs.setdefault(norm(html.unescape(name)), img)
    return clubs


def resolve_logo(club: str, aliases: dict, sweh: dict[str, str]) -> str | None:
    """Returnerar en logo-URL för klubben, eller None."""
    if club in aliases:
        a = aliases[club]
        if a is None:
            return None
        if a.startswith("http"):
            return a
        club = a  # alias till annat klubbnamn
    key = norm(club)
    if key in sweh:
        return sweh[key]
    # "Vimmerby HC" -> "vimmerby", "Tranås AIF" -> "tranas", "HC Dalen" -> "dalen"
    generic = {"hc", "if", "ik", "sk", "hk", "aif", "gif", "goif", "hf", "bk", "ff", "is", "sgf"}
    core = " ".join(w for w in key.split() if w not in generic)
    for k, url in sweh.items():
        kcore = " ".join(w for w in k.split() if w not in generic)
        if core and core == kcore:
            return url
    # "Valdemarsviks IF/IK Guts" -> första klubben
    if "/" in club:
        first = club.split("/")[0].strip()
        if first != club:
            return resolve_logo(first, aliases, sweh)
    return None


def shrink(path: Path, size: int = 512) -> None:
    """Skala ner stora loggor (kräver Pillow, annars lämnas filen orörd)."""
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as im:
        im = im.convert("RGBA")
        if max(im.size) > size:
            im.thumbnail((size, size), Image.LANCZOS)
        im.save(path, "PNG", optimize=True)


def download_logo(url: str, name: str) -> str | None:
    target = LOGOS / f"{slug(name)}.png"
    if target.exists():
        return target.name
    try:
        data = fetch(url, binary=True)
    except Exception as e:
        print(f"  ! logga {name}: {e}", file=sys.stderr)
        return None
    if not data.startswith(b"\x89PNG") and not data[:3] == b"\xff\xd8\xff":
        print(f"  ! logga {name}: inte en bild", file=sys.stderr)
        return None
    target.write_bytes(data)
    shrink(target)
    print(f"  + logga {name}")
    return target.name


def main() -> int:
    LOGOS.mkdir(parents=True, exist_ok=True)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    aliases = json.loads(ALIASES.read_text(encoding="utf-8")) if ALIASES.exists() else {}
    aliases.pop("_info", None)

    print("Hämtar kalender…")
    matches = parse_ics(fetch(ICS_URL))
    print(f"  {len(matches)} matcher")

    print("Hämtar klubbar från swehockey…")
    sweh = swehockey_clubs()
    print(f"  {len(sweh)} klubbar")

    clubs: dict[str, dict] = {}
    missing = []
    for name in sorted({strip_variant(m["opponent"])[0] for m in matches} | {OWN_CLUB}):
        url = resolve_logo(name, aliases, sweh)
        file = download_logo(url, name) if url else None
        if not file and (LOGOS / f"{slug(name)}.png").exists():
            file = f"{slug(name)}.png"
        if not file:
            missing.append(name)
        clubs[name] = {"logo": f"logos/{file}" if file else None}

    for m in matches:
        club, variant = strip_variant(m["opponent"])
        m["opponentClub"] = club
        m["opponentVariant"] = variant
        m["usVariant"] = strip_variant(m["us"])[1]

    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": ICS_URL,
        "ownClub": OWN_CLUB,
        "ownLogo": clubs[OWN_CLUB]["logo"],
        "clubs": clubs,
        "matches": matches,
    }
    # Skriv bara om innehållet (utom tidsstämpeln) ändrats, så att git inte får tomma commits.
    if DATA.exists():
        old = json.loads(DATA.read_text(encoding="utf-8"))
        if {k: v for k, v in old.items() if k != "updated"} == {
            k: v for k, v in payload.items() if k != "updated"
        }:
            print("Inga ändringar.")
            return 0
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Skrev {DATA.relative_to(ROOT)}")
    if missing:
        print("Saknar logga (lägg till i scripts/aliases.json):", ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
