import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright
from telethon import TelegramClient
from telethon.sessions import StringSession


# ============================================================
# CONFIG
# ============================================================

UKRCREWING_EMAIL = os.getenv("UKRCREWING_EMAIL")
UKRCREWING_PASSWORD = os.getenv("UKRCREWING_PASSWORD")

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_SESSION = os.getenv("TELEGRAM_SESSION")

TELEGRAM_TARGET = "@fwd19472"

UKRCREWING_LOGIN_URL = "https://ukrcrewing.com.ua/en/login"

UKRCREWING_VACANCY_URL = (
    "https://ukrcrewing.com.ua/vacancy/"
    "?v_sort=1&v_sort_dir=1"
)

SENT_FILE = Path("/app/sent_jobs.json")


# ------------------------------------------------------------
# FIRST RUN
# ------------------------------------------------------------
#
# True  = immediately scan today's vacancies once.
# False = only use the schedule.
#
# Keep True now.
# After the first successful deployment it can stay True:
# the memory will prevent duplicates.
# ------------------------------------------------------------

RUN_SCAN_IMMEDIATELY = True


# ------------------------------------------------------------
# SCHEDULE
# ------------------------------------------------------------

SCHEDULE = [
    (9, 40),
    (11, 15),
    (13, 25),
    (15, 30),
    (16, 45),
]


# ============================================================
# FREE EMAIL DOMAINS
# ============================================================

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",

    "mail.ru",
    "bk.ru",
    "inbox.ru",
    "list.ru",
    "rambler.ru",

    "yandex.ru",
    "yandex.com",
    "ya.ru",

    "outlook.com",
    "outlook.co.uk",
    "hotmail.com",
    "hotmail.co.uk",
    "live.com",
    "live.co.uk",
    "msn.com",

    "icloud.com",
    "me.com",
    "mac.com",

    "proton.me",
    "protonmail.com",

    "yahoo.com",
    "yahoo.co.uk",
    "aol.com",

    "ukr.net",
}


telegram_client = None


# ============================================================
# LOG
# ============================================================

def log(message=""):
    print(message, flush=True)


# ============================================================
# TIME
# ============================================================

def london_now():

    try:

        from zoneinfo import ZoneInfo

        return datetime.now(
            ZoneInfo("Europe/London")
        )

    except Exception:

        return datetime.now()


def today_string():

    return london_now().strftime("%d.%m.%Y")


# ============================================================
# HELPERS
# ============================================================

def normalize_space(text):

    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def normalize_date(value):

    if not value:
        return None

    value = normalize_space(value)

    # 30.09.2026
    m = re.search(
        r"\b(\d{2})\.(\d{2})\.(\d{4})\b",
        value
    )

    if m:

        return (
            f"{m.group(1)}."
            f"{m.group(2)}."
            f"{m.group(3)}"
        )

    # 30.09.26
    m = re.search(
        r"\b(\d{2})\.(\d{2})\.(\d{2})\b",
        value
    )

    if m:

        return (
            f"{m.group(1)}."
            f"{m.group(2)}."
            f"20{m.group(3)}"
        )

    return None


def first_match(patterns, text):

    for pattern in patterns:

        m = re.search(
            pattern,
            text or "",
            re.I | re.M
        )

        if m:

            value = normalize_space(
                m.group(1)
            )

            if value:
                return value

    return None


# ============================================================
# ENVIRONMENT
# ============================================================

