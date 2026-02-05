"""Stealth browser for JS-heavy scraping targets.

Adapted from canvas-companion StealthBrowser pattern.
Uses Patchright (Playwright fork with anti-detection patches).
"""

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

STEALTH_INIT_SCRIPT = """
// Mask navigator.webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Spoof navigator.deviceMemory
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

// Spoof navigator.platform to match Windows Chrome
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });

// Spoof plugins array
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
            {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
            {name: 'Native Client', filename: 'internal-nacl-plugin'}
        ];
        plugins.item = (i) => plugins[i];
        plugins.namedItem = (name) => plugins.find(p => p.name === name);
        plugins.refresh = () => {};
        return plugins;
    }
});

// Spoof languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Fix screen dimension mismatch
const screenWidth = 1920;
const screenHeight = 1080;
Object.defineProperty(screen, 'width', { get: () => screenWidth });
Object.defineProperty(screen, 'height', { get: () => screenHeight });
Object.defineProperty(screen, 'availWidth', { get: () => screenWidth });
Object.defineProperty(screen, 'availHeight', { get: () => screenHeight - 40 });
Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });

// Match window dimensions to screen
Object.defineProperty(window, 'outerWidth', { get: () => screenWidth });
Object.defineProperty(window, 'outerHeight', { get: () => screenHeight });

// Mock window.chrome object
window.chrome = {
    runtime: { connect: () => {}, sendMessage: () => {} },
    loadTimes: () => ({}),
    csi: () => ({})
};

// Fix permissions.query
const origQuery = navigator.permissions.query;
navigator.permissions.query = (p) => p.name === 'notifications'
    ? Promise.resolve({state: Notification.permission}) : origQuery(p);

// Fix timezone offset (CST = UTC-6)
Date.prototype.getTimezoneOffset = function() { return 360; };
"""

BROWSER_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-async-dns",
    "--dns-prefetch-disable",
    "--disable-infobars",
    "--disable-extensions",
    "--disable-default-apps",
    "--no-first-run",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--window-size=1920,1080",
]

BROWSER_CONTEXT_OPTIONS = {
    "viewport": {"width": 1920, "height": 1080},
    "screen": {"width": 1920, "height": 1080},
    "device_scale_factor": 1,
    "locale": "en-US",
    "timezone_id": "America/Chicago",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "color_scheme": "light",
    "accept_downloads": False,
}


class StealthBrowser:
    """Browser wrapper with anti-detection features."""

    def __init__(self, headless: bool = True, timeout: int = 30000, channel: str | None = None):
        self.headless = headless
        self.timeout = timeout
        self.channel = channel
        self.browser = None
        self.playwright = None

    async def launch(self) -> bool:
        """Launch browser. Returns True on success."""
        try:
            from patchright.async_api import async_playwright
            self.playwright = await async_playwright().start()
            launch_kwargs = {
                "headless": self.headless,
                "args": BROWSER_LAUNCH_ARGS,
            }
            if self.channel:
                launch_kwargs["channel"] = self.channel
            self.browser = await self.playwright.chromium.launch(**launch_kwargs)
            logger.info(f"Launched Patchright {'Chrome' if self.channel else 'Chromium'}")
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

    async def warm_session(self, page, target_url):
        """Visit homepage first, simulate human behavior, then navigate to target.

        Useful for sites with Cloudflare or similar bot protection that
        check browsing patterns before serving content.
        """
        domain = urlparse(target_url).netloc
        homepage = f"https://{domain}"
        logger.info(f"Warming session via {homepage}")

        await page.goto(homepage, wait_until="domcontentloaded", timeout=15000)
        await human_delay(2000, 4000)
        await self.apply_stealth(page)

        # Simulate human mouse/scroll activity
        await page.mouse.move(random.randint(100, 500), random.randint(100, 300))
        await page.mouse.wheel(delta_x=0, delta_y=random.randint(200, 400))
        await human_delay(1000, 2000)

        # Navigate to the actual target
        await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        await human_delay(2000, 5000)
        await self.apply_stealth(page)

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


@asynccontextmanager
async def get_browser(headless: bool = True, timeout: int = 30000, channel: str | None = None):
    """Context manager for stealth browser sessions.

    Args:
        channel: Browser channel. Use "chrome" for full Google Chrome
                 (better Cloudflare bypass). Default None uses Chromium.
    """
    browser = StealthBrowser(headless=headless, timeout=timeout, channel=channel)
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
