import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
import urllib.error
import urllib.request

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

# Сайт Way At Sea: куда отправлять вакансии (если не задано — отправка на сайт отключена)
SITE_IMPORT_URL = os.getenv("SITE_IMPORT_URL")        # https://www.wayatsea.com/api/import/vacancies
SITE_IMPORT_TOKEN = os.getenv("SITE_IMPORT_TOKEN")    # тот же ключ, что IMPORT_TOKEN на сайте

# Разовый запуск сразу после старта (для проверки): RUN_ON_START=1, SCAN_LIMIT=3
RUN_ON_START = os.getenv("RUN_ON_START", "").lower() in ("1", "true", "yes")
SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "0") or 0)

# Сколько дней назад вакансия ещё считается свежей (1 = только сегодняшние, как раньше)
ACCEPT_DAYS = max(1, int(os.getenv("ACCEPT_DAYS", "1") or 1))

UKRCREWING_BASE = "https://ukrcrewing.com.ua"

UKRCREWING_URL = (
    "https://ukrcrewing.com.ua/vacancy/"
    "?v_sort=1&v_sort_dir=1"
)

SENT_FILE = Path("/app/sent_jobs.json")


# ============================================================
# SCHEDULE
# ============================================================

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

    "proton.me",
    "protonmail.com",

    "yahoo.com",
    "yahoo.co.uk",

    "aol.com",

    "rambler.ru",

    "ukr.net",
}


# ============================================================
# TELEGRAM
# ============================================================

telegram_client = None


# ============================================================
# LOG
# ============================================================

def log(message=""):
    print(message, flush=True)


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_space(text):
    return re.sub(r"\s+", " ", text or "").strip()


