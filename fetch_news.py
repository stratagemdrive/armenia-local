"""
fetch_news.py
Fetches Armenian news headlines from RSS feeds (all English-language sources),
categorizes each story, and maintains a rolling 7-day window of up to 20
stories per category.
Output: docs/armenia_news.json
No APIs, no translation libraries required.
"""

import json
import re
import calendar
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests
from dateutil import parser as dateparser

# ── Configuration ─────────────────────────────────────────────────────────────

OUTPUT_PATH = Path("docs/armenia_news.json")
MAX_STORIES_PER_CATEGORY = 20
MAX_AGE_DAYS = 7

FEEDS = [
    {
        "source": "CivilNet",
        "url": "https://www.civilnet.am/en/feed",
        "lang": "en",
    },
    {
        "source": "Hetq",
        "url": "https://hetq.am/en/rss",
        "lang": "en",
    },
    {
        "source": "Armenpress",
        "url": "https://armenpress.am/en/rss",
        "lang": "en",
    },
    {
        # RFE/RL Armenian Service — English section
        "source": "Azatutyun (RFE/RL)",
        "url": "https://www.azatutyun.am/api/zp-oqeygr",
        "lang": "en",
    },
    {
        # Fallback RFE/RL feed in case the above rotates
        "source": "Azatutyun (RFE/RL)",
        "url": "https://www.rferl.org/api/zp_yqivruzmou",
        "lang": "en",
    },
    {
        "source": "The Armenian Weekly",
        "url": "https://armenianweekly.com/feed",
        "lang": "en",
    },
    {
        "source": "Asbarez",
        "url": "https://asbarez.com/feed",
        "lang": "en",
    },
]

CATEGORIES = ["Diplomacy", "Military", "Energy", "Economy", "Local Events"]

