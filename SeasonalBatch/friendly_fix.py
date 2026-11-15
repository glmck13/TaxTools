#!/usr/bin/env python3
import csv
import re
import sys

INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "demographics.csv"
fname = INPUT_FILE.split('.')
fname.append(".csv")
OUTPUT_FILE = fname[0] + "-populated." + fname[1]
REVIEW_FILE = fname[0] + "-review." + fname[1]

ENTITY_KEYWORDS = re.compile(
    r"\b(?:LLC|Inc|Corp|LLP|PLLC|Ltd|Limited|PC|PA|Trust|Estate|Tr|Foundation|"
    r"Associates|Advisors|Partners|Partnership|Holdings|Group|Enterprises|Services|"
    r"Consulting|Ventures|Properties|Management|Realty|Rentals|Shop|Farm|Company|"
    r"Declaration|Systems|Therapy|Law|Trustar|VBAD)\b",
    re.IGNORECASE,
)

INTERNAL_EMAILS = {
    "katie@tarrantadvisors.com",
    "s.tarrant@tarrantadvisors.com",
    "steve@matcpava.com",
    "null",
    "",
}

# Legacy QBO 2-token "Last First" rows that lack a comma or double-space
LEGACY_LAST_FIRST = {
    "Brown Ellenor",
    "Cillpam Polly",
    "Fleming Janet",
    "Franko Emily",
    "Gill Daniel",
    "Mapar Jalal",
    "Moore Kyle",
    "Romanski Shannon",
}


def clean_suffixes(name: str) -> str:
    # Strip QBO duplicate merge timestamps like _1765539769682 or trailing -1
    name = re.sub(r"_\d{10,}$", "", name.strip())
    name = re.sub(r"-1$", "", name.strip())
    return re.sub(r"\s+", " ", name).strip()


def is_entity_name(name: str) -> bool:
    clean = clean_suffixes(name)
    return (
        bool(ENTITY_KEYWORDS.search(clean))
        or clean.upper().startswith("QB TIME")
        or clean.lower().startswith("test,")
        or clean in {"Loudoun County Volleyball", "Loudoun County Volleyball - New", "Synergy Three"}
    )


def smart_title(text: str) -> str:
    words = text.split()
    out = []
    for w in words:
        # Capitalize ALL-CAPS words (len > 1) or all-lowercase words, preserving McGady/DeCamp
        if (w.isupper() and len(w) > 1) or w.islower():
            out.append(w.capitalize())
        else:
            out.append(w)
    return " ".join(out)


def parse_individual_name(raw_name: str):
    """Returns (primary_friendly_name, optional_cosigner_name)"""
    name = clean_suffixes(raw_name)

    # Care-of handling: "Biller, Robert C-O Scott Biller" -> "Scott Biller"
    co_match = re.search(r"\bC[-/]O\s+(.+)$", name, re.IGNORECASE)
    if co_match:
        return smart_title(co_match.group(1)), ""

    if "," in name:
        last_part, rest = [p.strip() for p in name.split(",", 1)]
        people = re.split(r"\s*(?:&|\band\b)\s*", rest, maxsplit=1, flags=re.IGNORECASE)
        first1 = people[0].strip()
        primary = smart_title(f"{first1} {last_part}")

        cosigner = ""
        if len(people) > 1 and people[1].strip():
            p2 = people[1].strip()
            if "," in p2:
                # e.g., "Orth, Claire" -> "Claire Orth"
                c_last, c_first = [x.strip() for x in p2.split(",", 1)]
                cosigner = smart_title(f"{c_first} {c_last}")
            elif " " not in p2 or re.match(r"^[A-Za-z]+\s+[A-Za-z]\.?$", p2):
                # e.g., "Seth" -> "Seth Alberts", or "Joanne M" -> "Joanne M Smeaton"
                cosigner = smart_title(f"{p2} {last_part}")
            else:
                # e.g., "Ashley Whitewell" -> "Ashley Whitewell"
                cosigner = smart_title(p2)
        return primary, cosigner

    # Handle "Wyatt & Emma Grubb"
    amp_match = re.match(r"^([A-Za-z]+)\s*&\s*([A-Za-z]+)\s+([A-Za-z'-]+)$", name)
    if amp_match:
        f1, f2, last = amp_match.groups()
        return smart_title(f"{f1} {last}"), smart_title(f"{f2} {last}")

    # Explicit legacy "Last First" rows
    if name in LEGACY_LAST_FIRST:
        parts = name.split()
        return smart_title(f"{parts[1]} {parts[0]}"), ""

    # Handle "Last First M." / "LAST FIRST" / "Last  First"
    tokens = name.split()
    if len(tokens) in (2, 3):
        if len(tokens) == 3 and re.match(r"^[A-Za-z]\.?$", tokens[2]):
            return smart_title(f"{tokens[1]} {tokens[2]} {tokens[0]}"), ""
        if len(tokens) == 2 and (tokens[0].isupper() or "  " in raw_name):
            return smart_title(f"{tokens[1]} {tokens[0]}"), ""

    return smart_title(name), ""


