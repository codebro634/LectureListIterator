from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


MAIL_TEMPLATE = """{SALUTATION}

ich organisiere zusammen mit der MaPhy und Informatik Fachschaft den
jährlichen Integrierwettbewerb. Hätten Sie Lust uns zu
unterstützen indem Sie unser Plakat (siehe Anhang) auf Stud.IP in {VERANSTALTUNGEN_PRE} {VERANSTALTUNGEN} posten oder als Datei hochladen? Das würde uns
riesig helfen! Der Wettbewerb geht in die 5. Runde und wenn Sie
einmal etwas dazu lesen möchten, dann gerne unsere Seite
"integrierwettbewerb.de" klicken 😊

Liebe Grüße,
Robin Schmöcker
"""

BASE_DIR = Path(__file__).resolve().parent
CONTACTS_CSV = BASE_DIR / "data" / "contact_information" / "all_contacts.csv"
ATTACHMENT_PATH = BASE_DIR / "data" / "contact_information" / "poster2026.jpeg"
MAIL_URL = "https://www.tnt.uni-hannover.de/webmail"
SUBJECT = "Integrierwettbewerb 2026"

COMPOSE_LINK = (By.CSS_SELECTOR, "a.compose[href*='_action=compose']")
TO_FIELD = (By.ID, "_to")
SUBJECT_FIELD = (By.ID, "compose-subject")
BODY_FIELD = (By.ID, "composebody")
SEND_BUTTON = (By.ID, "rcmbtn111")
ATTACHMENT_INPUT = (By.ID, "uploadformInput")


def build_salutation(name: str, title: str, gender: str = "") -> str:
    clean_name = name.strip()
    clean_title = title.strip()
    clean_gender = gender.strip().lower()

    if clean_title:
        suffix = "r" if clean_gender in {"m", "männlich", "maennlich", "male"} else ""
        return f"Sehr geehrte{suffix} {clean_title} {clean_name},"

    if clean_gender in {"m", "männlich", "maennlich", "male"}:
        return f"Sehr geehrter Herr {clean_name},"

    if clean_gender in {"w", "weiblich", "female"}:
        return f"Sehr geehrte Frau {clean_name},"

    return f"Guten Tag {clean_name},"


def mail_text(lectures: list[str], name: str, title: str, gender: str = "") -> str:
    return MAIL_TEMPLATE.format(
        SALUTATION=build_salutation(name=name, title=title, gender=gender),
        VERANSTALTUNGEN_PRE="ihren Veranstaltungen" if len(lectures) > 1 else "ihrer Veranstaltung",
        VERANSTALTUNGEN=(", ".join(lectures[:-1]) + f" und {lectures[-1]}") if len(lectures) > 1 else lectures[0],
    )


def normalize_lectures(raw_value: str) -> list[str]:
    return [lecture.strip() for lecture in raw_value.split("|") if lecture.strip()]


def primary_email(raw_value: str) -> str:
    for part in raw_value.replace(";", ",").split(","):
        candidate = part.strip()
        if candidate:
            return candidate
    return ""


def iter_contacts() -> Iterable[dict[str, str]]:
    with CONTACTS_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            lectures = normalize_lectures(row.get("lecture", ""))
            email = primary_email(row.get("mails", ""))
            last_name = (row.get("teacher") or "").strip()

            if not lectures or not email or not last_name:
                continue

            yield {
                "email": email,
                "lectures": lectures,
                "last_name": last_name,
                "title": (row.get("title") or "").strip(),
                "gender": (row.get("gender") or "").strip(),
            }


def make_driver() -> webdriver.Chrome:
    options = Options()
    options.add_experimental_option("detach", True)
    return webdriver.Chrome(options=options)


def wait_for_inbox(driver: webdriver.Chrome, timeout: int = 60) -> None:
    def inbox_ready(browser: webdriver.Chrome) -> bool:
        body = browser.find_element(By.TAG_NAME, "body")
        return "action-compose" not in (body.get_attribute("class") or "")

    WebDriverWait(driver, timeout).until(EC.presence_of_element_located(COMPOSE_LINK))
    WebDriverWait(driver, timeout).until(inbox_ready)


def wait_for_compose(driver: webdriver.Chrome, timeout: int = 60) -> None:
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located(TO_FIELD))
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located(SUBJECT_FIELD))
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located(BODY_FIELD))


