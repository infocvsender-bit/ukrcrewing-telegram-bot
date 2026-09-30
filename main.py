import asyncio
import json
import os
import re
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

LOGIN_URL = "https://ukrcrewing.com.ua/login"

VACANCY_URL = (
    "https://ukrcrewing.com.ua/vacancy/"
    "?v_sort=1&v_sort_dir=1"
)

SENT_FILE = Path("/app/sent_jobs.json")


# ============================================================
# HELPERS
# ============================================================

def log(message=""):
    print(message, flush=True)


def normalize_space(text):
    return re.sub(r"\s+", " ", text or "").strip()


def save_memory(sent_jobs):
    SENT_FILE.write_text(
        json.dumps(
            sorted(sent_jobs),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_memory():

    if not SENT_FILE.exists():
        return set()

    try:

        data = json.loads(
            SENT_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, list):
            return set(str(x) for x in data)

        if isinstance(data, dict):
            return set(
                str(x)
                for x in data.get("sent", [])
            )

    except Exception as e:

        log(
            f"WARNING: Could not read memory: {e}"
        )

    return set()


def first_match(patterns, text):

    for pattern in patterns:

        match = re.search(
            pattern,
            text or "",
            re.I | re.M,
        )

        if match:

            value = normalize_space(
                match.group(1)
            )

            if value:
                return value

    return None


# ============================================================
# TELEGRAM
# ============================================================

telegram_client = None


async def connect_telegram():

    global telegram_client

    log("=== CONNECTING TELEGRAM ===")

    if not TELEGRAM_API_ID:
        raise RuntimeError(
            "TELEGRAM_API_ID is missing."
        )

    if not TELEGRAM_API_HASH:
        raise RuntimeError(
            "TELEGRAM_API_HASH is missing."
        )

    if not TELEGRAM_SESSION:
        raise RuntimeError(
            "TELEGRAM_SESSION is missing."
        )

    telegram_client = TelegramClient(
        StringSession(TELEGRAM_SESSION),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
    )

    await telegram_client.connect()

    if not await telegram_client.is_user_authorized():

        raise RuntimeError(
            "TELEGRAM_SESSION is not authorized."
        )

    me = await telegram_client.get_me()

    log(
        "Telegram connected as: "
        f"{getattr(me, 'username', None) or me.first_name}"
    )

    log(
        f"Telegram target: {TELEGRAM_TARGET}"
    )


async def send_telegram(message):

    global telegram_client

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

    log("Telegram message sent.")


# ============================================================
# UKR CREWING LOGIN
# ============================================================

async def login_to_ukrcrewing(page):

    log("=== UKR CREWING LOGIN ===")

    await page.goto(
        LOGIN_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(2000)

    log(
        f"Login page URL: {page.url}"
    )

    email_selectors = [
        'input[type="email"]',
        'input[name="email"]',
        'input[name="username"]',
        'input[name="login"]',
        'input[placeholder*="email" i]',
        'input[placeholder*="e-mail" i]',
    ]

    email_field = None

    for selector in email_selectors:

        locator = page.locator(
            selector
        ).first

        try:

            if await locator.count() > 0:

                email_field = locator

                log(
                    f"Email field found: {selector}"
                )

                break

        except Exception:
            pass

    if email_field is None:

        raise RuntimeError(
            "UKR Crewing email field not found."
        )

    password_field = page.locator(
        'input[type="password"]'
    ).first

    if await password_field.count() == 0:

        raise RuntimeError(
            "UKR Crewing password field not found."
        )

    await email_field.fill(
        UKRCREWING_EMAIL
    )

    await password_field.fill(
        UKRCREWING_PASSWORD
    )

    log("Credentials filled.")

    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("Log in")',
        'button:has-text("Войти")',
        'button:has-text("Увійти")',
    ]

    submit = None

    for selector in selectors:

        locator = page.locator(
            selector
        ).first

        try:

            if await locator.count() > 0:

                submit = locator

                log(
                    f"Login button found: {selector}"
                )

                break

        except Exception:
            pass

    if submit:

        await submit.click()

    else:

        await password_field.press("Enter")

    await page.wait_for_timeout(5000)

    log(
        f"URL after login: {page.url}"
    )

    if "/login" in page.url.lower():

        raise RuntimeError(
            "UKR Crewing login failed."
        )

    log(
        "=== UKR CREWING LOGIN SUCCESS ==="
    )


# ============================================================
# VACANCY LINKS
# ============================================================

VACANCY_ID_RE = re.compile(
    r"/vacancy/(\d+)",
    re.I,
)


async def get_vacancy_links(page):

    log(
        "=== GETTING UKR CREWING VACANCIES ==="
    )

    links = {}

    anchors = page.locator(
        'a[href*="/vacancy/"]'
    )

    count = await anchors.count()

    log(
        f"Vacancy links found on page: {count}"
    )

    for i in range(count):

        try:

            href = await anchors.nth(
                i
            ).get_attribute("href")

            if not href:
                continue

            match = VACANCY_ID_RE.search(
                href
            )

            if not match:
                continue

            job_id = match.group(1)

            full_url = urljoin(
                "https://ukrcrewing.com.ua",
                href,
            )

            links[job_id] = full_url

        except Exception:
            continue

    log(
        f"Unique vacancy IDs found: {len(links)}"
    )

    return links


# ============================================================
# VACANCY PARSING
# ============================================================

def extract_rank(text):

    patterns = [
        r"Вакансия\s+([^\n]+)",
        r"Position\s*[:\-]\s*([^\n]+)",
        r"Должность\s*[:\-]\s*([^\n]+)",
    ]

    value = first_match(
        patterns,
        text,
    )

    if value:
        return value[:100]

    ranks = [
        "Master",
        "Chief Officer",
        "Chief Engineer",
        "2nd Engineer",
        "3rd Engineer",
        "4th Engineer",
        "1st Engineer",
        "2nd Officer",
        "3rd Officer",
        "ETO",
        "Electrician",
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
        "Steward",
        "Deck Cadet",
        "Engine Cadet",
    ]

    low = text.lower()

    for rank in ranks:

        if re.search(
            r"\b" + re.escape(rank.lower()) + r"\b",
            low,
        ):
            return rank

    return "Multiple positions"


def extract_field(text, patterns):

    return first_match(
        patterns,
        text,
    )


def extract_vessel_type(text):

    value = extract_field(
        text,
        [
            r"Тип судна\s*:\s*([^\n]+)",
            r"Vessel Type\s*:\s*([^\n]+)",
            r"Vessel type\s*:\s*([^\n]+)",
        ],
    )

    if value:
        return value[:100]

    types = [
        "Bulk Carrier",
        "Container Ship",
        "Container Vessel",
        "Oil Tanker",
        "Chemical Tanker",
        "Tanker",
        "LNG Carrier",
        "LPG Carrier",
        "AHTS",
        "PSV",
        "OSV",
        "Diving Support Vessel",
        "ERRV",
        "FPSO",
        "FSO",
        "Drilling Vessel",
        "Research Vessel",
        "Survey Vessel",
        "Cruise Ship",
        "Ro-Ro",
    ]

    low = text.lower()

    for vessel_type in types:

        if vessel_type.lower() in low:
            return vessel_type

    return None


def extract_vessel_name(text):

    return extract_field(
        text,
        [
            r"Название судна\s*:\s*([^\n]+)",
            r"Vessel Name\s*:\s*([^\n]+)",
            r"Ship Name\s*:\s*([^\n]+)",
        ],
    )


def extract_region(text):

    return extract_field(
        text,
        [
            r"Регион работы\s*:\s*([^\n]+)",
            r"Region\s*:\s*([^\n]+)",
            r"Trading Area\s*:\s*([^\n]+)",
        ],
    )


def extract_date(text):

    return extract_field(
        text,
        [
            r"Дата посадки на борт\s*:\s*([^\n]+)",
            r"Joining Date\s*:\s*([^\n]+)",
            r"Joining\s*:\s*([^\n]+)",
        ],
    )


def extract_duration(text):

    return extract_field(
        text,
        [
            r"Длительность рейса\s*:\s*([^\n]+)",
            r"Contract Duration\s*:\s*([^\n]+)",
            r"Duration\s*:\s*([^\n]+)",
        ],
    )


def extract_salary(text):

    value = extract_field(
        text,
        [
            r"Зарплата\s*:\s*([^\n]+)",
            r"Salary\s*:\s*([^\n]+)",
            r"Wage\s*:\s*([^\n]+)",
            r"Pay\s*:\s*([^\n]+)",
        ],
    )

    if value:
        return value[:100]

    match = re.search(
        r"(?:EUR|USD|GBP|€|\$|£)\s?\d[\d,.\- ]*",
        text,
        re.I,
    )

    if match:
        return normalize_space(
            match.group(0)
        )

    return None


def extract_phone(text):

    match = re.search(
        r"(?:Телефон для отклика[^:\n]*:\s*)?"
        r"(\+?\d[\d\s().\-]{7,}\d)",
        text,
        re.I,
    )

    if match:

        phone = normalize_space(
            match.group(1)
        )

        return phone

    return None


def extract_email(text):

    emails = re.findall(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        text,
        re.I,
    )

    for email in emails:

        email = email.lower().strip(
            ".,;:()[]<>\"'"
        )

        if "ukrcrewing.com.ua" not in email:

            return email

    return None


def extract_additional_info(text):

    match = re.search(
        r"Дополнительная информация\s*:?\s*(.*?)(?="
        r"Телефон для отклика"
        r"|Контактный е-мейл"
        r"|Контактный email"
        r"|Крюинг:"
        r"|$)",
        text,
        re.I | re.S,
    )

    if not match:
        return None

    info = match.group(1).strip()

    lines = []

    for raw in info.splitlines():

        line = normalize_space(raw)

        if not line:
            continue

        if line in lines:
            continue

        lines.append(line)

    return "\n".join(lines)[:1200]


def make_hashtags(rank, vessel_type):

    hashtags = []

    if rank:

        tag = re.sub(
            r"[^A-Za-z0-9]",
            "",
            rank,
        )

        if tag:
            hashtags.append(
                "#" + tag
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

    return list(
        dict.fromkeys(hashtags)
    )


def make_message(job):

    lines = []

    lines.append(
        f"⚓ Rank: {job['rank']}"
    )

    if job["vessel_name"]:
        lines.append(
            f"🚢 Vessel name: {job['vessel_name']}"
        )

    if job["vessel_type"]:
        lines.append(
            f"🚢 Vessel type: {job['vessel_type']}"
        )

    if job["region"]:
        lines.append(
            f"🌍 Region: {job['region']}"
        )

    if job["date"]:
        lines.append(
            f"📅 Date: {job['date']}"
        )

    if job["duration"]:
        lines.append(
            f"⏱️ Duration: {job['duration']}"
        )

    if job["salary"]:
        lines.append(
            f"💰 Salary: {job['salary']}"
        )

    if job["info"]:
        lines.append(
            f"ℹ️ {job['info']}"
        )

    contact_parts = []

    if job["email"]:
        contact_parts.append(
            job["email"]
        )

    if job["phone"]:
        contact_parts.append(
            job["phone"]
        )

    if contact_parts:

        lines.append(
            "📩 Contact: "
            + " / ".join(contact_parts)
        )

    lines.append(
        " ".join(
            make_hashtags(
                job["rank"],
                job["vessel_type"],
            )
        )
    )

    return "\n".join(lines)


async def read_job(page, job_id, url):

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
            1000
        )

    except Exception as e:

        log(
            f"Could not open vacancy {job_id}: {e}"
        )

        return None

    try:

        text = await page.locator(
            "body"
        ).inner_text()

    except Exception as e:

        log(
            f"Could not read vacancy {job_id}: {e}"
        )

        return None

    text = text.strip()

    if not text:
        return None

    job = {
        "id": job_id,
        "url": url,
        "rank": extract_rank(text),
        "vessel_name": extract_vessel_name(text),
        "vessel_type": extract_vessel_type(text),
        "region": extract_region(text),
        "date": extract_date(text),
        "duration": extract_duration(text),
        "salary": extract_salary(text),
        "phone": extract_phone(text),
        "email": extract_email(text),
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
    log("=" * 70)

    async with async_playwright() as playwright:

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

        job_page = await context.new_page()

        try:

            await login_to_ukrcrewing(
                page
            )

            log(
                "Opening latest vacancies page..."
            )

            await page.goto(
                VACANCY_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(
                2000
            )

            log(
                f"Vacancy page URL: {page.url}"
            )

            links = await get_vacancy_links(
                page
            )

            log(
                f"Found {len(links)} vacancies."
            )

            if not links:

                log(
                    "NO VACANCIES FOUND."
                )

                return

            new_count = 0

            for job_id, url in links.items():

                if job_id in sent_jobs:

                    log(
                        f"Already sent: {job_id}"
                    )

                    continue

                job = await read_job(
                    job_page,
                    job_id,
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
                        job_id
                    )

                    save_memory(
                        sent_jobs
                    )

                    new_count += 1

                    log(
                        f"Saved vacancy ID: {job_id}"
                    )

                except Exception as e:

                    log(
                        f"Telegram error for "
                        f"{job_id}: {type(e).__name__}: {e}"
                    )

            log("")
            log(
                f"NEW VACANCIES SENT: {new_count}"
            )

            log(
                f"MEMORY TOTAL: {len(sent_jobs)}"
            )

        finally:

            await job_page.close()
            await context.close()
            await browser.close()

            log(
                "Chromium closed."
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

    if not UKRCREWING_EMAIL:
        raise RuntimeError(
            "UKRCREWING_EMAIL is missing."
        )

    if not UKRCREWING_PASSWORD:
        raise RuntimeError(
            "UKRCREWING_PASSWORD is missing."
        )

    sent_jobs = load_memory()

    log(
        f"Loaded sent IDs: {len(sent_jobs)}"
    )

    if sent_jobs:
        log(
            "Previously sent IDs:"
        )

        log(
            str(
                sorted(
                    int(x)
                    if x.isdigit()
                    else x
                    for x in sent_jobs
                )
            )
        )

    await connect_telegram()

    await scan(
        sent_jobs
    )

    if telegram_client:

        await telegram_client.disconnect()

        log(
            "Telegram disconnected."
        )


if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except Exception as e:

        log(
            f"🔥 FATAL ERROR: "
            f"{type(e).__name__}: {e}"
        )

        raise