# ── Keyword maps ──────────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "Diplomacy": [
        r"\bdiplomat\w*\b", r"\bambassador\b", r"\btreaty\b", r"\bsanction\w*\b",
        r"\bforeign (affairs|minister|policy|relations)\b",
        r"\bministry of foreign affairs\b", r"\bmirzoyan\b",
        r"\bnato\b", r"\bunited nations\b", r"\bun\b", r"\beu\b",
        r"\beuropean (union|commission|parliament|council)\b",
        r"\bembassy\b", r"\bconsulate\b", r"\bconsul\w*\b",
        r"\btrade (deal|agreement|talks|negotiation)\b",
        r"\bsummit\b", r"\bpeace (deal|talks|process|treaty|agreement)\b",
        r"\bbilateral\b", r"\bmultilateral\b", r"\bimf\b", r"\bwto\b",
        r"\bg7\b", r"\bg20\b", r"\bcsto\b", r"\bsco\b",
        r"\bpashinyan.*(visit|trip|meeting|summit|talks)\b",
        r"\barmenia.*(azerbaijan|turkey|russia|iran|usa|united states|france|eu|georgia|india|china)\b",
        r"\bpeace (process|negotiations?|framework)\b",
        r"\bnagorno.karabakh\b", r"\bartsakh\b",
        r"\bceasefire\b", r"\bdemarcation\b", r"\bborder (delimitation|talks|agreement)\b",
        r"\bnormalization\b", r"\brecognition\b", r"\bcollective security\b",
        r"\bcooperation (agreement|deal|framework|protocol)\b",
        r"\binternational (relations|law|court|community)\b",
        r"\bcouncil of europe\b", r"\bosce\b", r"\bminsk group\b",
    ],
    "Military": [
        r"\bmilitary\b", r"\bdefence\b", r"\bdefense\b", r"\bminister of defense\b",
        r"\bpapikyan\b",  # Armenia's Defense Minister
        r"\bsoldier\w*\b", r"\btroops?\b", r"\bnavy\b", r"\barmy\b", r"\bair force\b",
        r"\bweapon\w*\b", r"\barmament\w*\b", r"\barms (deal|sale|transfer|supply)\b",
        r"\bdrone\w*\b", r"\bmissile\w*\b", r"\bartillery\b",
        r"\bwar\b", r"\bconflict\b", r"\bbattle\b", r"\bcombat\b",
        r"\bterror\w*\b", r"\bnational security\b", r"\bintelligence\b",
        r"\bexplosion\b", r"\bmunition\w*\b", r"\bshelling\b", r"\bincident\b",
        r"\bpeacekeep\w*\b", r"\bdeployment\b", r"\bmilitary (exercise|drill|base|aid)\b",
        r"\bsecurity (forces|operation|threat|situation)\b",
        r"\bsniper\b", r"\bceasefire (violation|breach)\b",
        r"\bveteran\w*\b", r"\bpow\b", r"\bprisoner of war\b",
        r"\bazerbaijan.*(attack|aggression|provocation|fire|shelling)\b",
        r"\bkarabakh.*(war|conflict|occupation|offensive)\b",
        r"\bmetsamor\b",  # Nuclear Power Plant — security context
        r"\bnato.*armenia\b", r"\bfrench.*weapons?\b", r"\bindian.*weapons?\b",
        r"\bdefense (budget|spending|ministry|cooperation)\b",
    ],
    "Energy": [
        r"\benergy\b", r"\boil\b", r"\bnatural gas\b", r"\bpipeline\b",
        r"\blng\b", r"\brenewable\b", r"\bsolar\b",
        r"\bwind (power|energy|farm|turbine)\b",
        r"\bhydro\b", r"\bhydroelectric\w*\b",
        r"\bnuclear (plant|power|energy|reactor)\b", r"\bmetsamor\b",
        r"\belectricit\w*\b", r"\bpower (grid|plant|outage|cut)\b",
        r"\bblackout\b", r"\bpower (shortage|supply|generation)\b",
        r"\bcarbon\b", r"\bclimate\b", r"\bemission\w*\b", r"\bnet.zero\b",
        r"\bfuel\b", r"\bgasoline\b", r"\bgas (price|supply|shortage|field)\b",
        r"\bgreen energy\b", r"\bclean energy\b", r"\btransition\b",
        r"\benergy (security|independence|crisis|cooperation|deal)\b",
        r"\biran.*gas\b", r"\brussia.*gas\b", r"\bgeorgia.*energy\b",
        r"\belectric (vehicle|car)\b", r"\bsolar (panel|farm|plant)\b",
        r"\bgeothermal\b", r"\bbiomass\b", r"\bsmr\b",
        r"\bmining\b", r"\bmineral\w*\b", r"\bgold (mine|mining)\b",
        r"\bcopper (mine|mining)\b", r"\bzangezur copper\b",
    ],
    "Economy": [
        r"\beconom\w*\b", r"\bbudget\b", r"\bgdp\b", r"\binflation\b",
        r"\binterest rate\b", r"\bcentral bank\b", r"\brecession\b",
        r"\btrade (war|tariff|deficit|surplus|balance)\b", r"\btariff\w*\b",
        r"\bjob\w*\b", r"\bunemployment\b", r"\blabou?r\b", r"\bwage\w*\b",
        r"\bhousing (market|price|crisis)\b", r"\breal estate\b",
        r"\bexport\w*\b", r"\bimport\w*\b", r"\bcost of living\b",
        r"\bfood (price|security|inflation)\b",
        r"\btax\w*\b", r"\bfiscal\b", r"\bdeficit\b", r"\bdebt\b",
        r"\bimf\b", r"\bworld bank\b", r"\bebrd\b",
        r"\binvestment\w*\b", r"\bforeign (investment|capital)\b",
        r"\bstartup\b", r"\btech (sector|industry|company)\b",
        r"\bhigh.tech\b", r"\bit (sector|industry|company)\b",
        r"\btourism\b", r"\btourist\w*\b",
        r"\bdram\b",  # Armenian currency
        r"\bcurrency\b", r"\bexchange rate\b", r"\bremittance\w*\b",
        r"\bsanction\w*.*econom\w*\b", r"\bgrowth\b", r"\bgross domestic\b",
        r"\bstatistics\b", r"\bpoverty\b", r"\bincome\b",
        r"\bfinance (minister|ministry)\b",
        r"\bmarket\w*\b", r"\bstock (market|exchange)\b",
        r"\bbank(ing)?\b", r"\bcredit\b", r"\bloan\b",
        r"\btrade (route|corridor|hub)\b",
        r"\bcross.border (trade|commerce)\b",
    ],
    "Local Events": [
        r"\bcommunity\b", r"\btown hall\b", r"\bfestival\b", r"\bparade\b",
        r"\bfire\b", r"\bflood\b", r"\baccident\b", r"\bcrash\b",
        r"\bcrime\b", r"\barrest\b", r"\bpolice\b", r"\bcourt\b",
        r"\bjudge\b", r"\bverdict\b", r"\btrial\b", r"\bsentence\b",
        r"\bmunicip\w*\b", r"\bmayor\b", r"\bcouncil\b", r"\bcity hall\b",
        r"\bschool\b", r"\buniversity\b", r"\bcollege\b", r"\bhospital\b",
        r"\bhealth (care|system|ministry|reform)\b",
        r"\bweather\b", r"\bstorm\b", r"\bearthquake\b", r"\blandslide\b",
        r"\bwildfire\b", r"\bdrought\b", r"\bflood\w*\b",
        r"\bfundraiser\b", r"\bcharity\b", r"\bvolunteer\b",
        r"\bculture\b", r"\barts?\b", r"\bheritage\b",
        r"\bcelebration\b", r"\bholiday\b", r"\bfeast\b",
        r"\bsport\w*\b", r"\bfootball\b", r"\bbasketball\b",
        r"\binfrastructure\b", r"\broad (repair|closure|construction)\b",
        r"\btransit\b", r"\bbus\b", r"\btrain\b", r"\bmetro\b",
        r"\byerevan\b", r"\bgyumri\b", r"\bvanadzor\b",
        r"\bkapan\b", r"\bgoris\b", r"\barmavir\b", r"\bshire\b",
        r"\bregion\b", r"\bprovince\b", r"\bvillage\b",
        r"\bchurch\b", r"\bmonastery\b", r"\bapostolic\b",
        r"\bgenociide\b", r"\bgenocide\b", r"\bapril 24\b",
        r"\bdiaspora\b", r"\barmenia(n)? community\b",
        r"\belection\w*\b", r"\bvote\b", r"\bparliament\b",
        r"\bopposition\b", r"\bprotest\b", r"\bdemonstration\b",
        r"\bcorrupt\w*\b", r"\bscandal\b",
        r"\bkarekin\b", r"\bcatholicos\b",
    ],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = dateparser.parse(raw)
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None