def open_compose(driver: webdriver.Chrome) -> None:
    wait_for_inbox(driver)
    driver.find_element(*COMPOSE_LINK).click()
    wait_for_compose(driver)


def clear_and_type(element, value: str) -> None:
    element.click()
    element.send_keys(Keys.CONTROL, "a")
    element.send_keys(Keys.DELETE)
    if value:
        element.send_keys(value)


def set_field_value(driver: webdriver.Chrome, locator: tuple[str, str], value: str) -> None:
    element = driver.find_element(*locator)

    try:
        clear_and_type(element, value)
        return
    except Exception:
        pass

    driver.execute_script(
        """
        const element = arguments[0];
        const value = arguments[1];
        element.value = value;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
        element.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Enter' }));
        element.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter' }));
        """,
        element,
        value,
    )


def populate_compose_form(driver: webdriver.Chrome, email: str, subject: str, body: str) -> None:
    set_field_value(driver, TO_FIELD, email)
    set_field_value(driver, SUBJECT_FIELD, subject)
    set_field_value(driver, BODY_FIELD, body)

    WebDriverWait(driver, 15).until(lambda browser: browser.find_element(*SEND_BUTTON).is_enabled())


def add_attachment(driver: webdriver.Chrome, attachment_path: Path) -> None:
    if not attachment_path.exists():
        raise SystemExit(f"Anhang nicht gefunden: {attachment_path}")

    upload = WebDriverWait(driver, 15).until(EC.presence_of_element_located(ATTACHMENT_INPUT))
    upload.send_keys(str(attachment_path.resolve()))
    WebDriverWait(driver, 60).until(
        lambda browser: attachment_path.name.lower() in browser.page_source.lower()
    )


def discard_draft_and_return_to_inbox(driver: webdriver.Chrome) -> None:
    try:
        driver.get(MAIL_URL)
    except UnexpectedAlertPresentException:
        try:
            alert = driver.switch_to.alert
            alert.accept()
            driver.get(MAIL_URL)
        except Exception:
            pass
    wait_for_inbox(driver)


def prompt_next_action(index: int, total: int, recipient: str) -> str:
    prompt = (
        f"[{index}/{total}] Mail an {recipient} vorbereitet. "
        "Im Browser pruefen und manuell senden. "
        "Danach 'sent' eingeben, mit 'skip' ueberspringen, mit 'quit' beenden: "
    )
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"sent", "skip", "quit"}:
            return answer
        print("Bitte genau 'sent', 'skip' oder 'quit' eingeben.")


def main() -> None:
    contacts = list(iter_contacts())
    if not contacts:
        raise SystemExit("Keine verarbeitbaren Kontakte in all_contacts.csv gefunden.")

    driver = make_driver()
    driver.get(MAIL_URL)

    try:
        wait_for_inbox(driver, timeout=300)
    except TimeoutException as exc:
        raise SystemExit(
            "Die Inbox-Ansicht wurde nicht gefunden. "
            "Bitte im gestarteten Chrome-Fenster bei tntwebmail.com einloggen und das Programm erneut ausfuehren."
        ) from exc

    for index, contact in enumerate(contacts, start=1):
        body = mail_text(
            lectures=contact["lectures"],
            name=contact["last_name"],
            title=contact["title"],
            gender=contact["gender"],
        )

        open_compose(driver)
        populate_compose_form(
            driver,
            email=contact["email"],
            subject=SUBJECT,
            body=body,
        )
        add_attachment(driver, ATTACHMENT_PATH)

        action = prompt_next_action(index=index, total=len(contacts), recipient=contact["email"])
        if action == "quit":
            print("Beendet. Das Browserfenster bleibt offen.")
            return

        if action == "skip":
            discard_draft_and_return_to_inbox(driver)
            continue

        try:
            wait_for_inbox(driver, timeout=300)
        except TimeoutException as exc:
            raise SystemExit(
                "Nach 'sent' wurde die Inbox nicht wieder erreicht. "
                "Bitte pruefen, ob die Nachricht wirklich gesendet wurde und ob Roundcube zur Uebersicht zurueckgekehrt ist."
            ) from exc

    print("Alle Kontakte wurden vorbereitet.")


if __name__ == "__main__":
    main()