def clean_value(value):

    if not value:
        return None

    value = normalize_space(value)

    value = value.strip(
        " \t\r\n:;-–—"
    )

    if not value:
        return None

    return value


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

    log(
        f"Site export enabled: "
        f"{bool(SITE_IMPORT_URL and SITE_IMPORT_TOKEN)}"
    )

    log("All required environment variables are present.")

    log(
        f"Telegram target: {TELEGRAM_TARGET}"
    )

    log(
        f"Schedule: {SCHEDULE}"
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

            result = {
                str(x)
                for x in data
            }

        elif isinstance(data, dict):

            result = {
                str(x)
                for x in data.get(
                    "sent",
                    []
                )
            }

        else:

            result = set()

        log(
            f"Loaded sent IDs: {len(result)}"
        )

        if result:

            log(
                "Previously sent IDs:"
            )

            log(
                str(
                    sorted(
                        result
                    )
                )
            )

        return result

    except Exception as e:

        log(
            f"WARNING: Could not read memory: {e}"
        )

        return set()


def save_memory(sent_jobs):

    try:

        SENT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        SENT_FILE.write_text(
            json.dumps(
                sorted(
                    sent_jobs
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        log(
            f"Memory saved: {len(sent_jobs)} IDs."
        )

    except Exception as e:

        log(
            f"WARNING: Could not save memory: {e}"
        )


# ============================================================
# LONDON TIME
# ============================================================

def london_now():

    try:

        from zoneinfo import ZoneInfo

        return datetime.now(
            ZoneInfo("Europe/London")
        )

    except Exception:

        return datetime.now()


def today_date_string():

    return london_now().strftime(
        "%d.%m.%Y"
    )


# ============================================================
# TELEGRAM
# ============================================================

async def connect_telegram():

    global telegram_client

    log("")
    log("📡 Connecting to Telegram...")

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

        log(
            "🔌 Telegram client connected."
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
            f"ID={getattr(me, 'id', None)}"
        )

        log(
            "✅ Telegram connection successful."
        )

    except Exception as e:

        log(
            f"❌ Telegram connection error: "
            f"{type(e).__name__}: {e}"
        )

        raise RuntimeError(
            "Could not connect to Telegram "
            "using the existing SESSION_STRING."
        )


async def send_telegram(message):

    global telegram_client

    if telegram_client is None:

        raise RuntimeError(
            "Telegram client is not initialized."
        )

    if not telegram_client.is_connected():

        log(
            "🔌 Telegram client disconnected. "
            "Connecting..."
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
# EMAIL VALIDATION
# ============================================================

EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.I,
)


def valid_employer_email(email):

    if not email:
        return False

    email = email.lower().strip()

    if "@" not in email:
        return False

    domain = email.split(
        "@",
        1
    )[1].lower()

    # Never use UkrCrewing itself
    if domain == "ukrcrewing.com.ua":
        return False

    if domain.endswith(
        ".ukrcrewing.com.ua"
    ):
        return False

    # Never use free email providers
    if domain in FREE_EMAIL_DOMAINS:
        return False

    return True


# ============================================================
# CONTACT EMAIL
# ============================================================

def extract_contact_email(text):

    """
    Search ONLY around the vacancy's
    'Контактный е-мейл' field.

    We do NOT search the whole page for email addresses.
    """

    if not text:
        return None

    patterns = [

        r"Контактный\s+е-мейл\s*:\s*"
        r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",

        r"Контактний\s+е-мейл\s*:\s*"
        r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",

        r"Contact\s+e-?mail\s*:\s*"
        r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",

        r"Е-?mail\s*:\s*"
        r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if not match:
            continue

        email = (
            match.group(1)
            .lower()
            .strip(
                ".,;:()[]<>\"'"
            )
        )

        if valid_employer_email(email):

            log(
                f"📧 Corporate contact email found: "
                f"{email}"
            )

            return email

        log(
            f"🚫 Contact email rejected: "
            f"{email}"
        )

        return None

    log(
        "🚫 No contact email found in vacancy."
    )

    return None


# ============================================================
# DATE EXTRACTION
# ============================================================

def extract_publication_date(text):

    patterns = [

        r"Опубликована\s*:\s*"
        r"(\d{2}\.\d{2}\.\d{4})",

        r"Опубликовано\s*:\s*"
        r"(\d{2}\.\d{2}\.\d{4})",

        r"Published\s*:\s*"
        r"(\d{2}\.\d{2}\.\d{4})",

        r"Published\s+on\s*:\s*"
        r"(\d{2}\.\d{2}\.\d{4})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text or "",
            re.I,
        )

        if match:

            return match.group(1)

    return None


def allowed_dates():

    now = london_now()

    return {
        (now - timedelta(days=i)).strftime("%d.%m.%Y")
        for i in range(ACCEPT_DAYS)
    }


def is_today(publication_date):

    if not publication_date:
        return False

    return publication_date == today_date_string()


# ============================================================
# GENERIC FIELD EXTRACTION
# ============================================================

def extract_field(
    text,
    labels,
):

    for label in labels:

        pattern = (
            re.escape(label)
            + r"\s*:\s*([^\n]+)"
        )

        match = re.search(
            pattern,
            text or "",
            re.I,
        )

        if match:

            value = clean_value(
                match.group(1)
            )

            if value:
                return value

    return None


# ============================================================
# VACANCY TITLE
# ============================================================

def extract_vacancy_title(text):

    patterns = [

        r"Вакансия\s+(.+?)(?:\n|$)",

        r"Vacancy\s+(.+?)(?:\n|$)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text or "",
            re.I,
        )

        if match:

            value = clean_value(
                match.group(1)
            )

            if value:
                return value

    return None


# ============================================================
# RANK
# ============================================================

def extract_rank(text):

    title = extract_vacancy_title(
        text
    )

    if title:

        title_lower = title.lower()

        ranks = [
            "Chief Officer",
            "Chief Mate",
            "Master",
            "1st Officer",
            "2nd Officer",
            "3rd Officer",
            "Chief Engineer",
            "1st Engineer",
            "2nd Engineer",
            "3rd Engineer",
            "4th Engineer",
            "ETO",
            "Electrician",
            "Boatswain",
            "Bosun",
            "Able Seaman",
            "AB",
            "Ordinary Seaman",
            "OS",
            "Motorman",
            "Oiler",
            "Fitter",
            "Crane Operator",
            "Cook",
            "Chief Cook",
            "Messman",
            "Steward",
            "Deck Cadet",
            "Engine Cadet",
            "DPO",
            "JDPO",
        ]

        for rank in ranks:

            if re.search(
                r"\b"
                + re.escape(
                    rank.lower()
                )
                + r"\b",
                title_lower,
            ):

                return rank

    return "Multiple positions"


# ============================================================
# VESSEL TYPE
# ============================================================

def extract_vessel_type(text):

    value = extract_field(
        text,
        [
            "Тип судна",
            "Vessel type",
            "Ship type",
        ],
    )

    if value:

        return value[:100]

    types = [
        "Bulk Carrier",
        "Container Ship",
        "Container Vessel",
        "Tanker",
        "Oil Tanker",
        "Chemical Tanker",
        "LNG Carrier",
        "LPG Carrier",
        "Ro-Ro",
        "Offshore Supply Vessel",
        "OSV",
        "AHTS",
        "PSV",
        "Diving Support Vessel",
        "ERRV",
        "FPSO",
        "FSO",
        "Drilling Vessel",
        "Research Vessel",
        "Survey Vessel",
        "Cruise Ship",
        "Cruise Vessel",
    ]

    low = (
        text or ""
    ).lower()

    for vessel_type in types:

        if vessel_type.lower() in low:

            return vessel_type

    return None


# ============================================================
# VESSEL NAME
# ============================================================

def extract_vessel_name(text):

    return extract_field(
        text,
        [
            "Название судна",
            "Vessel name",
            "Ship name",
        ],
    )


# ============================================================
# REGION
# ============================================================

def extract_region(text):

    return extract_field(
        text,
        [
            "Регион работы",
            "Region",
            "Trading area",
            "Trading Area",
        ],
    )


# ============================================================
# JOINING DATE
# ============================================================

def extract_joining_date(text):

    return extract_field(
        text,
        [
            "Дата посадки на борт",
            "Joining date",
            "Joining",
            "Join date",
        ],
    )


# ============================================================
# DURATION
# ============================================================

def extract_duration(text):

    return extract_field(
        text,
        [
            "Длительность рейса",
            "Contract duration",
            "Duration",
            "Contract",
        ],
    )


# ============================================================
# SALARY
# ============================================================

def extract_salary(text):

    value = extract_field(
        text,
        [
            "Зарплата",
            "Salary",
            "Wage",
            "Pay",
        ],
    )

    if value:

        return value[:100]

    match = re.search(
        r"(?:EUR|USD|GBP|€|\$|£)"
        r"\s?\d[\d,.\s]*(?:\s*(?:per|/)\s*"
        r"(?:month|day|week))?",
        text or "",
        re.I,
    )

    if match:

        return normalize_space(
            match.group(0)
        )

    return None


# ============================================================
# INFO CLEANING
# ============================================================

REMOVE_PHRASES = [
    "Пишите нам",
    "Морякам",
    "Компаниям",
    "Создать резюме",
    "Разослать резюме",
    "Поднять резюме в ТОП",
    "Скачать базу компаний",
    "Подписаться на вакансии",
    "Крюинги на карте",
    "Услуги для моряков",
    "Услуги для компаний",
    "Выход",
    "Персональное меню",

    # IMPORTANT:
    # Do not include Telegram contact
    # from UkrCrewing website.
    "telegram: @ukrcrewing_admin",
]


def clean_info(text):

    if not text:
        return ""

    lines = []

    for raw in text.splitlines():

        line = normalize_space(
            raw
        )

        if not line:
            continue

        low = line.lower()

        # ----------------------------------------------------
        # REMOVE UKRCREWING TELEGRAM ADMIN
        # ----------------------------------------------------

        if re.search(
            r"\btelegram\s*:\s*@ukrcrewing_admin\b",
            line,
            re.I,
        ):
            continue

        if any(
            phrase.lower() in low
            for phrase in REMOVE_PHRASES
        ):
            continue

        if EMAIL_RE.search(line):
            continue

        if line in lines:
            continue

        lines.append(line)

    keywords = [
        "дополнительная информация",
        "additional information",
        "requirement",
        "requirements",
        "required",
        "experience",
        "certificate",
        "certificates",
        "stcw",
        "dp",
        "dpo",
        "bosi",
        "h2s",
        "crew",
        "nationality",
        "visa",
        "english",
        "age",
        "previous",
        "salary",
        "duration",
        "boarding",
        "joining",
        "management",
        "flag",
        "dwt",
        "year of build",
    ]

    preferred = []

    for line in lines:

        low = line.lower()

        if any(
            keyword in low
            for keyword in keywords
        ):

            preferred.append(line)

    if preferred:

        lines = preferred

    result = []

    total = 0

    for line in lines:

        if total + len(line) > 1500:
            break

        result.append(line)

        total += len(line)

    return "\n".join(
        result
    ).strip()


# ============================================================
# FINAL MESSAGE CLEANING
# ============================================================

def remove_forbidden_telegram(text):

    if not text:
        return text

    # Remove:
    # telegram: @ukrcrewing_admin
    text = re.sub(
        r"(?im)^\s*telegram\s*:\s*@ukrcrewing_admin\s*$",
        "",
        text,
    )

    # Also remove if it appears inside a longer line.
    text = re.sub(
        r"(?i)\btelegram\s*:\s*@ukrcrewing_admin\b",
        "",
        text,
    )

    # Remove possible double blank lines.
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


# ============================================================
# JOB ID
# ============================================================

def extract_job_id(url):

    match = re.search(
        r"/vacancy/(\d+)",
        url or "",
        re.I,
    )

    if match:

        return match.group(1)

    return None


# ============================================================
# JOB LINKS FROM PAGE
# ============================================================

async def get_job_links(page):

    links = {}

    anchors = page.locator(
        'a[href*="/vacancy/"]'
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

            full_url = urljoin(
                UKRCREWING_BASE,
                href,
            )

            job_id = extract_job_id(
                full_url
            )

            if not job_id:
                continue

            links[job_id] = full_url

        except Exception:
            continue

    return links


# ============================================================
# PAGINATION
# ============================================================

async def get_pagination_links(page):

    pages = {}

    pages["0"] = UKRCREWING_URL

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

            full_url = urljoin(
                UKRCREWING_BASE,
                href,
            )

            match = re.search(
                r"/vacancy/p(\d+)/?",
                full_url,
                re.I,
            )

            if not match:
                continue

            page_number = match.group(1)

            pages[page_number] = full_url

        except Exception:
            continue

    return pages


async def discover_vacancy_pages(page):

    log(
        "=== DISCOVERING VACANCY PAGES ==="
    )

    pages = {}

    current_url = UKRCREWING_URL

    for page_number in range(0, 100):

        if page_number == 0:

            url = current_url

        else:

            url = (
                f"{UKRCREWING_BASE}/vacancy/"
                f"p{page_number}/"
            )

        log(
            f"Checking vacancy page: {url}"
        )

        try:

            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(
                700
            )

        except Exception as e:

            log(
                f"Could not open page: {e}"
            )

            break

        if await is_login_page(
            page
        ):

            log(
                "Redirected to login. "
                "Stopping pagination."
            )

            break

        links = await get_job_links(
            page
        )

        log(
            f"Found {len(links)} vacancy links "
            f"on page {page_number}."
        )

        if not links:

            log(
                "No vacancy links found. "
                "Stopping pagination."
            )

            break

        for job_id, job_url in links.items():

            pages[job_id] = job_url

        pagination = await get_pagination_links(
            page
        )

        if str(page_number + 1) not in pagination:

            log(
                "Next pagination page not found. "
                "Pagination finished."
            )

            break

    log(
        f"TOTAL UNIQUE VACANCY LINKS FOUND: "
        f"{len(pages)}"
    )

    return pages


# ============================================================
# LOGIN
# ============================================================

async def is_login_page(page):

    url = (
        page.url or ""
    ).lower()

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

    login_url = (
        f"{UKRCREWING_BASE}/en/login"
    )

    await page.goto(
        login_url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(
        1500
    )

    log(
        f"Login page URL: {page.url}"
    )

    email = None

    selectors = [
        'input[name="email"]',
        'input[type="email"]',
        'input[name="username"]',
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
                    f"Email field found: {selector}"
                )

                break

        except Exception:
            pass

    if email is None:

        raise RuntimeError(
            "UKR Crewing email field not found."
        )

    password = page.locator(
        'input[type="password"]'
    ).first

    if await password.count() == 0:

        raise RuntimeError(
            "UKR Crewing password field not found."
        )

    log(
        "Password field found."
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
                    f"Login button found: {selector}"
                )

                break

        except Exception:
            pass

    if submit:

        await submit.click()

    else:

        log(
            "Submit button not found. "
            "Pressing Enter."
        )

        await password.press(
            "Enter"
        )

    await page.wait_for_timeout(
        3000
    )

    log(
        f"URL after login: {page.url}"
    )

    if await is_login_page(
        page
    ):

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
        UKRCREWING_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(
        1500
    )

    log(
        f"Vacancy page URL: {page.url}"
    )

    if await is_login_page(
        page
    ):

        log(
            "Authentication required."
        )

        await login_to_ukrcrewing(
            page
        )

        await page.goto(
            UKRCREWING_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await page.wait_for_timeout(
            1500
        )

    if await is_login_page(
        page
    ):

        raise RuntimeError(
            "Authentication failed."
        )

    log(
        "✅ Vacancy page loaded."
    )


# ============================================================
# READ JOB
# ============================================================

async def read_job(
    page,
    job_id,
    url,
):

    log("")
    log(
        f"Opening vacancy: {job_id}"
    )

    try:

        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await page.wait_for_timeout(
            700
        )

    except Exception as e:

        log(
            f"Could not open vacancy "
            f"{job_id}: {e}"
        )

        return None

    if await is_login_page(
        page
    ):

        log(
            f"Vacancy {job_id} "
            "redirected to login."
        )

        return None

    try:

        text = await page.locator(
            "body"
        ).inner_text()

    except Exception as e:

        log(
            f"Could not read vacancy "
            f"{job_id}: {e}"
        )

        return None

    text = text.strip()

    if not text:

        log(
            f"Skipping {job_id}: "
            "empty page."
        )

        return None

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    publication_date = (
        extract_publication_date(
            text
        )
    )

    log(
        f"Publication date: "
        f"{publication_date}"
    )

    today = today_date_string()

    if publication_date not in allowed_dates():

        log(
            f"⏭️ Skipping {job_id}: "
            f"not fresh "
            f"({publication_date}, today {today})"
        )

        return None

    # --------------------------------------------------------
    # CONTACT EMAIL
    # --------------------------------------------------------

    email = extract_contact_email(
        text
    )

    if not email:

        log(
            f"⏭️ Skipping {job_id}: "
            "no valid corporate email "
            "in vacancy contact field."
        )

        return None

    # --------------------------------------------------------
    # PARSE
    # --------------------------------------------------------

    job = {
        "id": job_id,

        "url": url,

        "publication_date":
            publication_date,

        "title":
            extract_vacancy_title(
                text
            ),

        "rank":
            extract_rank(
                text
            ),

        "vessel_name":
            extract_vessel_name(
                text
            ),

        "vessel_type":
            extract_vessel_type(
                text
            ),

        "region":
            extract_region(
                text
            ),

        "date":
            extract_joining_date(
                text
            ),

        "duration":
            extract_duration(
                text
            ),

        "salary":
            extract_salary(
                text
            ),

        "email":
            email,

        "info":
            clean_info(
                text
            ),
    }

    return job


# ============================================================
# SITE (Way At Sea)
# ============================================================

def _post_to_site(payload):

    request = urllib.request.Request(
        SITE_IMPORT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Import-Token": SITE_IMPORT_TOKEN,
            "User-Agent": "WayAtSea-Parser/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8") or "{}")
        return response.status, (data.get("results") or [{}])[0]


async def send_to_site(job, check_only=False):
    """Отправляет вакансию на сайт (check_only=True — только проверить, не дубль ли).
    Возвращает "new" — новая вакансия, "duplicate" — уже публиковалась,
    False — сайт не настроен или недоступен (тогда Telegram работает как обычно)."""

    if not SITE_IMPORT_URL or not SITE_IMPORT_TOKEN:
        return False

    payload = {
        "source": "ukrcrewing",
        "external_id": str(job["id"]),
        "url": job.get("url"),
        "title": job.get("title"),
        "rank": job.get("rank"),
        "vessel_name": job.get("vessel_name"),
        "vessel_type": job.get("vessel_type"),
        "region": job.get("region"),
        "joining_date": job.get("date"),
        "duration": job.get("duration"),
        "salary": job.get("salary"),
        "email": job.get("email"),
        "info": job.get("info"),
        "published": job.get("publication_date"),
    }

    if check_only:
        payload = {"vacancies": [payload], "dry_run": True}

    try:

        status, result = await asyncio.to_thread(
            _post_to_site,
            payload,
        )

        if result.get("duplicate"):

            log(
                f"♻️ Duplicate on site: {job['id']} "
                f"({result.get('reason')})"
            )

            return "duplicate"

        if not check_only:

            log(
                f"🌐 Sent to site: {job['id']} "
                f"(HTTP {status})"
            )

        return "new"

    except urllib.error.HTTPError as e:

        log(
            f"❌ Site error for {job['id']}: "
            f"HTTP {e.code}"
        )

    except Exception as e:

        log(
            f"❌ Site error for {job['id']}: "
            f"{type(e).__name__}: {e}"
        )

    return False


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def make_message(job):

    lines = []

    lines.append(
        "🇺🇦 UkrCrewing"
    )

    lines.append("")

    lines.append(
        f"⚓ Rank: {job['rank']}"
    )

    if job["vessel_name"]:

        lines.append(
            f"🚢 Vessel name: "
            f"{job['vessel_name']}"
        )

    if job["vessel_type"]:

        lines.append(
            f"🚢 Vessel type: "
            f"{job['vessel_type']}"
        )

    if job["region"]:

        lines.append(
            f"🌍 Region: "
            f"{job['region']}"
        )

    if job["date"]:

        lines.append(
            f"📅 Date: "
            f"{job['date']}"
        )

    if job["duration"]:

        lines.append(
            f"⏱️ Duration: "
            f"{job['duration']}"
        )

    if job["salary"]:

        lines.append(
            f"💰 Salary: "
            f"{job['salary']}"
        )

    if job["info"]:

        lines.append(
            f"ℹ️ {job['info']}"
        )

    lines.append(
        f"📩 Contact: "
        f"{job['email']}"
    )

    hashtags = []

    rank = job["rank"]

    if rank and rank != "Multiple positions":

        tag = re.sub(
            r"[^A-Za-z0-9]",
            "",
            rank,
        )

        if tag:

            hashtags.append(
                "#" + tag
            )

    vessel_type = (
        job["vessel_type"]
    )

    if vessel_type:

        tag = re.sub(
            r"[^A-Za-z0-9]",
            "",
            vessel_type,
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

    lines.append("")

    lines.append(
        " ".join(hashtags)
    )

    # --------------------------------------------------------
    # FINAL SAFETY CLEANING
    # --------------------------------------------------------

    message = "\n".join(
        lines
    )

    message = remove_forbidden_telegram(
        message
    )

    return message


# ============================================================
# SCAN
# ============================================================

async def scan(sent_jobs, limit=None):

    processed = 0

    now = london_now()

    log("")
    log("=" * 70)
    log("🇺🇦 === UKR CREWING SCAN STARTED ===")
    log(
        now.strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
    )
    log(
        f"Today's vacancies: "
        f"{today_date_string()}"
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

            links = (
                await discover_vacancy_pages(
                    page
                )
            )

            log(
                f"Found {len(links)} "
                "vacancy links."
            )

            if not links:

                log(
                    "No vacancy links found."
                )

                return

            job_page = await context.new_page()

            for job_id, url in links.items():

                if str(job_id) in sent_jobs:

                    log(
                        f"Already sent: "
                        f"{job_id}"
                    )

                    continue

                job = await read_job(
                    job_page,
                    job_id,
                    url,
                )

                if not job:

                    continue

                if str(job_id) in sent_jobs:

                    log(
                        f"Already sent after parsing: "
                        f"{job_id}"
                    )

                    continue

                message = make_message(
                    job
                )

                log("")
                log(
                    "--- TELEGRAM MESSAGE ---"
                )

                log(
                    message
                )

                log(
                    "--- END MESSAGE ---"
                )

                # Сначала спрашиваем сайт: не публиковалась ли уже эта вакансия
                site_result = await send_to_site(
                    job,
                    check_only=True,
                )

                # Уже публиковалась (например, после перезапуска парсер «забыл» её) —
                # не дублируем и в Telegram
                if site_result == "duplicate":

                    sent_jobs.add(
                        str(job_id)
                    )

                    save_memory(
                        sent_jobs
                    )

                    log(
                        f"⏭️ Skipping Telegram for duplicate: "
                        f"{job_id}"
                    )

                    continue

                try:

                    await send_telegram(
                        message
                    )

                    sent_jobs.add(
                        str(job_id)
                    )

                    save_memory(
                        sent_jobs
                    )

                    log(
                        f"💾 Saved sent vacancy: "
                        f"{job_id}"
                    )

                    # После успешной отправки в Telegram — сохраняем вакансию на сайт
                    await send_to_site(
                        job
                    )

                    processed += 1

                    if limit and processed >= limit:

                        log(
                            f"✋ Limit reached: {limit} vacancies"
                        )

                        break

                except Exception as e:

                    log(
                        f"❌ Telegram error "
                        f"for {job_id}: "
                        f"{type(e).__name__}: {e}"
                    )

            await job_page.close()

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
            f"  - {hour:02d}:{minute:02d} "
            "Europe/London"
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
            f"Next UKR Crewing scan: "
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
    log("🇺🇦 UKR CREWING BOT STARTED")
    log("=" * 70)

    log(
        "📅 Today: "
        f"{today_date_string()}"
    )

    log(
        "📨 Telegram: "
        f"{TELEGRAM_TARGET}"
    )

    log(
        "🕘 Timezone: Europe/London"
    )

    check_environment()

    sent_jobs = load_memory()

    await connect_telegram()

    if RUN_ON_START:

        log(
            f"▶️ RUN_ON_START: scanning now "
            f"(limit {SCAN_LIMIT or 'none'})"
        )

        try:

            await scan(
                sent_jobs,
                limit=SCAN_LIMIT or None,
            )

        except Exception as e:

            log(
                f"🔥 START SCAN ERROR: "
                f"{type(e).__name__}: {e}"
            )

    await scheduler(
        sent_jobs
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        log(
            "UKR Crewing stopped."
        )

    except Exception as e:

        log(
            f"🔥 FATAL ERROR: "
            f"{type(e).__name__}: {e}"
        )

        raise