def check_environment():

    log("=" * 70)
    log("=== CHECKING ENVIRONMENT ===")
    log("=" * 70)

    log(
        f"UKRCREWING_EMAIL set: "
        f"{bool(UKRCREWING_EMAIL)}"
    )

    log(
        f"UKRCREWING_PASSWORD set: "
        f"{bool(UKRCREWING_PASSWORD)}"
    )

    log(
        f"TELEGRAM_API_ID set: "
        f"{bool(TELEGRAM_API_ID)}"
    )

    log(
        f"TELEGRAM_API_HASH set: "
        f"{bool(TELEGRAM_API_HASH)}"
    )

    log(
        f"TELEGRAM_SESSION set: "
        f"{bool(TELEGRAM_SESSION)}"
    )

    missing = []

    if not UKRCREWING_EMAIL:
        missing.append("UKRCREWING_EMAIL")

    if not UKRCREWING_PASSWORD:
        missing.append("UKRCREWING_PASSWORD")

    if not TELEGRAM_API_ID:
        missing.append("TELEGRAM_API_ID")

    if not TELEGRAM_API_HASH:
        missing.append("TELEGRAM_API_HASH")

    if not TELEGRAM_SESSION:
        missing.append("TELEGRAM_SESSION")

    if missing:

        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
        )

    log("All required environment variables are present.")

    log(
        f"Telegram target: {TELEGRAM_TARGET}"
    )

    log(
        f"Today's date: {today_string()}"
    )


# ============================================================
# MEMORY
# ============================================================

def load_memory():

    if not SENT_FILE.exists():

        log(
            "No sent_jobs.json found. "
            "Starting with empty memory."
        )

        return set()

    try:

        data = json.loads(
            SENT_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, list):

            return {
                str(x)
                for x in data
            }

        if isinstance(data, dict):

            return {
                str(x)
                for x in data.get(
                    "sent",
                    []
                )
            }

    except Exception as e:

        log(
            f"WARNING: Could not read memory: {e}"
        )

    return set()


