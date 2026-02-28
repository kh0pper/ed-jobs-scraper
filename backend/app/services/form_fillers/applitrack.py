"""Applitrack form filler — handles 88% of all job listings.

Applitrack uses multi-page HTML forms with standard fields plus
district-specific custom questions.
"""

import logging

from app.scrapers.browser import get_browser, human_delay
from app.services.form_filler import BaseFormFiller, register_form_filler

logger = logging.getLogger(__name__)


@register_form_filler("applitrack")
class ApplitrackFormFiller(BaseFormFiller):
    """Fill Applitrack application forms."""

    async def run(self, job, profile, application) -> dict:
        """Navigate to application form and fill all fields."""
        screenshots = []
        form_data = {}

        async with get_browser() as browser:
            page = await browser.new_page()
            try:
                # Navigate to application URL
                await page.goto(job.application_url, wait_until="domcontentloaded", timeout=30000)
                await browser.apply_stealth(page)
                await human_delay(1000, 2000)

                # Detect if we need to click "Apply" first
                apply_btn = await page.query_selector("a[href*='onlineapp'], input[value*='Apply'], button:has-text('Apply')")
                if apply_btn:
                    await apply_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await human_delay(1000, 2000)

                # Process form pages
                page_num = 0
                while page_num < 20:  # Safety limit
                    page_num += 1

                    # Detect and fill fields on current page
                    filled = await self._fill_page_fields(page, profile, application)
                    form_data[f"page_{page_num}"] = filled

                    # Take screenshot
                    ss_path = await self.take_screenshot(
                        page, f"page_{page_num}", str(application.id)
                    )
                    screenshots.append(ss_path)

                    # Look for "Next" / "Continue" button
                    next_btn = await page.query_selector(
                        "input[type='submit'][value*='Next'], "
                        "input[type='submit'][value*='Continue'], "
                        "button:has-text('Next'), "
                        "button:has-text('Continue'), "
                        "input[name='cmdNext']"
                    )

                    if not next_btn:
                        # Check for submit button — we're on the last page
                        submit_btn = await page.query_selector(
                            "input[type='submit'][value*='Submit'], "
                            "button:has-text('Submit')"
                        )
                        if submit_btn:
                            # Take final screenshot and stop — DON'T auto-submit
                            ss_path = await self.take_screenshot(
                                page, "pre_submit", str(application.id)
                            )
                            screenshots.append(ss_path)
                        break

                    await next_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await human_delay(1000, 2000)

            finally:
                await page.close()

        return {"form_data": form_data, "screenshots": screenshots}

    async def submit(self, job, application) -> dict:
        """Click submit on the final page."""
        async with get_browser() as browser:
            page = await browser.new_page()
            try:
                # Navigate back to the form — may need to re-navigate
                await page.goto(job.application_url, wait_until="domcontentloaded", timeout=30000)
                await browser.apply_stealth(page)
                await human_delay(1000, 2000)

                # Find and click submit
                submit_btn = await page.query_selector(
                    "input[type='submit'][value*='Submit'], "
                    "button:has-text('Submit')"
                )
                if submit_btn:
                    await submit_btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await human_delay(2000, 3000)

                ss_path = await self.take_screenshot(
                    page, "submitted", str(application.id)
                )
                return {"screenshot": ss_path}
            finally:
                await page.close()

    async def _fill_page_fields(self, page, profile, application) -> dict:
        """Detect and fill all fields on the current form page."""
        filled = {}

        # Map common Applitrack field names to profile values
        field_map = {
            # Text inputs — name/id patterns → profile values
            "FirstName": profile.full_name.split()[0] if profile.full_name else "",
            "LastName": profile.full_name.split()[-1] if profile.full_name and len(profile.full_name.split()) > 1 else "",
            "Email": profile.email or "",
            "Phone": profile.phone or "",
            "Address": profile.address_line1 or "",
            "City": profile.city or "",
            "State": profile.state or "",
            "Zip": profile.zip_code or "",
        }

        # Fill text inputs
        for field_pattern, value in field_map.items():
            if not value:
                continue

            # Try multiple selector patterns
            for selector in [
                f"input[name*='{field_pattern}' i]",
                f"input[id*='{field_pattern}' i]",
                f"input[placeholder*='{field_pattern}' i]",
            ]:
                el = await page.query_selector(selector)
                if el:
                    current_val = await el.get_attribute("value") or ""
                    if not current_val:
                        await el.fill(value)
                        filled[field_pattern] = value
                    break

        # Upload resume/cover letter if file inputs exist
        if application.resume_pdf_path:
            file_inputs = await page.query_selector_all("input[type='file']")
            for i, file_input in enumerate(file_inputs):
                label = await file_input.evaluate(
                    """el => {
                        const label = el.closest('label') || document.querySelector(`label[for="${el.id}"]`);
                        return label ? label.innerText.toLowerCase() : '';
                    }"""
                )
                if "resume" in label or i == 0:
                    await file_input.set_input_files(application.resume_pdf_path)
                    filled["resume_upload"] = application.resume_pdf_path
                elif "cover" in label and application.cover_letter_pdf_path:
                    await file_input.set_input_files(application.cover_letter_pdf_path)
                    filled["cover_letter_upload"] = application.cover_letter_pdf_path

        # Handle custom/district-specific questions via Z.ai
        await self._answer_custom_questions(page, profile, application, filled)

        return filled

    async def _answer_custom_questions(self, page, profile, application, filled: dict):
        """Use Z.ai to answer district-specific questions."""
        # Find unfilled text areas and text inputs that look like custom questions
        custom_fields = await page.evaluate("""() => {
            const fields = [];
            // Textareas
            document.querySelectorAll('textarea').forEach(el => {
                if (!el.value && el.offsetParent !== null) {
                    const label = el.closest('tr, div, fieldset');
                    const labelText = label ? label.innerText.substring(0, 200) : '';
                    fields.push({
                        type: 'textarea',
                        id: el.id || '',
                        name: el.name || '',
                        label: labelText
                    });
                }
            });
            // Text inputs with labels that look like questions
            document.querySelectorAll('input[type="text"]').forEach(el => {
                if (!el.value && el.offsetParent !== null) {
                    const label = el.closest('tr, div, fieldset');
                    const labelText = label ? label.innerText.substring(0, 200) : '';
                    if (labelText.includes('?') || labelText.length > 50) {
                        fields.push({
                            type: 'text',
                            id: el.id || '',
                            name: el.name || '',
                            label: labelText
                        });
                    }
                }
            });
            return fields;
        }""")

        if not custom_fields:
            return

        try:
            from app.services.zai_client import get_zai_client

            client = get_zai_client()

            for field in custom_fields[:5]:  # Limit to 5 custom questions per page
                if not field["label"].strip():
                    continue

                prompt = (
                    f"You are filling out a job application. Answer this question briefly and professionally.\n\n"
                    f"Question: {field['label']}\n\n"
                    f"Applicant background: {profile.full_name}, "
                    f"currently {profile.work_history[0]['title'] if profile.work_history else 'seeking employment'}. "
                    f"Experience in Texas K-12 education.\n\n"
                    f"Provide only the answer, no explanation."
                )

                response = client.complete(prompt=prompt, temperature=0.5, max_tokens=500)
                answer = response.content.strip()

                # Fill the field
                selector = f"#{field['id']}" if field["id"] else f"[name='{field['name']}']"
                if selector and selector != "#" and selector != "[name='']":
                    el = await page.query_selector(selector)
                    if el:
                        await el.fill(answer)
                        filled[f"custom_{field['id'] or field['name']}"] = answer[:100]

        except Exception as e:
            logger.warning("Failed to answer custom questions: %s", e)
