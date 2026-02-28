"""Form filler base class and registry.

Registry pattern matching the scraper registry — each platform
registers its form filler via @register_form_filler().
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Registry of platform → FormFiller class
_form_fillers: dict[str, type] = {}


def register_form_filler(platform: str):
    """Decorator to register a form filler class for a platform."""
    def decorator(cls):
        _form_fillers[platform] = cls
        logger.debug("Registered form filler: %s -> %s", platform, cls.__name__)
        return cls
    return decorator


def get_form_filler(platform: str):
    """Get an instance of the form filler for a platform, or None."""
    cls = _form_fillers.get(platform)
    if cls is None:
        return None
    return cls()


class BaseFormFiller:
    """Base class for platform-specific form fillers."""

    async def run(self, job, profile, application) -> dict:
        """Fill the application form.

        Args:
            job: JobPosting ORM object
            profile: ApplicantProfile ORM object
            application: Application ORM object

        Returns:
            dict with keys: form_data (dict), screenshots (list of paths)
        """
        raise NotImplementedError

    async def submit(self, job, application) -> dict:
        """Submit the filled application.

        Returns:
            dict with key: screenshot (path to final confirmation screenshot)
        """
        raise NotImplementedError

    async def take_screenshot(self, page, step_name: str, application_id: str) -> str:
        """Take a screenshot and save to disk."""
        screenshot_dir = os.environ.get("APPLY_SCREENSHOT_DIR", "/app/data/screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{application_id}_{step_name}_{timestamp}.png"
        filepath = os.path.join(screenshot_dir, filename)

        await page.screenshot(path=filepath, full_page=True)
        logger.info("Screenshot saved: %s", filepath)
        return filepath

    async def fill_text_field(self, page, selector: str, value: str):
        """Fill a text input field."""
        el = await page.query_selector(selector)
        if el:
            await el.click()
            await el.fill(value)

    async def select_dropdown(self, page, selector: str, value: str):
        """Select an option from a dropdown."""
        await page.select_option(selector, label=value)

    async def upload_file(self, page, selector: str, file_path: str):
        """Upload a file via file input."""
        el = await page.query_selector(selector)
        if el:
            await el.set_input_files(file_path)

    async def wait_and_click(self, page, selector: str, timeout: int = 5000):
        """Wait for element and click it."""
        await page.wait_for_selector(selector, timeout=timeout)
        await page.click(selector)


# Import form fillers to trigger registration
try:
    import app.services.form_fillers  # noqa: F401
except ImportError:
    pass
