"""Cloudflare Turnstile bypass using Camoufox.

Camoufox is an anti-detect Firefox browser that modifies fingerprints at the C++
engine level rather than through JS injection. This makes it harder for bot
detection systems like Cloudflare Turnstile to identify automation.

Usage:
    solver = TurnstileSolver()
    async with solver.get_browser() as browser:
        page = await browser.new_page()
        html = await solver.navigate_with_turnstile_bypass(page, url)
"""

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class TurnstileSolver:
    """
    Cloudflare Turnstile bypass using Camoufox anti-detect browser.

    Features:
    - Uses Camoufox which patches Firefox at the C++ level
    - Human-like mouse movements and timing
    - Attempts to solve interactive Turnstile challenges
    """

    def __init__(self, headless: bool = True):
        """
        Initialize the solver.

        Args:
            headless: Whether to run browser in headless mode.
                      Set to False for debugging or if headless detection is an issue.
        """
        self.headless = headless

    @asynccontextmanager
    async def get_browser(self):
        """
        Get a Camoufox browser context.

        Yields an async browser context with anti-detect patches applied.
        """
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            logger.error("Camoufox not installed. Run: pip install camoufox[geoip]")
            raise ImportError("Camoufox not available. Install with: pip install camoufox[geoip]")

        async with AsyncCamoufox(
            headless=self.headless,
            humanize=True,  # Enable human-like behavior
            geoip=True,  # Use GeoIP for realistic location
        ) as browser:
            yield browser

    async def human_delay(self, min_ms: int = 100, max_ms: int = 500) -> None:
        """Add a human-like random delay."""
        delay = random.uniform(min_ms / 1000, max_ms / 1000)
        await asyncio.sleep(delay)

    async def human_mouse_move(self, page, x: int, y: int) -> None:
        """Move mouse in a human-like way with slight variations."""
        steps = random.randint(5, 15)
        await page.mouse.move(x, y, steps=steps)

    async def detect_turnstile(self, page) -> Optional[dict]:
        """
        Detect if page has a Cloudflare Turnstile challenge.

        Returns:
            Dict with 'type' and 'element' if found, None otherwise.
        """
        html = await page.content()

        # Check for various Turnstile indicators
        indicators = [
            "cf-turnstile",
            "turnstile",
            "challenges.cloudflare.com",
            "cf-challenge",
            "verify you are human",
        ]

        for indicator in indicators:
            if indicator.lower() in html.lower():
                # Try to find the interactive element
                selectors = [
                    'iframe[src*="turnstile"]',
                    'iframe[src*="challenges.cloudflare.com"]',
                    ".cf-turnstile",
                    'input[name="cf-turnstile-response"]',
                ]

                for selector in selectors:
                    element = await page.query_selector(selector)
                    if element:
                        return {"type": "turnstile", "element": element, "selector": selector}

                return {"type": "turnstile", "element": None, "selector": None}

        return None

    async def attempt_turnstile_solve(self, page, challenge: dict) -> bool:
        """
        Attempt to solve a Turnstile challenge.

        Args:
            page: Browser page
            challenge: Challenge info from detect_turnstile

        Returns:
            True if challenge appears resolved, False otherwise.
        """
        logger.info("Attempting to solve Turnstile challenge...")

        # If we found an iframe, try to interact with it
        if challenge.get("element"):
            try:
                element = challenge["element"]
                box = await element.bounding_box()

                if box:
                    # Calculate center of element for click
                    x = box["x"] + box["width"] / 2
                    y = box["y"] + box["height"] / 2

                    # Move mouse naturally to element
                    await self.human_mouse_move(page, int(x), int(y))
                    await self.human_delay(200, 500)

                    # Click
                    await page.mouse.click(x, y)
                    await self.human_delay(1000, 2000)

            except Exception as e:
                logger.debug(f"Failed to interact with Turnstile element: {e}")

        # Try clicking checkbox if present
        checkbox_selectors = [
            'input[type="checkbox"]',
            '.checkbox',
            '[role="checkbox"]',
        ]

        for selector in checkbox_selectors:
            try:
                checkbox = await page.query_selector(selector)
                if checkbox:
                    box = await checkbox.bounding_box()
                    if box:
                        x = box["x"] + box["width"] / 2
                        y = box["y"] + box["height"] / 2
                        await self.human_mouse_move(page, int(x), int(y))
                        await self.human_delay(100, 300)
                        await page.mouse.click(x, y)
                        await self.human_delay(1000, 2000)
                        break
            except Exception:
                pass

        # Wait for potential redirect or challenge resolution
        await self.human_delay(2000, 4000)

        # Check if challenge is still present
        new_challenge = await self.detect_turnstile(page)
        if not new_challenge:
            logger.info("Turnstile challenge appears to be resolved")
            return True

        logger.warning("Turnstile challenge still present after attempt")
        return False

    async def navigate_with_turnstile_bypass(
        self,
        page,
        url: str,
        max_attempts: int = 3,
        wait_timeout: int = 30000,
    ) -> str:
        """
        Navigate to URL and attempt to bypass Turnstile if present.

        Args:
            page: Browser page
            url: URL to navigate to
            max_attempts: Maximum solve attempts
            wait_timeout: Max time to wait for page load (ms)

        Returns:
            Page HTML content after navigation/challenge resolution.
        """
        logger.info(f"Navigating to {url} with Turnstile bypass")

        await page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout)
        await self.human_delay(1000, 2000)

        # Check for and attempt to solve Turnstile
        for attempt in range(max_attempts):
            challenge = await self.detect_turnstile(page)

            if not challenge:
                logger.info("No Turnstile challenge detected")
                break

            logger.info(f"Turnstile detected, attempt {attempt + 1}/{max_attempts}")

            if await self.attempt_turnstile_solve(page, challenge):
                # Wait for page to fully load after challenge
                await self.human_delay(2000, 4000)
                break

            if attempt < max_attempts - 1:
                # Refresh and try again
                logger.info("Refreshing page for another attempt...")
                await page.reload(wait_until="domcontentloaded")
                await self.human_delay(1000, 2000)

        return await page.content()
