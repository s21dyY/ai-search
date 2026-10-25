"""
chatgpt_scraper.py
------------------
ChatGPT scraper for https://chatgpt.com/ in either of two modes, chosen at runtime
by which frontend the page loads:

  guest  logged-out page (internally "octane"). Verified 2026-10-22/24 with headless
         runs (local-docs/page-samples/chatgpt-headless/, chatgpt-articles/).
  app    logged-in React app, used when the browser profile holds a session
         (see --login / --profile in scraper_base.cli). Selectors in APP below come
         from the old scraper (history/ChatGPT_Scraper.py) and common testids and
         are NOT yet verified: capture a logged-in page first with
             python local-docs/capture_page_samples.py chatgpt --profile <name>

Guest-page facts (verified):
  input box            textarea[name='prompt']
  submit / stop        button[data-composer-submit]  (aria-label flips between
                       "Send message" and "Stop generating")
  "+" menu             button[aria-label='Add files and more']
  web search toggle    button[data-octane-web-search-toggle]  (aria-pressed)
  web search pill      button[data-octane-web-search-pill]    (visible when on)
  conversation         section[data-web-mobile-conversation] [data-message-role='assistant']
  citations            inline a[href^='http'] in the answer, usually in a card
                       [data-d-component='row'] with a title, a "Source: publisher, date"
                       line and an image button aria-label="Open <page title>".
  No sources panel. The image cards are image-search hits, not the pages the text
  consulted; the logged-in "More" list has no guest equivalent.

Usage (single thread):
    python chatgpt_scraper.py --login --profile mj
    python chatgpt_scraper.py 2026-10-20 --profile mj [--headful] [--limit 5]
    python chatgpt_scraper.py 2026-10-20                 (guest)
"""

from __future__ import annotations

import time
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from scraper_base import BaseScraper, BlockedError, RetryableError, cli, remove_non_bmp

# Selector sets. Each value is an ordered candidate list; the first match wins.
GUEST = dict(
    input=["textarea[name='prompt']"],
    submit=["button[data-composer-submit]"],
    stop=["button[data-composer-submit][aria-label='Stop generating']",
          "span[data-composer-stop-icon]:not([hidden])"],
    assistant=["section[data-web-mobile-conversation] [data-message-role='assistant']",
               "[data-message-role='assistant']"],
    plus_menu=["button[aria-label='Add files and more']"],
    plus_popover=["#octane-mobile-composer-actions-popover"],
    ws_toggle=["button[data-octane-web-search-toggle]"],
    ws_on=["button[data-octane-web-search-pill]"],
    sources_control=[],
    panel_links=[],
)

APP = dict(  # TO VERIFY against a logged-in capture
    input=["div#prompt-textarea"],
    submit=["button[data-testid='send-button']", "button[aria-label='Send prompt']"],
    stop=["button[data-testid='stop-button']", "button[aria-label='Stop streaming']",
          "button[aria-label='Stop generating']"],
    assistant=["[data-message-author-role='assistant']"],
    plus_menu=["button[data-testid='composer-plus-btn']", "button[aria-label='Add files and more']",
               "button[aria-label='Add photos & files']", "button[aria-label='Add photos and files']"],
    plus_popover=["[role='menu']"],
    ws_toggle=["//div[@role='menuitemradio'][contains(normalize-space(.), 'Web search')]",
               "//div[@role='menuitem'][contains(normalize-space(.), 'Web search')]",
               "//div[@role='menuitemradio'][contains(normalize-space(.), 'Search')]",
               "//div[@role='menuitem'][contains(normalize-space(.), 'Search')]",
               "button[aria-label='Search']"],
    ws_on=["button[aria-label='Search'][aria-pressed='true']",
           "//button[contains(@aria-label, 'Search') and @aria-pressed='true']",
           "//form//*[self::button or self::div][contains(normalize-space(.), 'Search') and contains(@class, 'pill')]"],
    sources_control=["button.group\\/footnote", "button[aria-label*='Sources']",
                     "//button[contains(normalize-space(.), 'Sources')]"],
    panel_links=["[data-testid='sources-panel'] a[href]", "[role='dialog'] a[href]", "aside a[href]"],
)


