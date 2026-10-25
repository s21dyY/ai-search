"""
perplexity_scraper.py
---------------------
Perplexity scraper, logged out (guest). Default "Search" mode always searches the
web, so no toggle is needed.

Selectors are carried over from history/perplexity_scraper.py, which worked as of
the last commit. The stop-button selectors are guesses; if none matches,
wait_for_answer() still works because it also relies on answer text stability.
Verify against local-docs/page-samples/perplexity/ once captured.

Usage (single thread):
    python perplexity_scraper.py 2026-10-20 [--headful] [--limit 5]
"""

from __future__ import annotations

import re
import time
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from scraper_base import BaseScraper, BlockedError, RetryableError, cli, remove_non_bmp


class PerplexityScraper(BaseScraper):
    name = "perplexity"
    url = "https://www.perplexity.ai"
    login_url = "https://www.perplexity.ai"      # use the "Sign In" button; email code login works
    throttle = (30, 35)

    def is_logged_in(self) -> bool:
        """Logged-in pages have no 'Sign In' control in the sidebar."""
        if not self.exists(self.INPUT, visible=False):
            return False
        text = self.body_text()
        return "sign in" not in text and "sign up" not in text

    INPUT = ["#ask-input", "textarea[placeholder*='Ask']", "div[contenteditable='true']"]
    ANSWER = [".prose"]
    STOP = [                                   # VERIFY
        "button[aria-label='Stop']",
        "button[aria-label='Stop generating']",
        "button[data-testid='stop-generating-button']",
    ]
    SOURCES_BUTTON = [
        "//button[.//div[contains(normalize-space(), 'sources')]]",
        "[data-testid='answer-mode-tabs-tab-sources']",
        "[data-testid='answer-mode-tabs-tab-links']",        # 2026-10 UI shows a "Links" tab
        "//button[normalize-space()='Links']",
    ]
    # Seen 2026-10-22 on a headless guest run: the "answer" was this sentence and a
    # "Sign in to continue using Perplexity" modal appeared.
    ANSWER_BLOCKED_TEXT = ("sign up and repeat your request", "sign in to continue")
    SOURCES_COUNT = ["//button[.//div[contains(normalize-space(), 'sources')]]//div[contains(normalize-space(), 'sources')]"]
    SOURCE_LINKS = [
        "a.group.flex.size-full.cursor-pointer.items-stretch",   # old working selector
        "[data-testid='answer-mode-tabs-tabpanel-sources'] a[href]",
    ]

    BLOCKED_TEXT = tuple(BaseScraper.BLOCKED_TEXT) + (
        "sign in to continue",
        "you've hit your limit",
    )

    # -- steps ---------------------------------------------------------------

    def open_new_chat(self):
        self.driver.uc_open_with_reconnect(self.url, reconnect_time=4)
        ok = self.wait_until(lambda: self.exists(self.INPUT), timeout=20, poll=0.5)
        if not ok:
            self.check_blocked()
            if len(self.body_text()) < 50:
                raise RetryableError("blank_page")
            raise RetryableError("no input box on landing page")
        if self.profile and not self.is_logged_in():
            self.ensure_logged_in()                  # automatic login from accounts.toml
            self.wait_until(lambda: self.exists(self.INPUT), timeout=20, poll=0.5)

    def click_continue_with_google(self):
        """Sign In -> 'Continue with Google' (verified 2026-10-25; same window, no popup)."""
        self.driver.uc_open_with_reconnect(self.url, reconnect_time=4)
        time.sleep(2)
        sign_in, _ = self.find_first(["//button[normalize-space(.)='Sign In']",
                                      "//button[contains(normalize-space(.), 'Sign in')]"], visible=True)
        if sign_in is not None:
            sign_in.click()
            time.sleep(2)
        btn, _ = self.find_first(["//button[contains(normalize-space(.), 'Continue with Google')]"], visible=True)
        if btn is None:
            self.check_blocked()
            raise RetryableError("login dialog: 'Continue with Google' not found")
        before = set(self.driver.window_handles)
        btn.click()
        time.sleep(3)
        new = set(self.driver.window_handles) - before
        if new:                                      # in case Perplexity switches to a popup
            self.driver.switch_to.window(new.pop())
        self.wait_until(lambda: "accounts.google.com" in self.driver.current_url, timeout=20, poll=0.5)

    def ask(self, prompt: str) -> str:
        box, _ = self.find_first(self.INPUT, visible=True)
        if box is None:
            raise RetryableError("input box disappeared")
        box.click()
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.BACKSPACE)
        box.send_keys(remove_non_bmp(prompt))
        request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        box.send_keys(Keys.ENTER)
        return request_time

    def is_generating(self) -> bool:
        return self.exists(self.STOP, visible=True)

    def _answer_el(self):
        el, _ = self.find_first(self.ANSWER, visible=False, last=True)
        return el

    def answer_text(self) -> str:
        el = self._answer_el()
        return self._text(el).strip() if el is not None else ""

    def extract_answer(self) -> str:
        el = self._answer_el()
        if el is None:
            return ""
        try:
            return remove_non_bmp(el.get_attribute("innerHTML") or "")
        except Exception:
            return ""

    def check_blocked(self):
        super().check_blocked()
        ans = self.answer_text().lower()
        for frag in self.ANSWER_BLOCKED_TEXT:
            if frag in ans:
                raise BlockedError(f"answer says: {frag!r} (sign-in wall)")

    def has_sources(self) -> bool:
        return self.exists(self.SOURCES_BUTTON, visible=True)

    def extract_sources(self) -> tuple[list, list]:
        btn, _ = self.find_first(self.SOURCES_BUTTON, visible=True)
        if btn is None:
            return [], []
        try:
            btn.click()
        except Exception as e:
            raise RetryableError(f"sources button not clickable: {e}") from e
        time.sleep(2)

        expected = None
        count_el, _ = self.find_first(self.SOURCES_COUNT, visible=True)
        if count_el is not None:
            m = re.match(r"\s*(\d+)", self._text(count_el))
            if m:
                expected = int(m.group(1))

        links = []
        for sel in self.SOURCE_LINKS:
            links = self._find_all(sel)
            if links:
                break
        if expected is not None:
            links = links[:expected]

        out, seen = [], set()
        for a in links:
            try:
                href = a.get_attribute("href") or ""
                text = (a.text or "").strip()
            except Exception:
                continue
            # The old scraper only kept the site name shown on the card.
            site = text.split("/")[0].strip() if text else ""
            key = href or site
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({"url": href or site, "headline": text, "snippet": ""})
        return out, []


if __name__ == "__main__":
    cli(PerplexityScraper)