def score_category(text: str) -> str:
    text_lower = text.lower()
    scores = {cat: 0 for cat in CATEGORIES}
    for cat, patterns in CATEGORY_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                scores[cat] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Local Events"


def fetch_feed(source: str, url: str) -> list[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; StratagemdrivBot/1.0; "
            "+https://stratagemdrive.github.io/armenia-local/)"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    stories = []
    cutoff = now_utc() - timedelta(days=MAX_AGE_DAYS)

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        print(f"[WARN] Could not fetch {url}: {exc}")
        return stories

    for entry in feed.entries:
        pub_dt = parse_date(entry)
        if pub_dt is None or pub_dt < cutoff:
            continue

        title = (entry.get("title") or "").strip()
        link  = (entry.get("link")  or "").strip()
        if not title or not link:
            continue

        summary = entry.get("summary") or entry.get("description") or ""
        category = score_category(f"{title} {summary[:400]}")

        stories.append({
            "title":          title,
            "source":         source,
            "url":            link,
            "published_date": pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "category":       category,
        })

    return stories


def load_existing() -> dict[str, list[dict]]:
    if OUTPUT_PATH.exists():
        try:
            with OUTPUT_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "stories" in data:
                by_cat: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
                for story in data["stories"]:
                    cat = story.get("category")
                    if cat in by_cat:
                        by_cat[cat].append(story)
                return by_cat
        except Exception as exc:
            print(f"[WARN] Could not parse existing JSON: {exc}")
    return {c: [] for c in CATEGORIES}


def merge_stories(
    existing: dict[str, list[dict]],
    fresh: list[dict],
) -> dict[str, list[dict]]:
    cutoff = now_utc() - timedelta(days=MAX_AGE_DAYS)

    for cat in CATEGORIES:
        existing[cat] = [
            s for s in existing[cat]
            if dateparser.parse(s["published_date"]).replace(tzinfo=timezone.utc) >= cutoff
        ]

    known_urls: dict[str, set[str]] = {
        cat: {s["url"] for s in existing[cat]} for cat in CATEGORIES
    }

    for story in fresh:
        cat = story["category"]
        if story["url"] in known_urls.get(cat, set()):
            continue
        existing[cat].append(story)
        known_urls[cat].add(story["url"])

    for cat in CATEGORIES:
        existing[cat].sort(key=lambda s: s["published_date"], reverse=True)
        existing[cat] = existing[cat][:MAX_STORIES_PER_CATEGORY]

    return existing


def write_output(by_cat: dict[str, list[dict]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_stories = [s for stories in by_cat.values() for s in stories]
    payload = {
        "generated_at":  now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "country":        "Armenia",
        "total_stories":  len(all_stories),
        "categories":     CATEGORIES,
        "stories":        all_stories,
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Wrote {len(all_stories)} stories to {OUTPUT_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[INFO] Starting Armenia news fetch at {now_utc().isoformat()}")

    seen_urls: set[str] = set()
    fresh_stories: list[dict] = []

    for feed_cfg in FEEDS:
        print(f"[INFO] Fetching {feed_cfg['source']} → {feed_cfg['url']}")
        stories = fetch_feed(feed_cfg["source"], feed_cfg["url"])
        # Deduplicate across feeds (e.g. two Azatutyun feeds)
        unique = [s for s in stories if s["url"] not in seen_urls]
        seen_urls.update(s["url"] for s in unique)
        print(f"       Found {len(unique)} unique recent stories")
        fresh_stories.extend(unique)

    print(f"[INFO] Total fresh stories collected: {len(fresh_stories)}")

    existing = load_existing()
    merged   = merge_stories(existing, fresh_stories)
    write_output(merged)


if __name__ == "__main__":
    main()