def guess_from_email(email: str) -> str:
    email = email.strip().lower()
    if email in INTERNAL_EMAILS or "@" not in email:
        return ""
    local = email.split("@", 1)[0]
    if local in {"info", "admin", "office", "contact", "support", "accounting", "billing"}:
        return ""
    m = re.match(r"^([a-z]{2,})[._]([a-z]{2,})$", local)
    if m:
        return f"{m.group(1).capitalize()} {m.group(2).capitalize()}"
    return ""


def main():
    with open(INPUT_FILE, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=":")
        fieldnames = reader.fieldnames
        rows = list(reader)

    # 1. Build clean email -> primary human signer lookup
    email_to_person = {}
    for r in rows:
        em = r["primary_email"].strip().lower()
        if em in INTERNAL_EMAILS:
            continue
        fn = r["friendly_name"].strip()
        if fn and not is_entity_name(fn):
            normalized_fn, _ = parse_individual_name(fn) if "," in fn else (smart_title(fn), "")
            email_to_person.setdefault(em, normalized_fn)

    for r in rows:
        em = r["primary_email"].strip().lower()
        if em in INTERNAL_EMAILS or em in email_to_person:
            continue
        cname = r["client_name"].strip()
        if not is_entity_name(cname) and "," in cname:
            person, _ = parse_individual_name(cname)
            if person:
                email_to_person[em] = person

    # 2. Enrich missing friendly_names and clean literal "null" emails
    review_rows = []
    for r in rows:
        if r["primary_email"].strip().lower() == "null":
            r["primary_email"] = ""

        em = r["primary_email"].strip().lower()
        cname = r["client_name"].strip()
        source = "existing"

        if not r["friendly_name"].strip():
            if cname.upper().startswith("QB TIME") or cname.lower().startswith("test,"):
                source = "skip_internal_or_test"
            elif not is_entity_name(cname):
                primary, cosigner = parse_individual_name(cname)
                r["friendly_name"] = primary
                if cosigner and not r["co_signer_name"].strip():
                    r["co_signer_name"] = cosigner
                source = "parsed_client_name"
            elif em in email_to_person:
                r["friendly_name"] = email_to_person[em]
                source = "matched_by_email"
            else:
                guess = guess_from_email(em)
                if guess:
                    r["friendly_name"] = guess
                    source = "email_guess_review"
                else:
                    source = "needs_manual_lookup"

        review_row = dict(r)
        review_row["friendly_name_source"] = source
        review_rows.append(review_row)

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=":", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    with open(REVIEW_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(fieldnames) + ["friendly_name_source"],
            delimiter=":",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(review_rows)

    print(f"Done. Wrote {len(rows)} rows to {OUTPUT_FILE} and {REVIEW_FILE}.")


if __name__ == "__main__":
    main()
