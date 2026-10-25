"""
scraper/perplexity_scraper.py
---------------------
Perplexity scraper, logged out (guest). Default "Search" mode always searches the
web, so no toggle is needed.

Selectors are carried over from history/perplexity_scraper.py, which worked as of
the last commit. The stop-button selectors are guesses; if none matches,
wait_for_answer() still works because it also relies on answer text stability.
Verify against local-docs/page-samples/perplexity/ once captured.

Usage (single thread):
    python -m scraper.perplexity_scraper 2026-10-20 [--headful] [--limit 5]
"""

from __future__ import annotations

import re
import time
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from .scraper_base import BaseScraper, BlockedError, RetryableError, cli, remove_non_bmp


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
    # Verified 2026-10-25 (logged in): stop button aria-label "Stop response (Esc)";
    # the answer is split over several .prose blocks; inline citations carry
    # data-pplx-citation-url; the "N sources" button opens a scroll list of all sources.
    STOP = [
        "button[aria-label^='Stop response']",
        "button[aria-label='Stop']",
        "button[aria-label='Stop generating']",
    ]
    SOURCES_BUTTON = [
        "//button[contains(normalize-space(.), 'sources')]",
        "//button[.//div[contains(normalize-space(), 'sources')]]",
        "[data-testid='answer-mode-tabs-tab-sources']",
    ]
    SOURCE_LIST_LINKS = "[data-radix-scroll-area-viewport] a[href^='http']"
    CITATION_ATTR = "data-pplx-citation-url"
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
        self.dismiss_popups()

    # Promotional modals and the cookie banner cover the input box (seen 2026-10-25:
    # "Computer is available for you to try" with "Maybe later"). Close them.
    POPUP_BUTTONS = [
        "//button[normalize-space(.)='Maybe later']",
        "//button[normalize-space(.)='Not now']",
        "//button[normalize-space(.)='No thanks']",
        "//button[normalize-space(.)='Decline optional']",
        "//button[normalize-space(.)='Got it']",
        "//button[normalize-space(.)='Dismiss']",
    ]

    def dismiss_popups(self, rounds: int = 3):
        for _ in range(rounds):
            btn, _ = self.find_first(self.POPUP_BUTTONS, visible=True)
            if btn is None:
                return
            try:
                self.driver.execute_script("arguments[0].click()", btn)
            except Exception:
                pass
            time.sleep(0.6)

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
        self.dismiss_popups()
        box, _ = self.find_first(self.INPUT, visible=True)
        if box is None:
            raise RetryableError("input box disappeared")
        try:
            box.click()
        except Exception:                        # something still overlays the box
            self.dismiss_popups()
            self.driver.execute_script("arguments[0].focus()", box)
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.BACKSPACE)
        box.send_keys(remove_non_bmp(prompt))
        request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        box.send_keys(Keys.ENTER)
        return request_time

    def is_generating(self) -> bool:
        return self.exists(self.STOP, visible=True)

    def _answer_els(self):
        return self._find_all(".prose")

    def answer_text(self) -> str:
        return "\n".join(t for t in (self._text(e).strip() for e in self._answer_els()) if t)

    def extract_answer(self) -> str:
        parts = []
        for e in self._answer_els():
            try:
                parts.append(e.get_attribute("innerHTML") or "")
            except Exception:
                pass
        return remove_non_bmp("\n".join(parts))

    def check_blocked(self):
        super().check_blocked()
        ans = self.answer_text().lower()
        for frag in self.ANSWER_BLOCKED_TEXT:
            if frag in ans:
                raise BlockedError(f"answer says: {frag!r} (sign-in wall)")

    def has_sources(self) -> bool:
        return self.exists(self.SOURCES_BUTTON, visible=True) or bool(self._find_all(f"[{self.CITATION_ATTR}]"))

    def extract_sources(self) -> tuple[list, list]:
        """(citations, search_results): inline cited URLs, and the full 'N sources' list."""
        citations, seen = [], set()
        for el in self._find_all(f"[{self.CITATION_ATTR}]"):
            url = el.get_attribute(self.CITATION_ATTR) or ""
            if url.startswith("http") and url not in seen:
                seen.add(url)
                citations.append({"url": url, "headline": "", "snippet": "",
                                  "publisher": self._text(el).split("+")[0].strip(), "kind": "inline"})

        self._sources_expected = None
        self._search_status = "none"
        btn, _ = self.find_first(self.SOURCES_BUTTON, visible=True)
        if btn is None:
            return citations, []
        m = re.search(r"(\d+)\s+sources?", self._text(btn))
        self._sources_expected = int(m.group(1)) if m else None
        try:
            btn.click()
        except Exception:
            self.driver.execute_script("arguments[0].click()", btn)
        self.wait_until(lambda: len(self._source_links()) >= (self._sources_expected or 1), 6, 0.3)

        results, seen = [], set()
        for a in self._source_links():
            try:
                url = a.get_attribute("href") or ""
                parts = [t.strip() for t in (a.text or "").split("\n") if t.strip()]
            except Exception:
                continue
            if url in seen:
                continue
            seen.add(url)
            results.append({"url": url, "site": parts[0] if parts else "",
                            "headline": parts[1] if len(parts) > 1 else "",
                            "snippet": parts[2] if len(parts) > 2 else "", "kind": "source"})
        self._search_status = "ok" if results else "capture_failed"
        for c in citations:                      # fill titles of cited pages from the list
            hit = next((r for r in results if r["url"] == c["url"]), None)
            if hit:
                c["headline"], c["snippet"] = hit["headline"], hit["snippet"]
        return citations, results

    def _source_links(self):
        return [a for a in self._find_all(self.SOURCE_LIST_LINKS)
                if "perplexity.ai" not in (a.get_attribute("href") or "") and self._displayed(a)]

    def collect_extras(self, result):
        result.search_results_status = getattr(self, "_search_status", "none")
        exp = getattr(self, "_sources_expected", None)
        if exp is not None and len(result.search_results) < exp:
            result.search_results_status = f"partial ({len(result.search_results)}/{exp})"


if __name__ == "__main__":
    cli(PerplexityScraper)
