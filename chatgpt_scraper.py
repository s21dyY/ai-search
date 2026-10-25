"""
chatgpt_scraper.py
------------------
ChatGPT scraper for https://chatgpt.com/ in either of two modes, chosen at runtime
by which frontend the page loads:

  guest  logged-out page (internally "octane"). Verified 2026-10-22/24 with headless
         runs (local-docs/page-samples/chatgpt-headless/, chatgpt-articles/).
  app    logged-in React app, used when the browser profile holds a session
         (see --login / --profile in scraper_base.cli). Verified 2026-10-25 with a
         free account (local-docs/page-samples/chatgpt-test/): composer is
         div.ProseMirror[role='textbox'], send/stop buttons are aria-label "Send" /
         "Stop", Web search is a row in the "+" menu, the answer lives in
         [data-markdown-text-style='assistant-message'] and the turn wrapper gets
         data-talvt-turn-state='complete'. The old selectors (#prompt-textarea,
         .markdown, data-testid, button.group/footnote, Citations/More panel) no
         longer exist. Both modes render the same card layout, so one extractor
         serves both.

Citations in both modes come from two places:
  cards     inline a[href] with a title / "Source:" line (JS extractor below)
  popovers  publisher pills inside span[data-d-component='popover-trigger']; hovering
            shows the cited pages (publisher, title, date, favicon domain) and each
            entry opens its page via window.open(url), which the scraper stubs to
            read the URL without opening a tab.

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

import json
import re
import time
from datetime import datetime
from urllib.parse import unquote

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from scraper_base import BaseScraper, BlockedError, RetryableError, cli, normalize_url, remove_non_bmp

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

APP = dict(  # input + plus_menu verified 2026-10-25 (page-samples/chatgpt-test); rest TO VERIFY
    input=["div.ProseMirror[role='textbox']", "div#prompt-textarea"],
    submit=["form button[aria-label='Send']", "button[aria-label='Send prompt']",
            "button[data-testid='send-button']"],
    stop=["form button[aria-label='Stop']", "button[data-testid='stop-button']",
          "button[aria-label='Stop streaming']"],
    # Verified 2026-10-25: assistant text lives in data-markdown-text-style='assistant-message';
    # the turn wrapper carries data-talvt-turn-state='complete' when generation is done.
    assistant=["[data-markdown-text-style='assistant-message']",
               "[data-content-search-unit-key$=':assistant']",
               "[data-message-author-role='assistant']"],
    plus_menu=["button[data-testid='composer-plus-btn']", "button[aria-label='Add files and more']",
               "button[aria-label='Add photos & files']", "button[aria-label='Add photos and files']"],
    plus_popover=["button[aria-label='Add files and more'][data-state='open']"],
    # "+" menu rows are plain buttons with data-list-navigation-item (verified 2026-10-25).
    ws_toggle=["//button[@data-list-navigation-item][contains(normalize-space(.), 'Web search')]",
               "//div[@role='menuitemradio'][contains(normalize-space(.), 'Web search')]",
               "//div[@role='menuitem'][contains(normalize-space(.), 'Web search')]"],
    # Indicator that Web search is active in the composer: TO VERIFY.
    ws_on=["//form//button[contains(@aria-label, 'Web search')]",
           "//form//button[contains(@aria-label, 'Remove') and contains(normalize-space(.), 'Search')]",
           "//form//*[self::button or self::span or self::div][normalize-space(.)='Search' and not(ancestor::*[@role='menu'])]",
           "//form//*[contains(normalize-space(.), 'Web search') and not(self::script)]"],
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

    def enable_web_search(self, attempts: int = 3):
        """Turn on the Web search tool so the answer carries sources. Idempotent.

        The app sometimes renders the '+' menu with 'Web search' greyed out (feature
        config not loaded; the sidebar then also says 'Projects couldn't be loaded').
        In that case reload the page and try again.
        """
        S = self.S
        if self.exists(S["ws_on"], visible=True):
            return
        toggle = None
        for attempt in range(attempts):
            toggle, _ = self.find_first(S["ws_toggle"], visible=True)
            if toggle is None:
                menu, _ = self.find_first(S["plus_menu"], visible=True)
                if menu is None:
                    raise RetryableError("web search: '+' menu button not found")
                menu.click()
                time.sleep(1.0)
                toggle, _ = self.find_first(S["ws_toggle"], visible=True)
            if toggle is not None:
                break
            greyed = self.exists(["//span[normalize-space(.)='Web search']"], visible=True)
            print(f"  [chatgpt/{self.mode}] web search item {'disabled' if greyed else 'missing'}; "
                  f"reloading ({attempt + 1}/{attempts})")
            self._close_stray_dialogs()
            self.driver.uc_open_with_reconnect(self.url, reconnect_time=4)
            self.wait_until(lambda: bool(self._detect_mode()), timeout=20, poll=0.5)
            time.sleep(2)
            if self.exists(S["ws_on"], visible=True):
                return
        if toggle is None:
            raise RetryableError("web search: toggle not found or disabled in '+' menu")
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

    def _close_stray_dialogs(self):
        """App mode can leave a dialog or menu open that covers the composer."""
        if self.exists(["[role='dialog'][data-state='open']", "[role='menu']"], visible=True):
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(0.4)
            except Exception:
                pass

    def _ask(self, prompt: str) -> str:
        self._close_stray_dialogs()
        box, _ = self.find_first(self.S["input"], visible=True)
        if box is None:
            raise RetryableError("input box disappeared")
        try:
            box.click()
        except Exception:
            # Something overlays the box; focus it directly instead.
            self.driver.execute_script("arguments[0].focus(); arguments[0].click && arguments[0].click();", box)
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

    # Publisher pills ("Reuters", "AP News +1") inside the answer are popover triggers.
    # Hovering one opens a radix popover (verified 2026-10-25) listing the cited pages as
    # buttons: aria-label "Open <publisher>", a favicon img whose src has domain=<site>,
    # a title span and a date span. No URL is in the DOM; clicking opens the page.
    POPOVER_TRIGGER = "span[data-d-component='popover-trigger']"
    POPOVER_ENTRIES = [
        "[data-radix-popper-content-wrapper] button[data-d-component='pressable']",
        "[role='dialog'][data-state='open'] button[data-d-component='pressable']",
    ]
    resolve_popover_urls = True     # click each entry to read the real URL (slower)
    popover_time_budget = 120       # s, per answer

    _DATE_RE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")

    def _hover(self, el):
        from selenium.webdriver.common.action_chains import ActionChains
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'})", el)
        ActionChains(self.driver).move_to_element(el).perform()

    def _unhover(self):
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
        time.sleep(0.2)

    def _popover_entry_buttons(self):
        for sel in self.POPOVER_ENTRIES:
            btns = [b for b in self._find_all(sel) if self._displayed(b)]
            if btns:
                return btns
        return []

    def _read_popover_entry(self, b) -> dict:
        publisher = (b.get_attribute("aria-label") or "").removeprefix("Open ").strip()
        domain = ""
        imgs = b.find_elements(By.CSS_SELECTOR, "img[src*='favicons?domain=']")
        if imgs:
            m = re.search(r"domain=([^&]+)", imgs[0].get_attribute("src") or "")
            if m:
                domain = normalize_url(unquote(m.group(1))).split("/")[0]
        spans = [t for t in (x.text.strip() for x in b.find_elements(By.CSS_SELECTOR, "span[data-d-component='text']")) if t]
        title = next((t for t in spans if t != publisher and not self._DATE_RE.match(t)), "")
        date = next((t for t in spans if self._DATE_RE.match(t)), "")
        return {"url": "", "domain": domain, "publisher": publisher, "headline": title,
                "snippet": "", "date": date, "kind": "popover"}

    # Popover entries open their page with window.open(url). Stub it in the page so a
    # click records the URL instead of opening a tab (verified 2026-10-25).
    _STUB_OPEN_JS = """
      if (!window.__origOpen) { window.__origOpen = window.open; }
      window.__opens = [];
      window.open = function(u) { window.__opens.push(String(u)); return null; };
    """
    _RESTORE_OPEN_JS = "if (window.__origOpen) { window.open = window.__origOpen; } window.__opens = [];"

    def _resolve_entry_url(self, btn, timeout: float = 3) -> str:
        """Click a popover entry with window.open stubbed and return the recorded URL."""
        self.driver.execute_script("window.__opens = [];")
        btn.click()
        end = time.time() + timeout
        while time.time() < end:
            opens = self.driver.execute_script("return window.__opens || [];")
            if opens:
                return str(opens[-1])
            time.sleep(0.2)
        return ""

    def _collect_popover_sources(self, max_pills: int = 30) -> list:
        """Hover each citation pill in the last answer and read its popover entries."""
        el = self._last_assistant()
        if el is None:
            return []
        out: list = []
        seen: set = set()
        started = time.time()
        try:
            triggers = [t for t in el.find_elements(By.CSS_SELECTOR, self.POPOVER_TRIGGER)
                        if t.find_elements(By.CSS_SELECTOR, "[data-pill]") and self._displayed(t)]
        except Exception:
            return []
        if self.resolve_popover_urls:
            self.driver.execute_script(self._STUB_OPEN_JS)
        try:
            for t in triggers[:max_pills]:
                if time.time() - started > self.popover_time_budget:
                    print("  [chatgpt] popover time budget exhausted")
                    break
                try:
                    self._hover(t)
                    self.wait_until(lambda: bool(self._popover_entry_buttons()), 2.5, 0.2)
                    entries = [self._read_popover_entry(b) for b in self._popover_entry_buttons()]
                except Exception:
                    self._unhover()
                    continue
                for i, e in enumerate(entries):
                    key = (e["domain"], e["headline"].lower())
                    if key in seen or not (e["domain"] or e["headline"]):
                        continue
                    seen.add(key)
                    if self.resolve_popover_urls:
                        try:
                            btns = self._popover_entry_buttons()
                            if i >= len(btns):                 # popover closed; reopen it
                                self._hover(t)
                                self.wait_until(lambda: len(self._popover_entry_buttons()) > i, 2.5, 0.2)
                                btns = self._popover_entry_buttons()
                            if i < len(btns):
                                url = self._resolve_entry_url(btns[i])
                                e["url"] = url.replace("?utm_source=chatgpt.com", "").replace("&utm_source=chatgpt.com", "")
                        except Exception as ex:
                            print(f"  [chatgpt] url resolve failed for {e['publisher']!r}: {str(ex)[:80]}")
                    out.append(e)
                self._unhover()
        finally:
            if self.resolve_popover_urls:
                try:
                    self.driver.execute_script(self._RESTORE_OPEN_JS)
                except Exception:
                    pass
        return out

    def has_sources(self) -> bool:
        d = self._extract_guest()
        if d["citations"] or d["images"]:
            return True
        el = self._last_assistant()
        return el is not None and bool(el.find_elements(By.CSS_SELECTOR, f"{self.POPOVER_TRIGGER} [data-pill]"))

    def extract_sources(self) -> tuple[list, list]:
        """(citations, search_results). Citations come from the page (cards + popovers);
        search results come from the conversation response the browser already received."""
        d = self._extract_guest()
        citations = d["citations"]
        self._last_images = d["images"]
        seen = {normalize_url(c["url"]) for c in citations}
        for s in self._collect_popover_sources():
            key = normalize_url(s["url"]) if s["url"] else f"{s['domain']}|{s['headline'].lower()}"
            if key not in seen:
                seen.add(key)
                citations.append(s)
        return citations, self._stream_search_results()

    def collect_extras(self, result):
        result.images = getattr(self, "_last_images", [])
        result.search_results_status = getattr(self, "_search_status", "capture_failed")
        if not result.search_results and result.search_results_status == "n/a":
            result.search_results = self._stream_search_results()
            result.search_results_status = self._search_status

    # -- search results from the conversation response ----------------------------
    #
    # The page receives the model's web-search results in its own conversation
    # response and hides them after rendering. We wrap window.fetch in the page so a
    # copy of those responses is kept, then parse them after the answer is complete.
    # No extra request is made. Verified 2026-10-25:
    #   guest  NDJSON  /unauth-mweb/conversation/updates
    #          status.reasoning.items[].searchSources.groups[].entries[] {url,title,attribution}
    #   app    SSE     /backend-api/f/conversation  and the full conversation JSON
    #          /backend-api/conversations/<id>: messages[].metadata.search_result_groups[].entries[]
    #          {url,title,snippet,pub_date,attribution}

    _TAP_URL_RE = r"/conversation/updates|/backend-api/f/conversation|/backend-api/conversations/[0-9a-f-]{20,}"

    _TAP_JS = r"""
    (() => {
      window.__tap = [];
      if (window.__tapInstalled) return true;
      window.__tapInstalled = true;
      const re = new RegExp(arguments[0]);
      const orig = window.fetch;
      window.fetch = async function(...args) {
        const resp = await orig.apply(this, args);
        try {
          const url = (args[0] && args[0].url) || String(args[0]);
          if (re.test(url) && resp.body) {
            const rec = {url: url.slice(0, 300), body: '', done: false};
            window.__tap.push(rec);
            const reader = resp.clone().body.getReader();
            const dec = new TextDecoder();
            (async () => {
              try {
                for (;;) {
                  const {done, value} = await reader.read();
                  if (done) break;
                  if (rec.body.length < 8000000) rec.body += dec.decode(value, {stream: true});
                }
              } catch (e) { rec.err = String(e); }
              rec.done = true;
            })();
          }
        } catch (e) {}
        return resp;
      };
      return true;
    })();
    """

    def _install_tap(self):
        try:
            self.driver.execute_script(self._TAP_JS, self._TAP_URL_RE)
            self._tap_ok = True
        except Exception as e:
            self._tap_ok = False
            print(f"  [chatgpt] could not install response tap: {str(e)[:100]}")

    def _stream_search_results(self, wait: float = 6) -> list:
        """Parse search results out of the tapped responses for the current turn."""
        if getattr(self, "_search_cache", None) is not None:
            return self._search_cache
        self._search_status = "capture_failed"
        if not getattr(self, "_tap_ok", False):
            self._search_cache = []
            return []

        def records():
            try:
                return self.driver.execute_script("return window.__tap || [];") or []
            except Exception:
                return []

        # Wait for the streams to finish; in app mode the full conversation JSON arrives
        # shortly after the answer, so give it a moment.
        end = time.time() + wait
        recs = records()
        while time.time() < end:
            recs = records()
            all_done = recs and all(r.get("done") for r in recs)
            have_full = any(re.search(r"/backend-api/conversations/", r["url"]) for r in recs)
            if all_done and (self.mode == "guest" or have_full):
                break
            time.sleep(0.5)

        if not recs:
            self._search_cache = []
            return []
        results = parse_search_results([r.get("body", "") for r in recs])
        self._search_status = "ok" if results else "none"
        self._search_cache = results
        return results

    def ask(self, prompt: str) -> str:
        self._search_cache = None
        self._search_status = "capture_failed"
        self._last_images = []
        self._install_tap()          # also clears records from earlier turns
        return self._ask(prompt)

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


# ----------------------------------------------------------------------------
# Search-result parser for tapped conversation responses
# ----------------------------------------------------------------------------

def _json_docs(body: str):
    """Yield JSON objects from a body that is plain JSON, NDJSON, or SSE."""
    body = (body or "").strip()
    if not body:
        return
    try:
        yield json.loads(body)
        return
    except Exception:
        pass
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]" or line[0] not in "{[":
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def _walk_entries(o):
    """Yield search-result entries from both known shapes, wherever they are nested."""
    if isinstance(o, dict):
        ss = o.get("searchSources")
        if isinstance(ss, dict):
            for g in ss.get("groups") or []:
                for e in (g or {}).get("entries") or []:
                    yield e, (g or {}).get("domain", "")
        srg = o.get("search_result_groups")
        if isinstance(srg, list):
            for g in srg:
                for e in (g or {}).get("entries") or []:
                    yield e, (g or {}).get("domain", "")
        for v in o.values():
            if isinstance(v, (dict, list)):
                yield from _walk_entries(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_entries(v)


def parse_search_results(bodies: list) -> list:
    out, seen = [], set()
    for body in bodies:
        for doc in _json_docs(body):
            for e, group_domain in _walk_entries(doc):
                if not isinstance(e, dict):
                    continue
                url = (e.get("url") or "").replace("?utm_source=chatgpt.com", "").replace("&utm_source=chatgpt.com", "")
                if not url.startswith("http"):
                    continue
                key = normalize_url(url)
                if key in seen:
                    continue
                seen.add(key)
                pub = e.get("pub_date")
                out.append({
                    "url": url,
                    "headline": e.get("title") or "",
                    "snippet": e.get("snippet") or "",
                    "domain": group_domain or e.get("attribution") or "",
                    "pub_date": datetime.fromtimestamp(pub).strftime("%Y-%m-%d") if isinstance(pub, (int, float)) else "",
                    "kind": "search",
                })
    return out


if __name__ == "__main__":
    cli(ChatGPTScraper)
