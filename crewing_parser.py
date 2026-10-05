import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright


BASE_URL = "https://ukrcrewing.com.ua"
AGENCY_URL = f"{BASE_URL}/agency"

UKRCREWING_EMAIL = os.getenv("UKRCREWING_EMAIL")
UKRCREWING_PASSWORD = os.getenv("UKRCREWING_PASSWORD")

OUTPUT_FILE = Path("crewings.txt")

# На первом тесте собираем только 5
MAX_CREWINGS = 5


def clean(text):
    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


async def is_login_page(page):
    url = (page.url or "").lower()

    if "/login" in url:
        return True

    try:
        return await page.locator(
            'input[type="password"]'
        ).count() > 0
    except Exception:
        return False


async def login(page):

    print("🔐 Открываем страницу логина...")

    await page.goto(
        f"{BASE_URL}/en/login",
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(1500)

    email_field = page.locator(
        'input[type="email"]'
    ).first

    if await email_field.count() == 0:
        email_field = page.locator(
            'input[name="email"]'
        ).first

    password_field = page.locator(
        'input[type="password"]'
    ).first

    if await email_field.count() == 0:
        raise RuntimeError(
            "Не найдено поле Email"
        )

    if await password_field.count() == 0:
        raise RuntimeError(
            "Не найдено поле Password"
        )

    await email_field.fill(
        UKRCREWING_EMAIL
    )

    await password_field.fill(
        UKRCREWING_PASSWORD
    )

    submit = page.locator(
        'button[type="submit"]'
    ).first

    if await submit.count() == 0:
        submit = page.locator(
            'input[type="submit"]'
        ).first

    if await submit.count() > 0:
        await submit.click()
    else:
        await password_field.press("Enter")

    await page.wait_for_timeout(3000)

    if await is_login_page(page):
        raise RuntimeError(
            "❌ Авторизация не прошла"
        )

    print("✅ Авторизация успешна")


async def get_crewing_links(page):

    print("📋 Открываем список крюингов...")

    await page.goto(
        AGENCY_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await page.wait_for_timeout(1000)

    if await is_login_page(page):
        await login(page)

        await page.goto(
            AGENCY_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        await page.wait_for_timeout(1000)

    links = []

    anchors = page.locator(
        'a[href*="/agency/"]'
    )

    count = await anchors.count()

    for i in range(count):

        href = await anchors.nth(i).get_attribute(
            "href"
        )

        if not href:
            continue

        full_url = urljoin(
            BASE_URL,
            href
        )

        # Пропускаем сам /agency/
        if re.search(
            r"/agency/?$",
            full_url,
            re.I,
        ):
            continue

        # Пропускаем страницы пагинации
        # /agency/p2/
        if re.search(
            r"/agency/p\d+/?$",
            full_url,
            re.I,
        ):
            continue

        # Нам нужны ссылки вида:
        # /agency/aashipping
        if not re.search(
            r"/agency/[^/]+/?$",
            full_url,
            re.I,
        ):
            continue

        if full_url not in links:
            links.append(full if full_url not in links:
    links.append(full