def save_memory(sent_jobs):

    try:

        SENT_FILE.write_text(
            json.dumps(
                sorted(
                    sent_jobs,
                    key=str
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    except Exception as e:

        log(
            f"WARNING: Could not save memory: {e}"
        )


# ============================================================
# TELEGRAM
# ============================================================

async def connect_telegram():

    global telegram_client

    log("")
    log("=== CONNECTING TELEGRAM ===")

    api_id = int(
        TELEGRAM_API_ID
    )

    telegram_client = TelegramClient(
        StringSession(
            TELEGRAM_SESSION
        ),
        api_id,
        TELEGRAM_API_HASH,
    )

    try:

        await telegram_client.connect()

    except Exception as e:

        log(
            f"❌ Telegram connection error: "
            f"{type(e).__name__}: {e}"
        )

        raise RuntimeError(
            "Could not connect to Telegram "
            "using TELEGRAM_SESSION."
        )

    if not telegram_client.is_connected():

        raise RuntimeError(
            "Telegram client is not connected."
        )

    authorized = (
        await telegram_client.is_user_authorized()
    )

    log(
        f"Telegram authorized: {authorized}"
    )

    if not authorized:

        raise RuntimeError(
            "TELEGRAM_SESSION is not authorized."
        )

    me = await telegram_client.get_me()

    log(
        "Telegram account: "
        f"{getattr(me, 'username', None) or ''} "
        f"{getattr(me, 'first_name', '')}"
    )

    log(
        "Telegram connection successful."
    )


async def send_telegram(message):

    global telegram_client

    if telegram_client is None:

        raise RuntimeError(
            "Telegram client is not initialized."
        )

    if not telegram_client.is_connected():

        log(
            "Telegram disconnected. Reconnecting..."
        )

        await telegram_client.connect()

    if not await telegram_client.is_user_authorized():

        raise RuntimeError(
            "Telegram session is not authorized."
        )

    await telegram_client.send_message(
        TELEGRAM_TARGET,
        message,
        link_preview=False,
    )

    log(
        "✅ Telegram message sent."
    )


# ============================================================
# EMAIL
# ============================================================

def extract_emails(text):

    emails = re.findall(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        text or "",
        re.I,
    )

    result = []

    for email in emails:

        email = email.lower().strip(
            ".,;:()[]<>\"'"
        )

        if email not in result:

            result.append(email)

    return result


def valid_employer_email(email):

    if not email:
        return False

    email = email.lower().strip()

    if "@" not in email:
        return False

    domain = email.split(
        "@",
        1
    )[1]

    if domain in FREE_EMAIL_DOMAINS:
        return False

    return True


def get_employer_email(text):

    for email in extract_emails(text):

        if valid_employer_email(email):

            return email

    return None


# ============================================================
# CLEAN TEXT
# ============================================================

REMOVE_PHRASES = [
    "пишите нам",
    "морякам",
    "компаниям",
    "создать резюме",
    "поднять резюме в топ",
    "разослать резюме",
    "подписаться на вакансии",
    "скачать базу компаний",
    "войти",
    "выход",
    "регистрация",
    "forgot your password",
    "login",
    "sign in",
    "register",
]


def clean_info(text):

    if not text:
        return ""

    text = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        text,
        flags=re.I,
    )

    lines = []

    for raw in text.splitlines():

        line = normalize_space(raw)

        if not line:
            continue

        low = line.lower()

        if any(
            phrase in low
            for phrase in REMOVE_PHRASES
        ):
            continue

        if line in lines:
            continue

        lines.append(line)

    return "\n".join(lines)


# ============================================================
# PARSING DETAIL PAGE
# ============================================================

def extract_title(text):

    patterns = [
        r"Вакансия\s+(.+?)(?:\n|$)",
        r"Vacancy\s+(.+?)(?:\n|$)",
    ]

    return first_match(
        patterns,
        text
    )


def extract_rank(text):

    value = first_match(
        [
            r"Должность\s*[:\-]\s*([^\n]+)",
            r"Position\s*[:\-]\s*([^\n]+)",
        ],
        text
    )

    if value:
        return value

    ranks = [
        "Chief Engineer",
        "Chief Officer",
        "2nd Engineer",
        "3rd Engineer",
        "4th Engineer",
        "2nd Officer",
        "3rd Officer",
        "Master",
        "ETO",
        "Electrician",
        "Bosun",
        "Boatswain",
        "Able Seaman",
        "Ordinary Seaman",
        "OS",
        "Fitter",
        "Crane Operator",
        "Cook",
        "Mess Boy",
        "DPO",
        "JDPO",
        "Deck Cadet",
        "Engine Cadet",
    ]

    low = text.lower()

    for rank in ranks:

        if re.search(
            r"\b"
            + re.escape(rank.lower())
            + r"\b",
            low
        ):

            return rank

    return "Multiple positions"


def extract_vessel_type(text):

    value = first_match(
        [
            r"Тип судна\s*[:\-]\s*([^\n]+)",
            r"Vessel type\s*[:\-]\s*([^\n]+)",
        ],
        text
    )

    if value:
        return value

    types = [
        "Bulk Carrier",
        "Container",
        "Container Ship",
        "Tanker",
        "Oil Tanker",
        "Chemical Tanker",
        "Oil Chemical Tanker",
        "LNG Tanker",
        "LPG Tanker",
        "General Cargo",
        "Heavy Lift Vessel",
        "Ro-Ro",
        "Offshore Supply Vessel",
        "OSV",
        "AHTS",
        "PSV",
        "Diving Support Vessel",
        "DSV",
        "ERRV",
        "FPSO",
        "FSO",
        "Drilling Vessel",
        "Research Vessel",
        "Survey Vessel",
        "Cruise Vessel",
        "Cruise Ship",
        "Dredger",
        "Coaster",
        "Motor Yacht",
        "Passenger Vessel",
        "Multi-Purpose Vessel",
    ]

    low = text.lower()

    for vessel_type in types:

        if vessel_type.lower() in low:

            return vessel_type

    return None


def extract_vessel_name(text):

    return first_match(
        [
            r"Название судна\s*[:\-]\s*([^\n]+)",
            r"Vessel name\s*[:\-]\s*([^\n]+)",
            r"Ship name\s*[:\-]\s*([^\n]+)",
        ],
        text
    )


def extract_region(text):

    return first_match(
        [
            r"Регион работы\s*[:\-]\s*([^\n]+)",
            r"Region\s*[:\-]\s*([^\n]+)",
            r"Trading area\s*[:\-]\s*([^\n]+)",
        ],
        text
    )


def extract_date(text):

    return first_match(
        [
            r"Дата посадки на борт\s*[:\-]\s*([^\n]+)",
            r"Joining date\s*[:\-]\s*([^\n]+)",
            r"Joining\s*[:\-]\s*([^\n]+)",
        ],
        text
    )


def extract_duration(text):

    return first_match(
        [
            r"Длительность рейса\s*[:\-]\s*([^\n]+)",
            r"Voyage duration\s*[:\-]\s*([^\n]+)",
            r"Contract duration\s*[:\-]\s*([^\n]+)",
            r"Duration\s*[:\-]\s*([^\n]+)",
        ],
        text
    )


def extract_salary(text):

    value = first_match(
        [
            r"Зарплата\s*[:\-]\s*([^\n]+)",
            r"Salary\s*[:\-]\s*([^\n]+)",
            r"Wage\s*[:\-]\s*([^\n]+)",
            r"Pay\s*[:\-]\s*([^\n]+)",
        ],
        text
    )

    if value:
        return value

    match = re.search(
        r"(?:EUR|USD|GBP|€|\$|£)\s?"
        r"\d[\d\s,.]*(?:\s*-\s*"
        r"(?:EUR|USD|GBP|€|\$|£)?\s?"
        r"\d[\d\s,.]*)?",
        text or "",
        re.I
    )

    if match:

        return normalize_space(
            match.group(0)
        )

    return None


def extract_published_date(text):

    patterns = [
        r"Опубликована\s*:\s*(\d{2}\.\d{2}\.\d{4})",
        r"Опубликовано\s*:\s*(\d{2}\.\d{2}\.\d{4})",
        r"Vacancy posted\s*[:\-]?\s*(\d{2}\.\d{2}\.\d{2,4})",
        r"Posted\s*[:\-]?\s*(\d{2}\.\d{2}\.\d{2,4})",
    ]

    value = first_match(
        patterns,
        text
    )

    return normalize_date(value)


def extract_phone(text):

    patterns = [
        r"Телефон для отклика на вакансию\s*[:\-]\s*([^\n]+)",
        r"Phone\s*[:\-]\s*([^\n]+)",
        r"Contact phone\s*[:\-]\s*([^\n]+)",
    ]

    return first_match(
        patterns,
        text
    )


def extract_agency(text):

    return first_match(
        [
            r"Крюинг\s*:\s*([^\n]+)",
            r"Crewing\s*:\s*([^\n]+)",
            r"Agency\s*:\s*([^\n]+)",
        ],
        text
    )


def extract_additional_info(text):

    markers = [
        "Дополнительная информация:",
        "Additional information:",
        "Additional Information:",
    ]

    for marker in markers:

        pos = text.lower().find(
            marker.lower()
        )

        if pos >= 0:

            part = text[
                pos + len(marker):
            ]

            stop_markers = [
                "Телефон для отклика",
                "Контактный е-мейл",
                "Contact email",
                "Phone",
                "Крюинг:",
                "Crewing:",
                "Agency:",
            ]

            for stop in stop_markers:

                idx = part.lower().find(
                    stop.lower()
                )

                if idx >= 0:

                    part = part[:idx]

            return clean_info(
                part
            )[:1200]

    return ""


# ============================================================
# JOB MESSAGE
# ============================================================

def make_message(job):

    lines = []

    lines.append("🇺🇦 UkrCrewing")
    lines.append("")

    lines.append(
        f"⚓ Rank: {job['rank']}"
    )

    if job.get("vessel_name"):

        lines.append(
            f"🚢 Vessel name: "
            f"{job['vessel_name']}"
        )

    if job.get("vessel_type"):

        lines.append(
            f"🚢 Vessel type: "
            f"{job['vessel_type']}"
        )

    if job.get("region"):

        lines.append(
            f"🌍 Region: "
            f"{job['region']}"
        )

    if job.get("date"):

        lines.append(
            f"📅 Date: "
            f"{job['date']}"
        )

    if job.get("duration"):

        lines.append(
            f"⏱️ Duration: "
            f"{job['duration']}"
        )

    if job.get("salary"):

        lines.append(
            f"💰 Salary: "
            f"{job['salary']}"
        )

    if job.get("info"):

        lines.append(
            f"ℹ️ {job['info']}"
        )

    lines.append(
        f"📩 Contact: "
        f"{job['email']}"
    )

    hashtags = []

    if job["rank"] != "Multiple positions":

        tag = re.sub(
            r"[^A-Za-z0-9]",
            "",
            job["rank"]
        )

        if tag:
            hashtags.append(
                "#" + tag
            )

    if job.get("vessel_type"):

        tag = re.sub(
            r"[^A-Za-z0-9]",
            "",
            job["vessel_type"]
        )

        if tag:
            hashtags.append(
                "#" + tag
            )

    hashtags.append(
        "#MerchantFleet"
    )

    hashtags = list(
        dict.fromkeys(
            hashtags
        )
    )

    lines.append(
        " ".join(hashtags)
    )

    return "\n".join(lines)


# ============================================================
# LOGIN
# ============================================================

async def is_login_page(page):

    url = page.url.lower()

    if "/login" in url:
        return True

    if "/signin" in url:
        return True

    try:

        return (
            await page.locator(
                'input[type="password"]'
            ).count()
            > 0
        )

    except Exception:

        return False


async def login_to_ukrcrewing(page):

    log("")
    log("=" * 70)
    log("=== UKR CREWING LOGIN ===")
    log("=" * 70)

    await page.goto(
        UKRCREWING_LOGIN_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(
        2000
    )

    log(
        f"Login URL: {page.url}"
    )

    email = None

    selectors = [
        'input[name="email"]',
        'input[type="email"]',
        'input[name="username"]',
        'input[placeholder*="email" i]',
        'input[placeholder*="e-mail" i]',
    ]

    for selector in selectors:

        loc = page.locator(
            selector
        ).first

        try:

            if (
                await loc.count() > 0
                and await loc.is_visible()
            ):

                email = loc

                log(
                    f"Email field found: "
                    f"{selector}"
                )

                break

        except Exception:
            pass

    if email is None:

        raise RuntimeError(
            "UKR Crewing email field "
            "not found."
        )

    password = page.locator(
        'input[type="password"]'
    ).first

    if await password.count() == 0:

        raise RuntimeError(
            "UKR Crewing password field "
            "not found."
        )

    await email.fill(
        UKRCREWING_EMAIL
    )

    await password.fill(
        UKRCREWING_PASSWORD
    )

    log(
        "Credentials filled."
    )

    submit = None

    selectors = [
        'input[type="submit"]',
        'button[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Log in")',
        'button:has-text("Sign in")',
    ]

    for selector in selectors:

        loc = page.locator(
            selector
        ).first

        try:

            if (
                await loc.count() > 0
                and await loc.is_visible()
            ):

                submit = loc

                log(
                    f"Login button found: "
                    f"{selector}"
                )

                break

        except Exception:
            pass

    if submit:

        await submit.click()

    else:

        await password.press(
            "Enter"
        )

    await page.wait_for_timeout(
        4000
    )

    log(
        f"URL after login: {page.url}"
    )

    if await is_login_page(page):

        body = await page.locator(
            "body"
        ).inner_text()

        log(
            "❌ Still on login page."
        )

        log(
            body[:1500]
        )

        raise RuntimeError(
            "UKR Crewing login failed."
        )

    log(
        "✅ UKR CREWING LOGIN SUCCESS"
    )


# ============================================================
# OPEN VACANCY LIST
# ============================================================

async def open_vacancy_page(page):

    log("")
    log(
        "=== OPENING UKR CREWING VACANCIES ==="
    )

    await page.goto(
        UKRCREWING_VACANCY_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(
        2000
    )

    if await is_login_page(page):

        log(
            "Redirected to login."
        )

        await login_to_ukrcrewing(
            page
        )

        await page.goto(
            UKRCREWING_VACANCY_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await page.wait_for_timeout(
            2000
        )

    if await is_login_page(page):

        raise RuntimeError(
            "Could not authenticate "
            "to UKR Crewing."
        )

    log(
        f"Vacancy page URL: {page.url}"
    )

    log(
        "Vacancy page loaded."
    )


# ============================================================
# GET VACANCY LINKS FROM PAGE
# ============================================================

VACANCY_ID_RE = re.compile(
    r"/vacancy/(\d+)"
)


async def get_vacancy_links(page):

    links = {}

    anchors = page.locator(
        "a[href]"
    )

    count = await anchors.count()

    for i in range(count):

        try:

            href = await anchors.nth(
                i
            ).get_attribute(
                "href"
            )

            if not href:
                continue

            match = VACANCY_ID_RE.search(
                href
            )

            if not match:
                continue

            vacancy_id = match.group(
                1
            )

            full_url = urljoin(
                "https://ukrcrewing.com.ua",
                href
            )

            if "/login" in full_url:
                continue

            links[
                vacancy_id
            ] = full_url

        except Exception:
            continue

    return links


# ============================================================
# PARSE DATE FROM LIST PAGE
# ============================================================

async def get_page_text(page):

    try:

        return await page.locator(
            "body"
        ).inner_text()

    except Exception:

        return ""


def page_contains_today_vacancies(text):

    today = today_string()

    # Full date
    if today in text:
        return True

    # Short website format: 30.09.26
    short_today = london_now().strftime(
        "%d.%m.%y"
    )

    if short_today in text:
        return True

    return False


def page_contains_older_dates(text):

    # This is only a helper.
    # Actual job dates are verified
    # on each detail page.
    return False


# ============================================================
# PAGINATION
# ============================================================

async def get_next_page_url(page):

    anchors = page.locator(
        "a[href]"
    )

    count = await anchors.count()

    current_url = page.url

    current_match = re.search(
        r"/vacancy/p(\d+)",
        current_url
    )

    current_page = (
        int(current_match.group(1))
        if current_match
        else 0
    )

    expected_page = (
        current_page + 1
    )

    possible_urls = []

    for i in range(count):

        try:

            href = await anchors.nth(
                i
            ).get_attribute(
                "href"
            )

            if not href:
                continue

            full_url = urljoin(
                "https://ukrcrewing.com.ua",
                href
            )

            match = re.search(
                r"/vacancy/p(\d+)",
                full_url
            )

            if not match:
                continue

            page_number = int(
                match.group(1)
            )

            if page_number == expected_page:

                possible_urls.append(
                    full_url
                )

        except Exception:
            continue

    if possible_urls:

        return possible_urls[0]

    # Fallback: build URL ourselves
    return (
        f"https://ukrcrewing.com.ua"
        f"/vacancy/p{expected_page}/"
        f"?v_sort=1&v_sort_dir=1"
    )


async def collect_today_links(page):

    log("")
    log("=" * 70)
    log("=== COLLECTING TODAY'S VACANCIES ===")
    log("=" * 70)

    all_links = {}

    visited_pages = set()

    page_number = 0

    while True:

        current_url = page.url

        if current_url in visited_pages:
            break

        visited_pages.add(
            current_url
        )

        log("")
        log(
            f"Scanning vacancy page "
            f"{page_number}: "
            f"{current_url}"
        )

        page_text = await get_page_text(
            page
        )

        # If today's date isn't on the page,
        # there is no reason to continue.
        if (
            page_number > 0
            and not page_contains_today_vacancies(
                page_text
            )
        ):

            log(
                "No today's date detected "
                "on this page."
            )

            log(
                "Stopping pagination."
            )

            break

        links = await get_vacancy_links(
            page
        )

        log(
            f"Found {len(links)} "
            f"vacancy links on page."
        )

        for vacancy_id, url in links.items():

            all_links[
                vacancy_id
            ] = url

        next_url = await get_next_page_url(
            page
        )

        if not next_url:
            break

        if next_url in visited_pages:
            break

        # Safety limit
        if page_number >= 100:
            log(
                "Pagination safety limit reached."
            )
            break

        page_number += 1

        try:

            await page.goto(
                next_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(
                1200
            )

        except Exception as e:

            log(
                f"Could not open next page: {e}"
            )

            break

    log("")
    log(
        f"Total vacancy links collected: "
        f"{len(all_links)}"
    )

    return all_links


# ============================================================
# READ VACANCY DETAIL
# ============================================================

async def read_vacancy(
    page,
    vacancy_id,
    url,
):

    log(
        f"Opening vacancy {vacancy_id}"
    )

    try:

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await page.wait_for_timeout(
            800
        )

    except Exception as e:

        log(
            f"Could not open "
            f"{vacancy_id}: {e}"
        )

        return None

    if await is_login_page(page):

        log(
            f"{vacancy_id}: "
            "redirected to login."
        )

        return None

    try:

        text = await page.locator(
            "body"
        ).inner_text()

    except Exception as e:

        log(
            f"Could not read "
            f"{vacancy_id}: {e}"
        )

        return None

    text = text.strip()

    if not text:

        return None

    published_date = (
        extract_published_date(
            text
        )
    )

    today = today_string()

    if published_date != today:

        # Also accept short format comparison
        short_today = london_now().strftime(
            "%d.%m.%y"
        )

        if published_date != short_today:

            log(
                f"Skipping {vacancy_id}: "
                f"published {published_date}, "
                f"today {today}"
            )

            return None

    email = get_employer_email(
        text
    )

    if not email:

        log(
            f"Skipping {vacancy_id}: "
            "no valid employer email."
        )

        return None

    job = {
        "id": vacancy_id,
        "url": url,
        "title": extract_title(text),
        "email": email,
        "rank": extract_rank(text),
        "vessel_name": extract_vessel_name(text),
        "vessel_type": extract_vessel_type(text),
        "region": extract_region(text),
        "date": extract_date(text),
        "duration": extract_duration(text),
        "salary": extract_salary(text),
        "published_date": published_date,
        "phone": extract_phone(text),
        "agency": extract_agency(text),
        "info": extract_additional_info(text),
    }

    return job


# ============================================================
# SCAN
# ============================================================

async def scan(sent_jobs):

    log("")
    log("=" * 70)
    log("=== UKR CREWING SCAN STARTED ===")
    log(
        london_now().strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
    )
    log("=" * 70)

    async with async_playwright() as playwright:

        log(
            "Launching Chromium..."
        )

        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        context = await browser.new_context(
            viewport={
                "width": 1440,
                "height": 1000,
            }
        )

        page = await context.new_page()

        try:

            await open_vacancy_page(
                page
            )

            links = await collect_today_links(
                page
            )

            if not links:

                log(
                    "No vacancy links found."
                )

                return

            log("")
            log(
                f"Today's candidate links: "
                f"{len(links)}"
            )

            job_page = await context.new_page()

            sent_count = 0

            for vacancy_id, url in links.items():

                if vacancy_id in sent_jobs:

                    log(
                        f"Already sent: "
                        f"{vacancy_id}"
                    )

                    continue

                job = await read_vacancy(
                    job_page,
                    vacancy_id,
                    url,
                )

                if not job:
                    continue

                message = make_message(
                    job
                )

                log("")
                log(
                    "--- TELEGRAM MESSAGE ---"
                )
                log(message)
                log(
                    "--- END MESSAGE ---"
                )

                try:

                    await send_telegram(
                        message
                    )

                    sent_jobs.add(
                        vacancy_id
                    )

                    save_memory(
                        sent_jobs
                    )

                    sent_count += 1

                    log(
                        f"💾 Saved vacancy "
                        f"{vacancy_id}"
                    )

                except Exception as e:

                    log(
                        f"❌ Telegram error "
                        f"for {vacancy_id}: "
                        f"{type(e).__name__}: {e}"
                    )

            await job_page.close()

            log("")
            log(
                f"=== SCAN FINISHED ==="
            )

            log(
                f"New vacancies sent: "
                f"{sent_count}"
            )

            log(
                f"Memory contains: "
                f"{len(sent_jobs)} IDs"
            )

        finally:

            await context.close()
            await browser.close()

            log(
                "Chromium closed."
            )


# ============================================================
# SCHEDULER
# ============================================================

def next_scan():

    now = london_now()

    for hour, minute in SCHEDULE:

        candidate = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

        if candidate > now:

            return candidate

    tomorrow = now + timedelta(
        days=1
    )

    return tomorrow.replace(
        hour=SCHEDULE[0][0],
        minute=SCHEDULE[0][1],
        second=0,
        microsecond=0,
    )


async def scheduler(sent_jobs):

    log("")
    log("=" * 70)
    log("=== UKR CREWING SCHEDULER STARTED ===")
    log("=" * 70)

    log(
        "Schedule:"
    )

    for hour, minute in SCHEDULE:

        log(
            f"  - {hour:02d}:{minute:02d}"
        )

    log(
        "Timezone: Europe/London"
    )

    log(
        f"Memory contains "
        f"{len(sent_jobs)} vacancy IDs."
    )

    while True:

        target = next_scan()

        now = london_now()

        seconds = max(
            1,
            int(
                (
                    target - now
                ).total_seconds()
            ),
        )

        log("")
        log(
            f"Next scan: "
            f"{target.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )

        log(
            f"Sleeping {seconds} seconds."
        )

        await asyncio.sleep(
            seconds
        )

        try:

            await scan(
                sent_jobs
            )

        except Exception as e:

            log(
                f"🔥 SCAN ERROR: "
                f"{type(e).__name__}: {e}"
            )

            await asyncio.sleep(
                5
            )


# ============================================================
# MAIN
# ============================================================

async def main():

    log("")
    log("=" * 70)
    log("=== UKR CREWING TELEGRAM BOT STARTED ===")
    log("=" * 70)

    log(
        "📂 Source: UkrCrewing"
    )

    log(
        "📨 Telegram: "
        f"{TELEGRAM_TARGET}"
    )

    log(
        "🕘 Schedule: "
        "09:40, 11:15, 13:25, 15:30, 16:45"
    )

    log(
        "🌍 Timezone: Europe/London"
    )

    log(
        f"📅 Today: {today_string()}"
    )

    check_environment()

    # --------------------------------------------------------
    # MEMORY
    # --------------------------------------------------------

    sent_jobs = load_memory()

    log("")
    log(
        f"💾 Loaded sent IDs: "
        f"{len(sent_jobs)}"
    )

    if sent_jobs:

        log(
            "Previously sent IDs:"
        )

        log(
            str(
                sorted(
                    sent_jobs,
                    key=str
                )
            )
        )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    await connect_telegram()

    log(
        "Telegram initialization complete."
    )

    # --------------------------------------------------------
    # IMMEDIATE FIRST SCAN
    # --------------------------------------------------------

    if RUN_SCAN_IMMEDIATELY:

        log("")
        log("=" * 70)
        log("=== IMMEDIATE TODAY SCAN ===")
        log("=" * 70)

        try:

            await scan(
                sent_jobs
            )

            log(
                "=== IMMEDIATE SCAN FINISHED ==="
            )

            log(
                f"Memory now contains "
                f"{len(sent_jobs)} IDs."
            )

        except Exception as e:

            log(
                f"🔥 IMMEDIATE SCAN ERROR: "
                f"{type(e).__name__}: {e}"
            )

    # --------------------------------------------------------
    # NORMAL SCHEDULE
    # --------------------------------------------------------

    await scheduler(
        sent_jobs
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    log(
        "=== EXECUTING asyncio.run(main()) ==="
    )

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        log(
            "UKR Crewing bot stopped."
        )

    except Exception as e:

        log(
            f"🔥 FATAL ERROR: "
            f"{type(e).__name__}: {e}"
        )

        raise
