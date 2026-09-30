import asyncio
import os
from playwright.async_api import async_playwright


CREWLINK_EMAIL = os.getenv("UKRCREWING_EMAIL")
CREWLINK_PASSWORD = os.getenv("UKRCREWING_PASSWORD")

LOGIN_URL = "https://ukrcrewing.com.ua/login"
VACANCY_URL = "https://ukrcrewing.com.ua/vacancy/?v_sort=1&v_sort_dir=1"


async def main():

    print("=" * 60, flush=True)
    print("=== UKR CREWING TEST STARTED ===", flush=True)
    print("=" * 60, flush=True)

    print(
        f"UKRCREWING_EMAIL set: {bool(CREWLINK_EMAIL)}",
        flush=True
    )

    print(
        f"UKRCREWING_PASSWORD set: {bool(CREWLINK_PASSWORD)}",
        flush=True
    )

    if not CREWLINK_EMAIL or not CREWLINK_PASSWORD:
        raise RuntimeError(
            "UKRCREWING_EMAIL or UKRCREWING_PASSWORD is missing."
        )

    async with async_playwright() as p:

        print("Launching Chromium...", flush=True)

        browser = await p.chromium.launch(
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

            print("Opening UKR Crewing...", flush=True)

            await page.goto(
                LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(3000)

            print(
                f"Current URL: {page.url}",
                flush=True
            )

            print(
                "Page title:",
                await page.title(),
                flush=True
            )

            print("Looking for email field...", flush=True)

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

                locator = page.locator(selector).first

                try:

                    if await locator.count() > 0:

                        print(
                            f"Email field found: {selector}",
                            flush=True
                        )

                        email_field = locator
                        break

                except Exception:
                    pass

            if email_field is None:
                raise RuntimeError(
                    "UKR Crewing email field was not found."
                )

            print("Looking for password field...", flush=True)

            password_field = page.locator(
                'input[type="password"]'
            ).first

            if await password_field.count() == 0:

                raise RuntimeError(
                    "UKR Crewing password field was not found."
                )

            print("Filling credentials...", flush=True)

            await email_field.fill(CREWLINK_EMAIL)
            await password_field.fill(CREWLINK_PASSWORD)

            print("Credentials filled.", flush=True)

            buttons = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Login")',
                'button:has-text("Log in")',
                'button:has-text("Войти")',
                'button:has-text("Увійти")',
            ]

            submit = None

            for selector in buttons:

                locator = page.locator(selector).first

                try:

                    if await locator.count() > 0:

                        print(
                            f"Login button found: {selector}",
                            flush=True
                        )

                        submit = locator
                        break

                except Exception:
                    pass

            if submit:

                await submit.click()

            else:

                print(
                    "Login button not found. Pressing Enter.",
                    flush=True
                )

                await password_field.press("Enter")

            await page.wait_for_timeout(5000)

            print(
                f"URL after login: {page.url}",
                flush=True
            )

            print(
                f"Title after login: {await page.title()}",
                flush=True
            )

            if "login" in page.url.lower():
                print(
                    "⚠️ Still on login page.",
                    flush=True
                )

                body = await page.locator(
                    "body"
                ).inner_text()

                print(
                    "LOGIN PAGE TEXT:",
                    flush=True
                )

                print(
                    body[:3000],
                    flush=True
                )

                raise RuntimeError(
                    "UKR Crewing login appears to have failed."
                )

            print(
                "✅ UKR CREWING LOGIN SUCCESS",
                flush=True
            )

            print(
                "Opening vacancy page...",
                flush=True
            )

            await page.goto(
                VACANCY_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            await page.wait_for_timeout(3000)

            print(
                f"Vacancy page URL: {page.url}",
                flush=True
            )

            body = await page.locator(
                "body"
            ).inner_text()

            print(
                "Vacancy page loaded.",
                flush=True
            )

            print(
                "Page text preview:",
                flush=True
            )

            print(
                body[:5000],
                flush=True
            )

            print("=" * 60, flush=True)
            print(
                "=== UKR CREWING TEST FINISHED ===",
                flush=True
            )
            print("=" * 60, flush=True)

        finally:

            await context.close()
            await browser.close()

            print(
                "Browser closed.",
                flush=True
            )


if __name__ == "__main__":
    asyncio.run(main())
