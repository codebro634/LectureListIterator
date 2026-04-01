from __future__ import annotations

import argparse
import csv
import re
import ssl
import sys
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen


INPUT_FILE = Path("data/raw_html/inf1.txt")
OUTPUT_FILE = Path("data/contact_information") / INPUT_FILE.name
DEFAULT_BASE_URL = "https://qis.verwaltung.uni-hannover.de"
PERSON_CACHE_PATTERN = "person_{pid}.txt"


def normalize_whitespace(text: str) -> str:
    return " ".join(unescape(text).split())


def read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"Could not decode {path}")


def extract_person_id(url: str) -> str | None:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("personal.pid")
    if values:
        return values[0]
    match = re.search(r"personal\.pid=(\d+)", url)
    return match.group(1) if match else None


@dataclass
class LectureRecord:
    title: str
    lecturer_name: str | None = None
    lecturer_first_name: str | None = None
    lecturer_url: str | None = None
    lecturer_title: str | None = None
    lecturer_gender: str | None = None
    emails: list[str] = field(default_factory=list)


@dataclass
class PersonData:
    title: str | None = None
    first_name: str | None = None
    emails: list[str] = field(default_factory=list)


class LectureHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[LectureRecord] = []
        self._current_record: LectureRecord | None = None
        self._capture_lecture_title = False
        self._capture_lecturer = False
        self._lecture_parts: list[str] = []
        self._lecturer_parts: list[str] = []
        self._pending_label = False
        self._inside_td = False
        self._lecturer_anchor_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)

        if tag == "tr":
            self._pending_label = False

        if tag == "td":
            self._inside_td = True

        if tag != "a":
            return

        href = attributes.get("href", "") or ""
        anchor_class = (attributes.get("class", "") or "").strip()

        if "publishSubDir=veranstaltung" in href:
            self._finalize_current_record()
            self._current_record = LectureRecord(title="")
            self._capture_lecture_title = True
            self._lecture_parts = []
            return

        if (
            self._current_record
            and self._pending_label
            and not self._current_record.lecturer_name
            and anchor_class == "ver"
            and "personal.pid=" in href
        ):
            self._capture_lecturer = True
            self._lecturer_parts = []
            self._lecturer_anchor_href = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._inside_td = False

        if tag != "a":
            return

        if self._capture_lecture_title and self._current_record:
            self._current_record.title = normalize_whitespace("".join(self._lecture_parts))
            self._capture_lecture_title = False
            self._lecture_parts = []
            return

        if self._capture_lecturer and self._current_record:
            lecturer_name = normalize_whitespace("".join(self._lecturer_parts))
            self._current_record.lecturer_name = lecturer_name or None
            self._current_record.lecturer_url = self._lecturer_anchor_href
            self._capture_lecturer = False
            self._lecturer_parts = []
            self._lecturer_anchor_href = None

    def handle_data(self, data: str) -> None:
        text = normalize_whitespace(data)

        if self._capture_lecture_title:
            self._lecture_parts.append(data)
            return

        if self._capture_lecturer:
            self._lecturer_parts.append(data)
            return

        if self._current_record and self._inside_td and text in {"Dozent:", "Dozenten:", "Lehrende:"}:
            self._pending_label = True

    def close(self) -> None:
        super().close()
        self._finalize_current_record()

    def _finalize_current_record(self) -> None:
        if self._current_record and self._current_record.title:
            self.records.append(self._current_record)
        self._current_record = None
        self._capture_lecture_title = False
        self._capture_lecturer = False
        self._lecture_parts = []
        self._lecturer_parts = []
        self._pending_label = False
        self._lecturer_anchor_href = None


class PersonEmailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.emails: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return

        attributes = dict(attrs)
        href = attributes.get("href", "") or ""
        if href.startswith("mailto:"):
            email = normalize_whitespace(href.removeprefix("mailto:"))
            if email and email not in self.emails:
                self.emails.append(email)


def parse_lectures(html: str) -> list[LectureRecord]:
    parser = LectureHTMLParser()
    parser.feed(html)
    parser.close()
    return parser.records