class ChatGPTScraper(BaseScraper):
    name = "chatgpt"
    url = "https://chatgpt.com/"
    login_url = "https://chatgpt.com/auth/login"
    throttle = (20, 30)

    BLOCKED_TEXT = tuple(BaseScraper.BLOCKED_TEXT) + (
        "you've reached our limit",
        "you have reached our limit",
        "reached the message limit",
        "log in to continue",
        "log in or sign up to continue",
        "sign up to continue",
    )
    RETRY_TEXT = ("chat stopped unexpectedly", "something went wrong", "network error")

    # Runs inside the browser on the assistant message element (guest page).
    _EXTRACT_JS = r"""
    const root = arguments[0];
    const clean = u => (u || '').replace(/[?&]utm_source=chatgpt\.com/g, '');
    const txt = el => ((el && (el.innerText || el.textContent)) || '').trim();
    const citations = [], seen = new Set();
    root.querySelectorAll("a[href^='http']").forEach(a => {
      const url = clean(a.href);
      if (!url || seen.has(url)) return;
      seen.add(url);
      const linkText = txt(a);
      let headline = linkText, snippet = '', source = '', imageTitle = '';
      const card = a.closest("[data-d-component='row']");
      if (card) {
        const ps = Array.from(card.querySelectorAll("p[data-d-component='text']")).map(txt).filter(Boolean);
        const body = ps.filter(t => t !== linkText && !/^source:/i.test(t) && !/^\d+\s*[·.]/.test(t));
        if (body.length) { headline = body[0]; snippet = body.slice(1).join(' ').slice(0, 400); }
        const src = ps.find(t => /^source:/i.test(t));
        if (src) source = src.replace(/^source:\s*/i, '');
        const btn = card.querySelector("button[aria-label^='Open ']");
        if (btn) imageTitle = btn.getAttribute('aria-label').replace(/^Open\s+/, '');
      }
      citations.push({url, headline, snippet, source, link_text: linkText, image_title: imageTitle});
    });
    const images = [];
    root.querySelectorAll("button[aria-label^='Open ']").forEach(b => {
      images.push({url: '', headline: b.getAttribute('aria-label').replace(/^Open\s+/, ''), snippet: '', kind: 'image'});
    });
    return {citations, images};
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = "guest"
        self.S = GUEST

    # -- mode ------------------------------------------------------------------

    def _detect_mode(self) -> str:
        if self.exists(APP["input"], visible=False):
            return "app"
        if self.exists(GUEST["input"], visible=False):
            return "guest"
        return ""

    def is_logged_in(self) -> bool:
        return self._detect_mode() == "app"

    # -- steps -----------------------------------------------------------------

    def open_new_chat(self):
        self.driver.uc_open_with_reconnect(self.url, reconnect_time=4)
        ok = self.wait_until(lambda: bool(self._detect_mode()), timeout=20, poll=0.5)
        if not ok:
            self.check_blocked()
            raise RetryableError("no input box on landing page")
        self.mode = self._detect_mode()
        self.S = APP if self.mode == "app" else GUEST
        if self.profile and self.mode == "guest":
            raise BlockedError(f"profile '{self.profile}' is not logged in (guest page loaded); "
                               f"run: python chatgpt_scraper.py --login --profile {self.profile}")
        self.enable_web_search()

    def enable_web_search(self):
        """Turn on the Web search tool so the answer carries sources. Idempotent."""
        S = self.S
        if self.exists(S["ws_on"], visible=True):
            return
        toggle, _ = self.find_first(S["ws_toggle"], visible=True)
        if toggle is None:
            menu, _ = self.find_first(S["plus_menu"], visible=True)
            if menu is None:
                raise RetryableError("web search: '+' menu button not found")
            menu.click()
            time.sleep(0.8)
            toggle, _ = self.find_first(S["ws_toggle"], visible=True)
        if toggle is None:
            raise RetryableError("web search: toggle not found in '+' menu")
        state = (toggle.get_attribute("aria-pressed") or toggle.get_attribute("aria-checked") or "").lower()
        if state != "true":
            toggle.click()
        on = self.wait_until(lambda: self.exists(S["ws_on"], visible=True), timeout=5, poll=0.3)
        if not on:
            if self.mode == "guest":
                raise RetryableError("web search: toggle did not turn on")
            # App mode: the "on" indicator is unverified; continue but say so.
            print("  [chatgpt/app] could not confirm Web search is on; verify APP['ws_on']")
        # Close the menu if it is still open so it does not cover the input.
        pop, _ = self.find_first(S["plus_popover"], visible=True)
        if pop is not None:
            try:
                if self.mode == "guest":
                    self.driver.execute_script("arguments[0].hidePopover && arguments[0].hidePopover()", pop)
                else:
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass

    def ask(self, prompt: str) -> str:
        box, _ = self.find_first(self.S["input"], visible=True)
        if box is None:
            raise RetryableError("input box disappeared")
        box.click()
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.BACKSPACE)
        text = remove_non_bmp(prompt)
        box.send_keys(text)
        request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        box.send_keys(Keys.ENTER)
        time.sleep(0.5)
        # If Enter did not submit, click the send button.
        still = (box.get_attribute("value") or "") if self.mode == "guest" else self._text(box)
        if text[:20] in still:
            btn, _ = self.find_first(self.S["submit"], visible=True)
            if btn is None:
                raise RetryableError("send button not found")
            btn.click()
        return request_time

    def is_generating(self) -> bool:
        return self.exists(self.S["stop"], visible=True)

    def _last_assistant(self):
        el, _ = self.find_first(self.S["assistant"], visible=False, last=True)
        return el

    def _markdown_el(self, el):
        """App mode: the markdown body inside the assistant message, else the message."""
        if self.mode == "app":
            try:
                inner = el.find_elements(By.CSS_SELECTOR, ".markdown")
                if inner:
                    return inner[-1]
            except Exception:
                pass
        return el

    def answer_text(self) -> str:
        el = self._last_assistant()
        if el is None:
            return ""
        text = self._text(self._markdown_el(el))
        return text.removeprefix("ChatGPT said:").strip()

    def extract_answer(self) -> str:
        el = self._last_assistant()
        if el is None:
            return ""
        return self.driver.execute_script(
            "const c = arguments[0].cloneNode(true);"
            "c.querySelectorAll('h4').forEach(h => h.remove());"
            "return c.innerHTML;", self._markdown_el(el))

    # -- sources -----------------------------------------------------------------

    def _extract_guest(self) -> dict:
        el = self._last_assistant()
        if el is None:
            return {"citations": [], "images": []}
        try:
            return self.driver.execute_script(self._EXTRACT_JS, el) or {"citations": [], "images": []}
        except Exception as e:
            raise RetryableError(f"citation extraction failed: {e}") from e

    def has_sources(self) -> bool:
        if self.mode == "guest":
            d = self._extract_guest()
            return bool(d["citations"] or d["images"])
        if self.exists(self.S["sources_control"], visible=True):
            return True
        el = self._last_assistant()
        return el is not None and bool(el.find_elements(By.CSS_SELECTOR, "a[href*='utm_source=chatgpt.com']"))

    def extract_sources(self) -> tuple[list, list]:
        if self.mode == "guest":
            d = self._extract_guest()
            return d["citations"], d["images"]

        # App mode: open the sources panel, read "Citations" and "More" like the old scraper.
        citations: list = []
        more: list = []
        control, _ = self.find_first(self.S["sources_control"], visible=True)
        if control is not None:
            try:
                control.click()
                time.sleep(2)
                citations = self._links_in_section("Citations")
                more = self._links_in_section("More")
                if not citations:
                    for sel in self.S["panel_links"]:
                        links = self._find_all(sel)
                        if links:
                            citations = self._links_to_sources(links)
                            break
            except Exception as e:
                print(f"  [chatgpt/app] sources panel failed: {e}")
        if not citations:
            el = self._last_assistant()
            if el is not None:
                citations = self._links_to_sources(el.find_elements(By.CSS_SELECTOR, "a[href*='utm_source=chatgpt.com']"))
        return citations, more

    def _links_in_section(self, header_text: str) -> list:
        headers = self._find_all(f"//li[normalize-space(text())='{header_text}']")
        if not headers:
            return []
        try:
            section = headers[0].find_element(By.XPATH, "..")
            return self._links_to_sources(section.find_elements(By.TAG_NAME, "a"))
        except Exception:
            return []

    def _links_to_sources(self, links) -> list:
        out, seen = [], set()
        for a in links:
            try:
                url = a.get_attribute("href") or ""
            except Exception:
                continue
            url = url.replace("?utm_source=chatgpt.com", "").replace("&utm_source=chatgpt.com", "")
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            headline, snippet = "", ""
            try:
                texts = [d.text.strip() for d in a.find_elements(By.TAG_NAME, "div") if d.text.strip()]
                if len(texts) >= 2:
                    headline, snippet = texts[1], (texts[2] if len(texts) > 2 else "")
                elif texts:
                    headline = texts[0]
                else:
                    headline = (a.text or a.get_attribute("aria-label") or a.get_attribute("title") or "").strip()
            except Exception:
                pass
            out.append({"url": url, "headline": headline, "snippet": snippet})
        return out

    def check_blocked(self):
        super().check_blocked()
        text = self.page_text_for_block_check()
        for frag in self.RETRY_TEXT:
            if frag in text:
                raise RetryableError(f"page says: {frag!r}")


if __name__ == "__main__":
    cli(ChatGPTScraper)
