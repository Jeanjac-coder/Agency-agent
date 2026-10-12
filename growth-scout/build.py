#!/usr/bin/env python3
"""Build the Vybe Growth Scout board.

Reads every lane file in data/raw/*.json, applies the gates and priority rules
in params.toml, de-duplicates, and writes:

  data/targets.json   the ranked, validated target list (the record)
  site/data.json      the same data for the dashboard
  site/index.html     the self-contained dashboard (no external requests)

Python 3.11+ standard library only.

  python3 growth-scout/build.py            # build
  python3 growth-scout/build.py --check    # validate only, exit 1 on problems
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
SITE = ROOT / "site"
LINK_CHECK = ROOT / "data" / "link_check.json"
COMBOS = ROOT / "data" / "combos.json"
SCREENED = ROOT / "data" / "screened_apps.json"
IDENTIFIED = ROOT / "data" / "identified_apps.json"
FOLLOWUPS = ROOT / "data" / "followups.json"
APPROVALS = ROOT / "data" / "approvals.json"
JOHN = ROOT / "data" / "john_verdicts.json"

TYPES = {
    "vc", "angel", "angel-group", "syndicate", "accelerator", "corporate-vc",
    "builder", "research-lab", "amplifier", "community", "event", "listing", "signal",
    "competitor-deal", "athlete", "team", "program", "app-partner", "sport",
    "oem-partner", "channel-partner",
}
HUNTS = {"investor", "growth", "social", "sponsorship", "partnership"}
PARTNER_STATUSES = {"open", "competitor", "exclusive", "no-wearable-yet", "unknown"}


def load_params() -> dict:
    with open(ROOT / "params.toml", "rb") as fh:
        return tomllib.load(fh)


def parse_date(value) -> dt.date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def validate(row: dict, params: dict, today: dt.date) -> list[str]:
    """Return the reasons a row fails the gates (empty list = keep)."""
    gates = params["gates"]
    problems = []
    if not row.get("name"):
        problems.append("no name")
    if row.get("type") not in TYPES:
        problems.append(f"unknown type {row.get('type')!r}")
    if row.get("hunt") not in HUNTS:
        problems.append(f"unknown hunt {row.get('hunt')!r}")
    # Partnerships must show what the app already works with, not assume it.
    if row.get("type") == "app-partner":
        if "existing_wearables" not in row:
            problems.append("app-partner without existing_wearables (null if unknown)")
        if row.get("partner_status") not in PARTNER_STATUSES:
            problems.append(f"app-partner partner_status {row.get('partner_status')!r}")
        elif row["partner_status"] in {"competitor", "exclusive"} and (row.get("fit") or 0) > 6:
            problems.append(f"{row['partner_status']} app scored above 6")
        if not row.get("opportunity"):
            problems.append("app-partner without a stated opportunity")
    if row.get("type") in {"oem-partner", "channel-partner"} and not (row.get("opportunity") and row.get("unknowns")):
        problems.append(f"{row['type']} without opportunity and unknowns")
    if row.get("type") == "sport" and not (row.get("wearable_adoption") and row.get("opportunity")):
        problems.append("sport without wearable_adoption evidence or opportunity")
    evidence = [u for u in row.get("evidence") or [] if isinstance(u, str) and u.startswith("http")]
    if len(evidence) < gates["min_evidence_urls"]:
        problems.append("no evidence URL")
    fit = row.get("fit")
    if not isinstance(fit, (int, float)) or fit < gates["min_fit"]:
        problems.append(f"fit {fit} below {gates['min_fit']}")
    contact = row.get("contact_url") or ""
    if contact and not contact.startswith("http"):
        problems.append("contact_url is not a URL (never a guessed email)")
    name_blob = norm(f"{row.get('name')} {row.get('org')}")
    for bad in gates["exclude_names"]:
        if norm(bad) and norm(bad) in name_blob:
            problems.append(f"excluded name {bad}")
    # Only the target's own name decides the lane: a VC whose deal note
    # mentions SBIR is still a VC, but "Acme SBIR Program" is a grant.
    name_text = f"{row.get('name')}".lower()
    for kw in gates["exclude_keywords"]:
        if kw.lower() in name_text and row.get("type") not in {"signal"}:
            problems.append(f"out of lane ({kw}: funding sweep owns it)")
    deadline = parse_date(row.get("deadline"))
    if deadline and deadline < today:
        problems.append(f"deadline {deadline} passed")
    if row.get("type") in {"vc", "corporate-vc", "angel", "syndicate"}:
        last = parse_date(row.get("last_signal_date"))
        if last and (today - last).days > gates["max_signal_age_days"]:
            problems.append(f"last signal {last} too old")
    return problems


IDENTITY_RE = re.compile(
    r"\bveteran[- ](?:owned|founder|led)|\bveteran-,|\b(?:woman|women)[- ](?:owned|led|founder)|\bwoman-,|\bminority[- ]owned",
    re.I,
)


def is_sendable(row: dict) -> bool:
    """A drafted opener the founder can send today through a public channel."""
    return bool(
        row["type"] not in {"signal", "competitor-deal"}
        and row.get("contact_url")
        and row.get("opener")
        and "warm intro" not in (row.get("channel") or "").lower()
        and not row.get("identity_needs_ok")
    )


def uses_founder_identity(row: dict) -> bool:
    """True when the drafted opener tells the founder-identity story."""
    return bool(IDENTITY_RE.search(row.get("opener") or ""))


OHIO_RE = re.compile(
    r"\b(OH|Ohio|Akron|Cleveland|Columbus|Cincinnati|Dayton|Toledo|Canton|Kent|Youngstown|"
    r"Hudson|Fairborn|Middlefield|Sidney|Newark|Chagrin|Bowling Green|Mansfield|Lorain|Medina|Stow)\b")


NC_RE = re.compile(
    r"\b(NC|N\.C\.|North Carolina|Charlotte|Raleigh|Durham|Chapel Hill|Greensboro|Winston-Salem|"
    r"Fayetteville|Fort Bragg|Fort Liberty|Camp Lejeune|Jacksonville, NC|Wilmington|Asheville|Cary|"
    r"High Point|Research Triangle|RTP|Boone|Greenville, NC)\b")
EAST_RE = re.compile(
    r"\b(ME|NH|VT|MA|RI|CT|NY|NJ|PA|DE|MD|DC|VA|SC|GA|FL|Maine|New Hampshire|Vermont|Massachusetts|"
    r"Rhode Island|Connecticut|New York|New Jersey|Pennsylvania|Delaware|Maryland|Washington, DC|"
    r"Virginia|South Carolina|Georgia|Florida|Boston|NYC|Brooklyn|Philadelphia|Pittsburgh|Baltimore|"
    r"Richmond|Norfolk|Virginia Beach|Arlington|Charleston|Columbia, SC|Atlanta|Savannah|Miami|"
    r"Orlando|Tampa|Jacksonville|Hartford|Providence|Newark, NJ)\b")


def _where(row: dict) -> str:
    return " ".join(str(row.get(k) or "") for k in ("geo", "name", "org", "warm_path"))


def is_ohio(row: dict) -> bool:
    return bool(OHIO_RE.search(_where(row)))


STATE_RE = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|"
    r"NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b")
EAST_STATES = {"NC", "VA", "SC", "GA", "FL", "MD", "DC", "DE", "PA", "NJ", "NY", "CT", "RI", "MA", "VT", "NH", "ME", "WV"}


def state_of(row: dict) -> str:
    geo = str(row.get("geo") or "")
    found = STATE_RE.findall(geo)
    if found:
        return found[-1]
    if "North Carolina" in geo:
        return "NC"
    if "Ohio" in geo:
        return "OH"
    return "National"


def by_state(targets: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for t in targets:
        st = state_of(t)
        counts[st] = counts.get(st, 0) + 1
    return [{"state": k, "count": v, "east": k in EAST_STATES}
            for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def region(row: dict) -> str:
    """nc, east, ohio or other. Geo decides first; names only break ties."""
    geo = str(row.get("geo") or "")
    for text in (geo, _where(row)):
        if NC_RE.search(text):
            return "nc"
        if EAST_RE.search(text):
            return "east"
        if OHIO_RE.search(text):
            return "ohio"
    return "other"


# Founder, 11 Oct: "we are not spending money, we have no money". Vybe is
# pre-launch with a 5-10 unit DevKit and no stock of bands. Anything that asks
# for cash, a table, a booth, a vendor slot, a sponsorship tier or prizes is
# parked off the board. Rows that need DevKit units are kept but marked for
# after DevKit v0.1, so the "doable now" list is calls, integrations,
# applications, guest spots and listings that cost nothing.
COST_RE = re.compile(
    r"\b(tables?|booths?|vendors?|expos?|exhibit\w*|sponsor\w*|tiers?|packages?|fees?|paid|pay|"
    r"giveaways?|swag|prizes?|presenting|activations?|tents?|donat\w*|registration)\b|\$\s?\d", re.I)
UNITS_RE = re.compile(
    r"\b(seed|loan|lend|send|ship|give|offer|provide)\b[^.]{0,40}\b(bands?|units?|devkits?|devices?|samples?)\b"
    r"|\breview[- ]unit|\bdevkit (units?|bands?)\b|\bwear[- ]test", re.I)
VALUE_BY_TYPE = {"app-partner": 15, "builder": 15, "research-lab": 10, "channel-partner": 5,
                 "amplifier": 5, "listing": 5, "accelerator": 0, "community": 0, "oem-partner": 0,
                 "sport": -5, "team": -10, "event": -10, "program": -10, "athlete": -15}


REVIEW = ROOT / "data" / "review.json"


def load_review() -> dict:
    """Hand review of every growth/partner row (11 Oct): {id: {verdict A|B|cut, reason, move}}."""
    return json.loads(REVIEW.read_text()).get("rows", {}) if REVIEW.exists() else {}


SUPPLIER_RE = re.compile(
    r"\b(contract (?:electronics )?manufactur\w*|electronics manufactur\w*|EMS provider|PCBA?\b|PCB assembly|"
    r"box build|battery (?:maker|manufacturer|supplier)|sensor vendor|component supplier|"
    r"product[- ]development firm|engineering firm|design firm|injection mold\w*|silicone mold\w*|"
    r"certification lab|compliance (?:test )?lab|manufacturing (?:association|network|extension))\b", re.I)
SUPPLIER_NAMES = ("anzer", "zufek", "nocturnal", "lipol", "sugamed", "suga", "kyros", "magnet", "platelens", "joules")


def is_supplier(row: dict) -> bool:
    """Rule 7 (founder, 11 Oct): suppliers sell TO Vybe; procurement belongs to the founders, not outreach."""
    name = f"{row.get('name') or ''} {row.get('org') or ''}".lower()
    if row.get("type") == "oem-partner" or any(n in name for n in SUPPLIER_NAMES):
        return True
    text = " ".join(str(row.get(k) or "") for k in ("name", "org", "why", "ask"))
    return bool(SUPPLIER_RE.search(text)) and row.get("hunt") != "investor"


def costs_money(row: dict) -> bool:
    if row.get("hunt") == "investor":
        return False  # a check size is money coming in, not going out
    if row.get("hunt") == "sponsorship" or row.get("type") in ("competitor-deal", "athlete"):
        return True
    text = " ".join(str(row.get(k) or "") for k in ("name", "ask", "opener", "why", "why_now"))
    return bool(COST_RE.search(text))


def needs_units(row: dict) -> bool:
    return bool(UNITS_RE.search(" ".join(str(row.get(k) or "") for k in ("ask", "opener"))))


def score(row: dict, params: dict, today: dt.date) -> tuple[int, str]:
    p = params["priority"]
    s = int(row["fit"]) * 10
    deadline = parse_date(row.get("deadline"))
    if deadline and 0 <= (deadline - today).days <= p["deadline_window_days"]:
        s += p["deadline_bonus"]
    last = parse_date(row.get("last_signal_date"))
    if last and 0 <= (today - last).days <= p["recent_signal_days"]:
        s += p["recent_signal_bonus"]
    if row.get("confidence") == "verified":
        s += p["verified_bonus"]
    if row.get("contact_url"):
        s += p["open_channel_bonus"]
    s += {"nc": p.get("nc_bonus", 0), "east": p.get("east_coast_bonus", 0),
          "ohio": p.get("ohio_bonus", 0)}.get(region(row), 0)
    ice = row.get("ice") or {}
    if row.get("hunt") == "growth" and all(isinstance(ice.get(k), (int, float)) for k in "ice"):
        # Easy, high-confidence wins move up; hard ones move down.
        s += round((ice["i"] + ice["c"] + ice["e"]) / 3) - 7
    s += VALUE_BY_TYPE.get(row.get("type"), 0)
    if row.get("hunt") != "investor" and not needs_units(row):
        s += 10  # doable now, no hardware needed
    s = max(0, s)
    label = "High" if s >= p["high"] else "Medium" if s >= p["medium"] else "Low"
    return s, label


def load_link_check() -> dict:
    """{url: {"status": "ok" | "dead" | "unverified", "note": str}} from the last link check."""
    if not LINK_CHECK.exists():
        return {}
    data = json.loads(LINK_CHECK.read_text())
    return data.get("urls", {})


def apply_link_check(row: dict, checks: dict) -> str | None:
    """Drop dead links from a row. Returns a rejection reason when nothing citable is left."""
    status = lambda u: (checks.get(u) or {}).get("status")  # noqa: E731
    dead = [u for u in row["evidence"] if status(u) == "dead"]
    row["evidence"] = [u for u in row["evidence"] if status(u) != "dead"]
    if not row["evidence"]:
        return f"every evidence link is dead ({len(dead)} checked)"
    contact = row.get("contact_url")
    if contact and status(contact) == "dead":
        row["contact_url"] = None
        row["contact_note"] = f"contact link dead: {(checks[contact].get('note') or '').strip()}"
    checked = [u for u in row["evidence"] + ([row["contact_url"]] if row.get("contact_url") else []) if u in checks]
    if row.get("contact_note"):
        row["link_status"] = "contact dead"
    elif checked and all(status(u) == "ok" for u in checked):
        row["link_status"] = "verified"
    elif checked:
        row["link_status"] = "partly verified"
    else:
        row["link_status"] = "not checked"
    return None


def load_partner_extras() -> tuple[dict, list[dict]]:
    """Combos, and the apps that were checked and not kept (the 9 re-checked apps use their newer verdicts)."""
    combos = json.loads(COMBOS.read_text()) if COMBOS.exists() else {"note": "", "combos": []}
    screened = {}
    if SCREENED.exists():
        for r in json.loads(SCREENED.read_text()).get("screened_out", []):
            screened[r["app"]] = {"app": r["app"], "reason": r.get("reason", ""), "recheck": False}
    if IDENTIFIED.exists():
        for r in json.loads(IDENTIFIED.read_text()):
            who = r.get("company") if r.get("identified") else None
            reason = r.get("reason", "")
            screened[r["app"]] = {
                "app": r["app"],
                "reason": (f"Re-checked: identified as {who}. " if who else "Re-checked: could not be tied to a real app. ") + reason,
                "recheck": True,
            }
    return combos, sorted(screened.values(), key=lambda r: r["app"].lower())


def dedupe_key(row: dict) -> str:
    if row.get("type") in {"signal", "competitor-deal"}:
        return row["type"] + ":" + norm(row.get("name"))
    return norm(row.get("name")) + "|" + norm(row.get("org"))


HOME_FIXES = [
    (r"a few (?:miles|minutes) away in Akron", "in Raleigh, North Carolina"),
    (r"here in Akron", "in Raleigh"),
    (r"Akron, Ohio", "Raleigh, North Carolina"),
    (r"Akron, OH", "Raleigh, NC"),
    (r"\bAkron-based\b", "Raleigh-based"),
    (r"\ban Akron company\b", "a Raleigh company"),
    (r"\bAkron company\b", "Raleigh company"),
    (r"\ban Ohio startup\b", "a North Carolina startup"),
    (r"\bOhio startup\b", "North Carolina startup"),
    (r"\bin Akron\b", "in Raleigh"),
    (r"\b(?:from|out of) Akron\b", lambda m: m.group(0).replace("Akron", "Raleigh")),
    (r"\bAkron-made\b", "Raleigh-made"),
    (r"\bAkron-built\b", "Raleigh-built"),
    (r"\(Akron\)", "(Raleigh, NC)"),
    (r"fellow Akron builders here", "we're a Raleigh team"),
    (r"a few miles from your Akron store", "in Raleigh"),
    (r"you ran right past our Akron office on the towpath\. ", ""),
    (r"\ban Akron (?=(?:[\w/-]+ )?(?:team|startup|company|founder))", "a Raleigh "),
    (r"\bAkron (?=(?:[\w/-]+ )?(?:team|startup|company|founder))", "Raleigh "),
]


def home_fix(text: str | None) -> str | None:
    """Home base is Raleigh, NC (founder, 10 Oct). Older openers said Akron, Ohio."""
    if not text:
        return text
    for pat, rep in HOME_FIXES:
        text = re.sub(pat, rep, text)
    return text


def build(params: dict, today: dt.date) -> tuple[list[dict], list[dict], dict]:
    kept: dict[str, dict] = {}
    rejected: list[dict] = []
    lanes = {}
    checks = load_link_check()
    for path in sorted(RAW.glob("*.json")):
        lane = path.stem
        try:
            rows = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            rejected.append({"lane": lane, "name": path.name, "reasons": [f"invalid JSON: {exc}"]})
            continue
        if not isinstance(rows, list):
            rows = rows.get("targets", []) if isinstance(rows, dict) else []
        lanes[lane] = {"raw": len(rows), "kept": 0}
        for row in rows:
            if not isinstance(row, dict):
                continue
            reasons = validate(row, params, today)
            if reasons:
                rejected.append({"lane": lane, "name": row.get("name"), "reasons": reasons})
                continue
            row = dict(row)
            row["opener"] = home_fix(row.get("opener"))
            row["lane"] = lane
            row["evidence"] = [u for u in row["evidence"] if isinstance(u, str) and u.startswith("http")]
            dead = apply_link_check(row, checks)
            if dead:
                rejected.append({"lane": lane, "name": row.get("name"), "reasons": [dead]})
                continue
            row["score"], row["priority"] = score(row, params, today)
            row["stale_signal"] = stale_signal(row, today)
            row["identity_needs_ok"] = (
                uses_founder_identity(row) and not params["outreach"].get("founder_identity_approved", False)
            )
            key = dedupe_key(row)
            prior = kept.get(key)
            if prior:
                # Keep the stronger row; merge the evidence so nothing is lost.
                merged_ev = list(dict.fromkeys(prior["evidence"] + row["evidence"]))
                winner = row if row["score"] > prior["score"] else prior
                winner["evidence"] = merged_ev
                kept[key] = winner
                continue
            kept[key] = row
            lanes[lane]["kept"] += 1
    review = load_review()
    for r in kept.values():
        rid = re.sub(r"\s+", "-", norm(f"{r['name']} {r.get('org') or ''}"))[:80]
        v = review.get(rid)
        if v:
            r["review"], r["review_reason"], r["move"] = v.get("verdict"), v.get("reason"), v.get("move")
            r["score"] += {"A": 40, "B": 10}.get(v.get("verdict"), 0)
    for r in kept.values():
        if is_supplier(r):
            r["review"], r["review_reason"] = "cut", "supplier, rule 7, not an outreach lane"
    parked = [r for r in kept.values() if costs_money(r) or r.get("review") == "cut"]
    PARKED.clear()
    PARKED.extend({"name": r["name"], "type": r["type"], "geo": r.get("geo"), "ask": r.get("ask"),
                   "why_parked": r.get("review_reason") if r.get("review") == "cut" else "costs money"} for r in parked)
    for r in kept.values():
        r["when"] = "after DevKit v0.1" if needs_units(r) else "now"
    for r in kept.values():
        big_name_fields(r)
    # Rule 12: rank by the name on the door first, then fit and score. Signals are context, not a hunt.
    targets = sorted((r for r in kept.values() if not costs_money(r) and r.get("review") != "cut"),
                     key=lambda r: (r["type"] == "signal", -r["big_name"], -r["score"], r.get("deadline") or "9999", r["name"]))
    for i, row in enumerate(targets, 1):
        row["rank"] = i
        row["sendable"] = is_sendable(row)
        row.setdefault("move", row.get("ask"))  # the console reads move on every target
        if not row.get("move"):
            row["move"] = row.get("ask")
        row["id"] = re.sub(r"\s+", "-", norm(f"{row['name']} {row.get('org') or ''}"))[:80]
        scrub_claims(row)
    threads = {norm(t["org"]): t for t in load_followups()["threads"]}
    john, batch1 = load_john()
    JOHN_BY_ORG.clear(); JOHN_BY_ORG.update(john)
    batch1_ids = {k for k, it in load_approvals().get("items", {}).items() if it.get("batch") == 1}
    for row in targets:
        decision_fields(row, threads.get(norm(row.get("org"))) or threads.get(norm(row["name"])))
        v = john.get(norm(row.get("org"))) or john.get(norm(row["name"]))
        john_fields(row, v or (batch1 if row["id"] in batch1_ids else None))
        draft_fields(row)
    return targets, rejected, lanes


# Approved claims only: heart rate, HRV and sleep timing (founder). Never "ECG".
CLAIM_FIXES = [
    (re.compile(r"ECG[- ]based\s+", re.I), ""),
    (re.compile(r"\bECG\s*[/-]\s*HRV\b|\bHRV\s*/\s*ECG\b", re.I), "HRV"),
    (re.compile(r"\bECG\b"), "heart rate"),
]
CLAIM_FIELDS = ("why", "why_now", "ask", "opener", "move", "opportunity", "review_reason")


def scrub_claims(row: dict) -> None:
    for f in CLAIM_FIELDS:
        v = row.get(f)
        if isinstance(v, str):
            for rx, rep in CLAIM_FIXES:
                v = rx.sub(rep, v)
            row[f] = v


# Rule 12: big name, small batch. A first pass from the organisation's name and type;
# BIG_NAME_OVERRIDES in data/big_name.json wins when the founder or a review sets one.
BIG_NAME_TIERS = [
    (10, r"\b(garmin|whoop|oura|apple|google|samsung|strava|withings|fitbit|reddit|product hunt|y combinator|andreessen horowitz|us fda|us hhs|mayo clinic)\b"),
    (9, r"\b(concept2|the verge|business insider|techstars|life time|labcorp|home assistant|ncaa|team usa)\b"),
    (8, r"\b(duke|university of north carolina|ohio state|stanford|arizona state|university of pittsburgh|oregon health|university of massachusetts|university of kentucky|82nd airborne|air force research|naval postgraduate|uniformed services university|u\.s\. army|rti international|trainingpeaks|dc rainmaker|national strength and conditioning|crosslink|point nine|founder institute|idc)\b"),
    (7, r"\b(techradar|android central|lifehacker|golden seeds|mac venture|female founders fund|alumni ventures|reach capital|junction|terra|sleep cycle|fitbod|rise science|intervals\.icu|wellstar|quantified self|former fitbit|oura \(co-founder\)|stanford spezi|national fallen firefighters)\b"),
    (6, r"\b(hrv4training|welltory|elite hrv|raleigh fire|charlotte fire|wake county ems|fleet feet|37 angels|pipeline angels|hivers|lexipol|o2x|crowd supply|university|college|37angels|the veteran fund|vetted)\b"),
]
BIG_NAME_DEFAULT = {"vc": 5, "corporate-vc": 6, "accelerator": 6, "research-lab": 6, "channel-partner": 5,
                    "angel-group": 5, "syndicate": 4, "angel": 4, "app-partner": 4, "amplifier": 4,
                    "community": 4, "listing": 4, "program": 5, "event": 4, "team": 6, "builder": 3, "signal": 5}
BIG_NAME_REASON = {10: "a household or national name", 9: "a household or national name",
                   8: "a flagship institution, national body or major fund", 7: "a flagship institution, national body or major fund",
                   6: "a regional body, known niche name or seed fund", 5: "a regional body, known niche name or seed fund"}
FIRST_BATCH = {"app-partner": "one data feed into their app for 10 to 25 consenting users",
               "builder": "one data feed into their tool for 10 to 25 consenting users",
               "research-lab": "one small pilot of 10 to 25 participants",
               "channel-partner": "one pilot team of 10 to 25", "team": "one pilot team of 10 to 25",
               "community": "one pilot group of 10 to 25 members", "amplifier": "one review, feature or mention",
               "listing": "one free listing", "signal": "context only, no ask"}
BIG_NAME_FILE = ROOT / "data" / "big_name.json"


def big_name_fields(row: dict) -> None:
    over = {}
    if BIG_NAME_FILE.exists():
        over = json.loads(BIG_NAME_FILE.read_text()).get("rows", {})
    text = norm(row.get("org") or row["name"])
    score = next((n for n, rx in BIG_NAME_TIERS if re.search(rx, text)), BIG_NAME_DEFAULT.get(row["type"], 3))
    # A project or chapter that only mentions a big brand is not that brand.
    if re.search(r"github|open source|developer group|self-hoster|\bon polar\b|unnamed|name not public|/", text):
        score = min(score, 4)
    if row["type"] == "angel":
        score = min(score, 7)
    o = over.get(row.get("id") or "") or {}
    score = o.get("big_name", score)
    reason = BIG_NAME_REASON.get(score, "a local or niche name with little recognition outside its field")
    batch = FIRST_BATCH.get(row["type"], "a first intro call" if row["hunt"] == "investor" else "one small pilot")
    row["big_name"] = score
    row["big_name_why"] = o.get("big_name_why") or f"{row.get('org') or row['name']} is {reason}; first batch: {batch}."


def draft_fields(row: dict) -> None:
    """Rule 11/12 front page: an unsent draft is published in full; a sent one carries no body."""
    unsent = row.get("status") == "drafted" and bool(row.get("opener"))
    row["draft_to"] = (row.get("role") or row.get("org") or row["name"]) if unsent else ""
    row["draft_subject"] = email_subject(row) if unsent else ""
    row["draft_body"] = (row["opener"].strip() + SIGNOFF) if unsent else ""
    row["send_today"] = unsent and row.get("john_verdict") == "approve" and not is_supplier(row) and not costs_money(row)


JOHN_BY_ORG: dict = {}
DECISION_KEYS = ("org", "what_is", "status", "offer", "we_need", "they_need", "cost", "next_date", "size", "size_source")
# Rule 9.7 (VYBE-AGENT-STANDARDS.md): every lead carries the decision fields.
THREAD_STATUS = {"no reply": "waiting", "auto-reply only": "waiting", "replied": "replied",
                 "replied: meeting": "booked", "no go": "closed", "closed": "closed"}
THEY_NEED = {
    "investor": "Pre-seed deal flow in wearables and health data that fits their thesis.",
    "signal": "",
}
THEY_NEED_DEFAULT = "An open source of overnight HRV, heart rate and sleep timing their users can bring in, without a closed vendor API."


def first_sentence(text: str | None) -> str:
    text = (text or "").strip()
    m = re.match(r"(.+?(?<!\bDr)(?<!\bMr)(?<!\bMs)(?<!\bSt)(?<!\bInc)(?<!\be\.g)(?<!\bi\.e)(?<!\bU\.S)(?<!\bvs)[.!?])(\s+[A-Z]|$)", text)
    return (m.group(1) if m else text)[:260]


def money(text: str | None) -> float | None:
    """Largest dollar amount in a string: '$250K-$1M' -> 1000000."""
    best = None
    for n, unit in re.findall(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB])?\b", text or ""):
        v = float(n.replace(",", "")) * {"k": 1e3, "m": 1e6, "b": 1e9}.get(unit.lower(), 1)
        best = v if best is None or v > best else best
    return best


def thread_status(t: dict) -> str:
    if "declined" in (t.get("next") or "").lower() or "perhaps in the future" in (t.get("next") or "").lower():
        return "declined"
    return THREAD_STATUS.get(t.get("state"), "waiting")


def decision_fields(row: dict, thread: dict | None) -> None:
    src = (row.get("evidence") or [""])[0]
    host = re.sub(r"^https?://(www\.)?", "", src).split("/")[0]
    row["what_is"] = first_sentence(row.get("why")) + (f" (source: {host})" if host else "")
    row["status"] = thread_status(thread) if thread else "drafted"
    row["offer"] = (thread or {}).get("offer", "")
    row["we_need"] = row.get("opportunity") or row.get("ask") or ""
    row["they_need"] = row.get("why_now") or THEY_NEED.get(row["type"], THEY_NEED.get(row["hunt"], THEY_NEED_DEFAULT))
    row["cost"] = 0  # rows that cost money are parked before they reach the board
    row["next_date"] = row.get("deadline") or (thread or {}).get("due") or ""
    size = money(row.get("check_size")) if row["hunt"] == "investor" else None
    row["size"] = size
    row["size_source"] = f"check size listed at {host}" if size and host else ""


# Rule 11: John's reply is the verdict on a draft.
def load_john() -> tuple[dict, dict | None]:
    if not JOHN.exists():
        return {}, None
    rows = json.loads(JOHN.read_text())["verdicts"]
    by_org = {norm(r["org"]): r for r in rows if r["org"] != "__batch1__"}
    batch1 = next((r for r in rows if r["org"] == "__batch1__"), None)
    return by_org, batch1


def john_fields(row: dict, v: dict | None) -> None:
    row["john_verdict"] = (v or {}).get("verdict", "none")
    row["john_said"] = ((v or {}).get("said") or "")[:200]
    row["john_at"] = (v or {}).get("at", "")


def thread_fields(t: dict, targets_by_org: dict) -> dict:
    row = targets_by_org.get(norm(t["org"])) or {}
    t = dict(t)
    t["status"] = thread_status(t)
    t.setdefault("offer", "")
    t["what_is"] = row.get("what_is", "")
    t["we_need"] = row.get("we_need", "")
    t["they_need"] = row.get("they_need", "")
    t["cost"] = t.get("cost", money(t.get("next")) or 0)
    t["next_date"] = "" if t["status"] in ("closed", "declined") else (t.get("due") or "")
    t.setdefault("size", None)
    t["draft_to"], t["draft_subject"], t["draft_body"], t["send_today"] = "", "", "", False
    t.setdefault("size_source", "")
    john_fields(t, JOHN_BY_ORG.get(norm(t["org"])))
    return t


QUEUE_HUNTS = ("partnership", "growth", "social")
PARKED: list = []
# The Vybe Health Calendly (jeremy@vybe.health). Never the i-grow account.
CALENDLY = "https://calendly.com/jeremy-vybe/30min"
SIGNOFF = "\n\nJeremy Lahn\nVybe Health\njeremy@vybe.health · vybe.health"


def email_subject(row: dict) -> str:
    """A plain subject line built only from fields already on the row."""
    if row["hunt"] == "sponsorship":
        return f"Vybe Health x {row['name']}: small sponsorship idea"
    if row["type"] == "app-partner":
        return f"Vybe Health x {row['name']}: overnight data integration"
    if row["type"] == "oem-partner":
        return f"Vybe Health: DevKit build inquiry for {row['org'] or row['name']}"
    return f"Vybe Health x {row['name']}: partnership idea"


def followup_body(row: dict) -> str:
    """The one follow-up allowed per contact, sent 5-7 days after the first email.

    Sent as a reply on the first email's thread, so it points back to that note
    and adds no new claims. The row's ask is an internal note, never quoted.
    """
    return (f"Hello {row['name']} team,\n\nFollowing up on my note below. "
            "Could you point me to the right person, or let me know if it's a fit?\n\n"
            f"If a short call is easier, you can pick a time that suits you here: {CALENDLY}" + SIGNOFF)


def load_followups() -> dict:
    if not FOLLOWUPS.exists():
        return {"note": "", "checked": None, "threads": []}
    data = json.loads(FOLLOWUPS.read_text())
    data["threads"].sort(key=lambda r: (r.get("due") or "9999", r["org"]))
    return data


def stale_signal(row: dict, today: dt.date) -> bool:
    """why_now only cites years before this one and there is no future deadline."""
    if parse_date(row.get("deadline")):
        return False
    years = [int(y) for y in re.findall(r"\b(20\d\d)\b", row.get("why_now") or "")]
    return bool(years) and max(years) < today.year


APPROVALS_CACHE: dict = {}


def load_approvals() -> dict:
    """John approves every draft before it is sent (founder, 10 Oct)."""
    if not APPROVALS.exists():
        return {"approver": "john@vybe.health", "items": {}}
    return json.loads(APPROVALS.read_text())


def outreach_queue(targets: list[dict]) -> list[dict]:
    """Ready-to-send emails for sponsorship and partner targets, best first.

    Drafts only: nothing here is sent. Rows held for the founder-identity
    decision, dead contact links and warm-intro-only rows are already excluded
    by is_sendable().
    """
    queue = []
    for t in targets:
        if t["hunt"] not in QUEUE_HUNTS or not t.get("sendable") or t.get("stale_signal"):
            continue
        queue.append({
            "id": t["id"], "name": t["name"], "org": t["org"], "type": t["type"], "hunt": t["hunt"],
            "priority": t["priority"], "rank": t["rank"], "deadline": t.get("deadline"),
            "channel": t.get("channel"), "contact_url": t.get("contact_url"),
            "evidence": (t.get("evidence") or [None])[0], "ask": t.get("ask"),
            "subject": email_subject(t), "body": t["opener"].strip() + SIGNOFF,
            "followup_subject": "Re: " + email_subject(t), "followup_body": followup_body(t),
            "approval": (APPROVALS_CACHE.get(t["id"]) or {}).get("status", "not requested"),
        })
    return queue


def summary(targets: list[dict], today: dt.date) -> dict:
    def count(pred):
        return sum(1 for t in targets if pred(t))

    soon = [t for t in targets if (d := parse_date(t.get("deadline"))) and 0 <= (d - today).days <= 30]
    return {
        "total": len(targets),
        "investor": count(lambda t: t["hunt"] == "investor" and t["type"] != "signal"),
        "growth": count(lambda t: t["hunt"] == "growth" and t["type"] != "signal"),
        "social": count(lambda t: t["hunt"] == "social"),
        "sponsorship": count(lambda t: t["hunt"] == "sponsorship" and t["type"] != "competitor-deal"),
        "app_partners": count(lambda t: t["type"] == "app-partner"),
        "sports": count(lambda t: t["type"] == "sport"),
        "competitor_deals": count(lambda t: t["type"] == "competitor-deal"),
        "signals": count(lambda t: t["type"] == "signal"),
        "high": count(lambda t: t["priority"] == "High" and t["type"] != "signal"),
        "deadlines_30d": len(soon),
        "ready_to_send": count(lambda t: t.get("sendable")),
        "identity_needs_ok": count(lambda t: t.get("identity_needs_ok")),
        "outreach_queue": count(lambda t: t["hunt"] in QUEUE_HUNTS and t.get("sendable")),
        "rule_9_7": all(all(k in t for k in DECISION_KEYS) for t in targets),
        "hardware_lanes_retired": True,
        "hardware_parked": sum(1 for r in PARKED if "rule 7" in (r.get("why_parked") or "")),
        "rule_12": all("big_name" in t and "big_name_why" in t for t in targets),
        "drafts_published": all("send_today" in t and "draft_body" in t for t in targets),
        "wins": count(lambda t: t.get("status") in ("replied", "booked") and t.get("john_verdict") != "no" and t.get("big_name", 0) >= 7),
        "send_today": count(lambda t: t.get("send_today")),
        "rule_11": all(all(k in t for k in ("john_verdict", "john_said", "john_at")) for t in targets),
    }


def render(data: dict) -> str:
    template = (ROOT / "template.html").read_text()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (
        template.replace("/*__DATA__*/null", payload)
        .replace("__GENERATED__", html.escape(data["generated"]))
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    args = ap.parse_args()

    params = load_params()
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    targets, rejected, lanes = build(params, today)
    combos, screened_apps = load_partner_extras()

    print(f"{len(targets)} targets kept, {len(rejected)} rejected")
    for lane, c in lanes.items():
        print(f"  {lane:14} raw {c['raw']:3}  kept {c['kept']:3}")
    for r in rejected[:40]:
        print(f"  rejected [{r['lane']}] {r['name']}: {'; '.join(r['reasons'])}")
    if args.check:
        bad = [r for r in rejected if any("invalid JSON" in x or "never a guessed" in x for x in r["reasons"])]
        return 1 if bad else 0

    approvals = load_approvals()
    APPROVALS_CACHE.clear()
    APPROVALS_CACHE.update(approvals.get("items", {}))
    followups = load_followups()
    by_org = {norm(t.get("org")): t for t in targets}
    followups["threads"] = [thread_fields(t, by_org) for t in followups["threads"]]
    data = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "today": today.isoformat(),
        "scope": params["scope"],
        "sprint": params["sprint"],
        "lanes": [{"id": l["id"], "title": l["title"], "hunt": l["hunt"], **lanes.get(l["id"], {"raw": 0, "kept": 0})}
                  for l in params["lanes"]],
        "summary": summary(targets, today),
        "by_state": by_state(targets),
        "targets": targets,
        "combos": combos["combos"],
        "combos_note": combos.get("note", ""),
        "screened_apps": screened_apps,
        "rejected_count": len(rejected),
        "approvals": approvals,
        "outreach": outreach_queue(targets),
        "followups": followups,
        "parked_count": len(PARKED),
        "parked_rule": "Parked (costs money): sponsorships, tables, booths, vendor slots, expo or event fees, tiers, prizes and athlete deals. Founder, 11 Oct: no spend.",
    }
    (ROOT / "data" / "parked.json").write_text(json.dumps({"rule": data["parked_rule"], "rows": PARKED}, indent=2, ensure_ascii=False) + "\n")
    (ROOT / "data" / "targets.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    (SITE / "index.html").write_text(render(data))
    print(f"wrote {SITE / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