def parse_person_emails(html: str) -> list[str]:
    parser = PersonEmailParser()
    parser.feed(html)
    parser.close()
    return parser.emails


def extract_person_name_block(html: str) -> str | None:
    match = re.search(
        r"<td class=\"tab_gross\"[^>]*>\s*<b>Name:</b>\s*</td>\s*<td class=\"normal\">\s*<strong>(.*?)</strong>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return normalize_whitespace(match.group(1))


def extract_person_title(html: str) -> str | None:
    name_block = extract_person_name_block(html)
    if not name_block:
        return None

    title_match = re.match(
        r"^((?:(?:Prof\.|Dr\.|Jun\.-Prof\.|Priv\.-Doz\.|PD|apl\.\s*Prof\.)\s*)+)",
        name_block,
    )
    if not title_match:
        return None
    return normalize_whitespace(title_match.group(1))


def extract_person_first_name(html: str) -> str | None:
    name_block = extract_person_name_block(html)
    if not name_block:
        return None

    title = extract_person_title(html)
    if title:
        name_block = name_block.removeprefix(title).strip()

    parts = [part for part in name_block.split() if part]
    if not parts:
        return None
    return parts[0]


def guess_gender_from_first_name(first_name: str | None) -> str | None:
    if not first_name:
        return None

    normalized = (
        first_name.lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
        .strip("- ")
    )

    female_names = {
        "alexandra", "anna", "anne", "barbara", "birgit", "christina", "claudia", "cornelia",
        "dorothea", "eva", "friederike", "hannah", "heike", "ines", "julia", "katharina",
        "katja", "lara", "lea", "lena", "lisa", "maria", "marie", "melanie", "nadine",
        "nina", "sandra", "sarah", "simone", "sofia", "sophia", "susanne", "theresa",
    }
    male_names = {
        "alexander", "andreas", "benjamin", "christian", "daniel", "david", "dennis", "domenico",
        "fabian", "felix", "florian", "frank", "georg", "henning", "jan", "jonas", "johannes",
        "julius", "kai", "kevin", "klaus", "lars", "lukas", "marcel", "markus", "martin",
        "michael", "moritz", "nils", "oliver", "oskar", "patrick", "paul", "peter", "philipp",
        "robin", "sebastian", "stefan", "thomas", "tobias", "uwe", "vincent", "walter",
    }

    if normalized in female_names:
        return "weiblich"
    if normalized in male_names:
        return "männlich"
    if normalized.endswith(("a", "ia", "na")) and not normalized.endswith(("uca", "nikita")):
        return "weiblich"
    if normalized.endswith(("o", "us", "er", "ian")):
        return "männlich"
    return None


def parse_person_data(html: str) -> PersonData:
    return PersonData(
        title=extract_person_title(html),
        first_name=extract_person_first_name(html),
        emails=parse_person_emails(html),
    )


def fetch_person_page(url: str, cookie: str | None) -> str:
    headers = {"User-Agent": "LectureListIterator/1.0"}
    if cookie:
        headers["Cookie"] = cookie

    request = Request(url, headers=headers)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with urlopen(request, timeout=30, context=context) as response:
        raw = response.read()
        content_type = response.headers.get_content_charset() or "utf-8"
        return raw.decode(content_type, errors="replace")


def resolve_person_html(
    lecturer_url: str | None,
    cache_dir: Path | None,
    cookie: str | None,
    base_url: str,
    person_fallback: Path | None,
) -> str | None:
    if not lecturer_url:
        return None

    person_id = extract_person_id(lecturer_url)
    if cache_dir and person_id:
        cache_path = cache_dir / PERSON_CACHE_PATTERN.format(pid=person_id)
        if cache_path.exists():
            return read_text_with_fallback(cache_path)

    if person_fallback and person_fallback.exists():
        return read_text_with_fallback(person_fallback)

    absolute_url = urljoin(base_url, lecturer_url)
    try:
        return fetch_person_page(absolute_url, cookie)
    except Exception as exc:  # pragma: no cover
        print(f"Warning: could not fetch {absolute_url}: {exc}", file=sys.stderr)
        return None


def enrich_with_emails(
    records: list[LectureRecord],
    cache_dir: Path | None,
    cookie: str | None,
    base_url: str,
    person_fallback: Path | None,
) -> None:
    person_cache: dict[str, PersonData] = {}
    retrieved_email_count = 0

    for index, record in enumerate(records, start=1):
        if not record.lecturer_url:
            continue

        cache_key = record.lecturer_url
        if cache_key not in person_cache:
            person_html = resolve_person_html(
                lecturer_url=record.lecturer_url,
                cache_dir=cache_dir,
                cookie=cookie,
                base_url=base_url,
                person_fallback=person_fallback,
            )
            person_cache[cache_key] = parse_person_data(person_html) if person_html else PersonData()
            retrieved_email_count += len(person_cache[cache_key].emails)
            print(f"[{index}/{len(records)}] Retrieved emails so far: {retrieved_email_count}", file=sys.stderr)

        person_data = person_cache[cache_key]
        record.lecturer_title = person_data.title
        record.lecturer_first_name = person_data.first_name
        record.lecturer_gender = guess_gender_from_first_name(person_data.first_name)
        record.emails = person_data.emails


def print_records(records: list[LectureRecord]) -> None:
    for record in records:
        emails = ", ".join(record.emails) if record.emails else "-"
        lecturer = record.lecturer_name or "-"
        lecturer_first_name = record.lecturer_first_name or "-"
        lecturer_title = record.lecturer_title or "-"
        lecturer_gender = record.lecturer_gender or "-"
        print(f"Lecture: {record.title}")
        print(f"First lecturer: {lecturer}")
        print(f"First name: {lecturer_first_name}")
        print(f"Title: {lecturer_title}")
        print(f"Gender: {lecturer_gender}")
        print(f"Emails: {emails}")
        print()

    print(f"Total lectures found: {len(records)}")


def write_csv(records: list[LectureRecord], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=";")
        writer.writerow(["lecture", "teacher", "first_name", "title", "gender", "mails"])
        for record in records:
            writer.writerow(
                [
                    record.title,
                    record.lecturer_name or "",
                    record.lecturer_first_name or "",
                    record.lecturer_title or "",
                    record.lecturer_gender or "",
                    ",".join(record.emails),
                ]
            )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract lecture titles, first lecturer, and lecturer emails from LUH QIS HTML."
    )
    parser.add_argument("--input", type=Path, default=INPUT_FILE, help="Path to the lecture list HTML file.")
    parser.add_argument("--output", type=Path, default=None, help="Path to the generated CSV file.")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory containing cached person pages named like person_<pid>.txt.",
    )
    parser.add_argument(
        "--person-fallback",
        type=Path,
        default=None,
        help="Fallback person HTML file to use when no cached page exists.",
    )
    parser.add_argument(
        "--cookie",
        default=None,
        help="Authenticated Cookie header value used when fetching person pages online.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL for relative lecturer links.")
    return parser


def filter_records(records: list[LectureRecord]) -> list[LectureRecord]:
    skip_terms = ["labor", "StudiStart", "Denkwerkstatt", "Studienleistung", "Lernraum", "Saturday", "Ringvorlesung", "Fachschaftsrat", "Schreiben","Labor","Projekt","seminar","Online","Praktikum","praktikum","Projektarbeit", "Kolloquium","Sprechzeit", "Schulung", "übung", "Übung", "Praktikum", "Seminar", "Repetitorium", "Hörsaalübung", "im Rahmen des"]
    return [record for record in records if not any(term in record.title for term in skip_terms)]


def main() -> None:
    args = build_arg_parser().parse_args()
    lecture_html = read_text_with_fallback(args.input)
    output_file = args.output or (OUTPUT_FILE.parent / args.input.name)
    records = parse_lectures(lecture_html)
    enrich_with_emails(
        records=records,
        cache_dir=args.cache_dir,
        cookie=args.cookie,
        base_url=args.base_url,
        person_fallback=args.person_fallback,
    )
    records = filter_records(records)
    print_records(records)
    write_csv(records, output_file)


if __name__ == "__main__":
    main()
