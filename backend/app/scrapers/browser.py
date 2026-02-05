"""Stealth browser for JS-heavy scraping targets.

Adapted from canvas-companion StealthBrowser pattern.
Uses Patchright (Playwright fork with anti-detection patches).
"""

import asyncio
import logging
import random
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

STEALTH_INIT_SCRIPT = """
// Mask automation signals
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

// Mock window.chrome
window.chrome = {
    runtime: { connect: () => {}, sendMessage: () => {} },
    loadTimes: () => ({}),
    csi: () => ({})
};
"""

BROWSER_CONTEXT_OPTIONS = {
    "viewport": {"width": 1920, "height": 1080},
    "locale": "en-US",
    "timezone_id": "America/Chicago",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "color_scheme": "light",
    "accept_downloads": False,
}


class StealthBrowser:
    """Browser wrapper with anti-detection features."""

    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
        self.browser = None
        self.playwright = None

    async def launch(self) -> bool:
        """Launch browser. Returns True on success."""
        try:
            from patchright.async_api import async_playwright
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-async-dns",
                    "--dns-prefetch-disable",
                ],
            )
            logger.info("Launched Patchright Chromium")
            return True
        except Exception as e:
            logger.error(f"Failed to launch browser: {e}")
            return False

    async def new_page(self):
        """Create a new page with stealth settings."""
        if not self.browser:
            raise RuntimeError("Browser not launched")

        context = await self.browser.new_context(**BROWSER_CONTEXT_OPTIONS)
        # Note: context.add_init_script breaks DNS resolution in Docker
        # (Patchright bug). Stealth scripts are injected post-navigation
        # via apply_stealth() instead.
        page = await context.new_page()
        page.set_default_timeout(self.timeout)
        return page

    @staticmethod
    async def apply_stealth(page):
        """Inject stealth scripts after page load. Call after goto()."""
        await page.evaluate(STEALTH_INIT_SCRIPT)

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


@asynccontextmanager
async def get_browser(headless: bool = True, timeout: int = 30000):
    """Context manager for stealth browser sessions."""
    browser = StealthBrowser(headless=headless, timeout=timeout)
    try:
        if not await browser.launch():
            raise RuntimeError("Failed to launch stealth browser")
        yield browser
    finally:
        await browser.close()


async def human_delay(min_ms: int = 100, max_ms: int = 500) -> None:
    """Random delay to appear human."""
    delay = random.uniform(min_ms / 1000, max_ms / 1000)
    await asyncio.sleep(delay)
