"""
scraper_base.py
---------------
Shared base for the guest-mode scrapers (chatgpt_scraper.py, perplexity_scraper.py).

Design, see local-docs/prd-parallel-runs-and-retries.md sections 5 and 7:

- The scraper exposes small steps so a queue worker can drive them and heartbeat
  between them: open_new_chat(), ask(), wait_for_answer(), extract_answer(),
  has_sources(), extract_sources().
- Failures are raised as typed exceptions (RetryableError, BlockedError,
  BadInputError) instead of being printed and swallowed.
- run_one(prompt) drives all steps for one prompt and returns a ScrapeResult.
- run_csv() is the single-thread runner behind `python chatgpt_scraper.py <dates>`.
  The queue runner from the PRD will call run_one() directly.

No login anywhere. Both targets are used as a logged-out guest.
"""

from __future__ import annotations

import json
import random
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from seleniumbase import Driver

DATA_DIR = Path("data")

# One Chrome profile per account, e.g. profiles/mj/. Created by `--login --profile mj`.
# The profile holds the session cookies, so it IS the credential: gitignored, never shared.
PROFILES_DIR = Path("profiles")


# ----------------------------------------------------------------------------
# Errors. The queue worker maps these to the result classes in PRD section 5.4.
# ----------------------------------------------------------------------------

class ScraperError(Exception):
    """Base class. `kind` is the short label stored in the queue's last_error."""
    kind = "error"


class RetryableError(ScraperError):
    """Timeout, element missing, browser crash, empty answer, blank page."""
    kind = "retryable"


class BlockedError(ScraperError):
    """Login wall, Cloudflare challenge, rate limit. The worker pauses."""
    kind = "blocked"


class BadInputError(ScraperError):
    """Empty headline or prompt. Not retried."""
    kind = "bad_input"


# ----------------------------------------------------------------------------
# Result
# ----------------------------------------------------------------------------

@dataclass
class ScrapeResult:
    prompt: str
    request_time: str = ""
    response_text: str = ""            # answer as HTML
    response_plain: str = ""           # answer as visible text
    searched: int = 0                  # 1 if the model showed any sources
    citations: list = field(default_factory=list)       # [{url, headline, snippet}]
    search_results: list = field(default_factory=list)  # pages the model retrieved (cited or not)
    images: list = field(default_factory=list)          # image-search cards shown in the answer
    # Whether search_results could be read: "ok", "none" (captured, no search ran),
    # "capture_failed" (response not readable), "n/a" (target has no such list).
    search_results_status: str = "n/a"
    screenshot_path: str = ""

    def to_row(self) -> dict:
        cited = {normalize_url(c.get("url", "")) for c in self.citations if c.get("url")}
        not_cited = [s for s in self.search_results if normalize_url(s.get("url", "")) not in cited]
        return {
            "prompt": self.prompt,
            "request_time": self.request_time,
            "response_text": self.response_text,
            "response_plain": self.response_plain,
            "searched": self.searched,
            "response_citations": json.dumps(self.citations, ensure_ascii=False),
            "response_search_results": json.dumps(self.search_results, ensure_ascii=False),
            "response_images": json.dumps(self.images, ensure_ascii=False),
            "n_citations": len(self.citations),
            "n_search_results": len(self.search_results),
            "n_search_results_not_cited": len(not_cited),
            "search_results_status": self.search_results_status,
            "screenshot_path": self.screenshot_path,
        }


# ----------------------------------------------------------------------------
# Helpers shared by both scrapers
# ----------------------------------------------------------------------------

def remove_non_bmp(text: str) -> str:
    """Chromedriver cannot type characters outside the Basic Multilingual Plane."""
    return "".join(c for c in text if ord(c) <= 0xFFFF)


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    url = re.sub(r"[?&]utm_source=chatgpt\.com", "", url)
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.rstrip("/").lower()


def domain_of(url: str) -> str:
    return normalize_url(url).split("/")[0]


def _title_overlap(a: str, b: str) -> float:
    """Share of the shorter title's content words that appear in the other title."""
    tok = lambda s: {w for w in re.findall(r"[a-z0-9']+", (s or "").lower()) if len(w) > 2}
    ta, tb = tok(a), tok(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def match_sources(sources: list, article_url: str, headline: str) -> tuple[int, int]:
    """
    Returns (original_found, republisher_found) as 0/1.

    original:    a source URL matches the article URL; or, when the source has no URL
                 (ChatGPT citation popovers), its domain matches and its title overlaps
                 the headline strongly.
    republisher: a source on another domain whose title matches the headline.
    """
    original = 0
    republisher = 0
    target = normalize_url(article_url)
    target_domain = domain_of(article_url)
    headline = (headline or "").strip()
    for s in sources:
        u = normalize_url(s.get("url", ""))
        dom = s.get("domain") or (domain_of(u) if u else "")
        title = (s.get("headline") or "").split(" ...")[0].strip()
        overlap = _title_overlap(title, headline) if title and headline else 0.0
        if u and target and (u == target or u in target or target in u):
            original = 1
            continue
        if not u and dom and target_domain and dom == target_domain and overlap >= 0.5:
            original = 1
            continue
        if "wikipedia.org" in (u or dom):
            continue
        # 0.8: syndicated copies (e.g. Yahoo) reuse the headline nearly verbatim;
        # other outlets' own stories on the same event score ~0.6-0.7 (checked 2026-10-25).
        if title and headline and (title in headline or overlap >= 0.8) and dom != target_domain:
            republisher = 1
    return original, republisher


# ----------------------------------------------------------------------------
# Base scraper
# ----------------------------------------------------------------------------

class BaseScraper:
    name = "base"
    url = ""

    # Timing defaults, PRD section 9. Subclasses override.
    throttle: tuple[float, float] = (20, 30)   # sleep before each ask
    not_sent_timeout = 15                       # s: generation or answer must appear
    hard_timeout = 240                          # s: whole answer
    stable_window = 3                           # s: answer text unchanged
    poll = 1.0                                  # s

    # Text fragments (lower case) that mean we are blocked. Subclasses extend.
    BLOCKED_TEXT: Sequence[str] = (
        "verify you are human",
        "just a moment",
        "checking your browser",
        "too many requests",
        "unusual activity",
    )
    CLOUDFLARE_CSS: Sequence[str] = ("#challenge-form", "#cf-chl-widget", "iframe[src*='challenges.cloudflare.com']")

    # Optional User-Agent override. Headless Chrome announces itself as
    # "HeadlessChrome", which some sites (Perplexity) answer with a sign-in wall.
    USER_AGENT: str | None = None

    def __init__(self, headless: bool = True, profile: str | None = None,
                 profile_dir: str | None = None, window_size: tuple[int, int] = (1600, 2000),
                 user_agent: str | None = None):
        """
        profile:      name of a persistent, logged-in profile under profiles/ (account mode).
        profile_dir:  explicit Chrome user-data directory (overrides `profile`).
        Neither:      fresh temporary profile in Chrome guest mode (logged-out mode).
        """
        self.profile = profile
        if profile_dir:
            self.profile_dir = str(profile_dir)
        elif profile:
            self.profile_dir = str((PROFILES_DIR / profile).resolve())
            Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        else:
            self.profile_dir = tempfile.mkdtemp(prefix=f"{self.name}_profile_")
        self.headless = headless
        extra = {}
        ua = user_agent or self.USER_AGENT
        if ua:
            extra["agent"] = ua
        # --guest disables profile persistence, so it is only used when no profile is wanted.
        guest_args = [] if (profile or profile_dir) else ["--guest"]
        self.driver = Driver(
            uc=True,
            headless=headless,
            user_data_dir=self.profile_dir,
            **extra,
            chromium_arg=guest_args + [
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-search-engine-choice-screen",
                "--disable-notifications",
                "--disable-infobars",
                "--disable-extensions",
                "--disable-sync",
            ],
        )
        self.driver.set_window_size(*window_size)
        self.driver.set_page_load_timeout(45)

    # -- lifecycle ---------------------------------------------------------

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None

    def __del__(self):
        self.close()

    # -- element helpers ---------------------------------------------------

    def _find_all(self, selector: str):
        by = By.XPATH if selector.startswith(("//", "(//", "xpath=")) else By.CSS_SELECTOR
        selector = selector.removeprefix("xpath=")
        try:
            return self.driver.find_elements(by, selector)
        except WebDriverException:
            return []

    def find_first(self, candidates: Sequence[str], visible: bool = False, last: bool = False):
        """First candidate selector that matches. Returns (element, selector) or (None, None)."""
        for sel in candidates:
            els = self._find_all(sel)
            if visible:
                els = [e for e in els if self._displayed(e)]
            if els:
                return (els[-1] if last else els[0]), sel
        return None, None

    def exists(self, candidates: Sequence[str], visible: bool = True) -> bool:
        el, _ = self.find_first(candidates, visible=visible)
        return el is not None

    @staticmethod
    def _displayed(el) -> bool:
        try:
            return el.is_displayed()
        except (StaleElementReferenceException, WebDriverException):
            return False

    @staticmethod
    def _text(el) -> str:
        try:
            return el.text or ""
        except (StaleElementReferenceException, WebDriverException):
            return ""

    def body_text(self) -> str:
        try:
            return (self.driver.find_element(By.TAG_NAME, "body").text or "").lower()
        except WebDriverException:
            return ""

    def wait_until(self, pred: Callable[[], bool], timeout: float, poll: float | None = None) -> bool:
        """Poll pred until true. Returns False on timeout instead of raising."""
        end = time.time() + timeout
        poll = poll or self.poll
        while time.time() < end:
            try:
                if pred():
                    return True
            except (StaleElementReferenceException, NoSuchElementException):
                pass
            time.sleep(poll)
        return False

    def screenshot(self, path: str | Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.driver.save_screenshot(str(path))
            return str(path)
        except WebDriverException:
            return ""

    def save_html(self, path: str | Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(self.driver.page_source, encoding="utf-8")
            return str(path)
        except WebDriverException:
            return ""

    # -- generic blocked check ---------------------------------------------

    def page_text_for_block_check(self) -> str:
        """Visible page text minus the answer, so a news answer that happens to
        contain 'too many requests' is not mistaken for a block."""
        text = self.body_text()
        try:
            ans = self.answer_text().lower().strip()
        except Exception:
            ans = ""
        if ans:
            text = text.replace(ans, " ")
        return text

    def check_blocked(self):
        """Raise BlockedError if the page shows a block. Subclasses add their own text."""
        if self.exists(self.CLOUDFLARE_CSS, visible=False):
            raise BlockedError("cloudflare challenge")
        text = self.page_text_for_block_check()
        for frag in self.BLOCKED_TEXT:
            if frag in text:
                raise BlockedError(f"page says: {frag!r}")

    # -- login state (account mode) ------------------------------------------

    login_url: str = ""          # where to send the person for a manual login

    def is_logged_in(self) -> bool:
        """Best-effort check of the current page. Subclasses override."""
        return False

    # -- step API, implemented by subclasses --------------------------------

    def open_new_chat(self):
        raise NotImplementedError

    def ask(self, prompt: str) -> str:
        """Type the prompt and submit. Returns request_time string."""
        raise NotImplementedError

    def is_generating(self) -> bool:
        """True while the site shows a stop button / streaming indicator."""
        raise NotImplementedError

    def answer_text(self) -> str:
        """Visible text of the latest answer, empty if none yet."""
        raise NotImplementedError

    def extract_answer(self) -> str:
        """HTML of the latest answer."""
        raise NotImplementedError

    def has_sources(self) -> bool:
        raise NotImplementedError

    def extract_sources(self) -> tuple[list, list]:
        """Returns (citations, search_results)."""
        raise NotImplementedError

    def collect_extras(self, result: "ScrapeResult"):
        """Hook for target-specific fields (images, search_results from the network)."""
        return None

    # -- completion check, PRD section 5.3 -----------------------------------

    def wait_for_answer(self):
        start = time.time()

        # 1. Prompt was sent: a generation indicator or some answer text must appear.
        sent = self.wait_until(lambda: self.is_generating() or bool(self.answer_text().strip()),
                               self.not_sent_timeout, poll=0.5)
        if not sent:
            self.check_blocked()
            raise RetryableError(f"not_sent: nothing happened within {self.not_sent_timeout} s")

        # 2. Generation finished.
        remaining = self.hard_timeout - (time.time() - start)
        done = self.wait_until(lambda: not self.is_generating(), remaining)
        if not done:
            raise RetryableError(f"timeout: still generating after {self.hard_timeout} s")

        # 3. Answer text stable for stable_window seconds.
        last = self.answer_text()
        stable_since = time.time()
        while time.time() - start < self.hard_timeout:
            time.sleep(self.poll)
            cur = self.answer_text()
            if cur != last:
                last, stable_since = cur, time.time()
            elif time.time() - stable_since >= self.stable_window:
                break
        else:
            raise RetryableError("timeout: answer text never stabilised")

        if not last.strip():
            self.check_blocked()
            raise RetryableError("empty_answer")

    # -- one prompt end to end ------------------------------------------------

    def run_one(self, prompt: str) -> ScrapeResult:
        if not prompt or not prompt.strip():
            raise BadInputError("empty prompt")
        result = ScrapeResult(prompt=prompt)
        try:
            self.open_new_chat()
            self.check_blocked()
            result.request_time = self.ask(prompt)
            self.wait_for_answer()
            self.check_blocked()          # a login wall can appear after the answer
            result.response_text = self.extract_answer()
            result.response_plain = self.answer_text()
            if self.has_sources():
                result.citations, result.search_results = self.extract_sources()
            self.collect_extras(result)
            result.searched = 1 if (result.citations or result.search_results) else 0
            return result
        except ScraperError:
            raise
        except WebDriverException as e:
            first_line = (str(e).splitlines() or [""])[0][:200]
            raise RetryableError(f"{type(e).__name__}: {first_line}") from e


# ----------------------------------------------------------------------------
# Single-thread runner (today's `python <scraper>.py <dates>` behaviour)
# ----------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "prompt", "request_time", "response_text", "response_plain", "searched",
    "response_citations", "response_search_results", "response_images",
    "n_citations", "n_search_results", "n_search_results_not_cited", "search_results_status",
    "original_in_citations", "original_in_search_results",
    "republisher_in_citations", "republisher_in_search_results",
    "screenshot_path", "status", "error",
]


def login_session(scraper_cls: type[BaseScraper], profile: str):
    """
    Open a visible browser on the site's login page using profiles/<profile>/ and
    wait while the person logs in by hand (Google, email code, whatever the site
    wants). Nothing is typed by the script and no password is stored anywhere.
    After this, any run with --profile <profile> starts logged in.
    """
    s = scraper_cls(headless=False, profile=profile)
    try:
        s.driver.uc_open_with_reconnect(s.login_url or s.url, reconnect_time=4)
        print(f"\nA Chrome window is open using profile '{profile}' ({s.profile_dir}).")
        print(f"Log in to {s.name} in that window. Finish any code or 2FA step.")
        input("When the normal chat page is showing, press Enter here... ")
        try:
            s.driver.uc_open_with_reconnect(s.url, reconnect_time=4)
            time.sleep(3)
        except Exception:
            pass
        if s.is_logged_in():
            print(f"Login confirmed. Profile saved at {s.profile_dir}")
        else:
            print("Could not confirm the logged-in state from the page. The session may still be saved;")
            print(f"run the scraper with --profile {profile} --headful --limit 1 to check.")
    finally:
        s.close()


def run_csv(scraper_cls: type[BaseScraper], dates: str, headless: bool = True,
            limit: int | None = None, blocked_pause: float = 600, profile: str | None = None):
    """
    Read data/gannett_API_data_{dates}.csv, ask one prompt per article, write
    data/gannett_{name}_{dates}.csv after every article. No retries here; the
    queue runner handles those. A blocked page restarts the browser and pauses.
    """
    from Prompt_Generator import PromptGenerator  # needs OPENAI_API_KEY; import lazily

    name = scraper_cls.name
    in_path = DATA_DIR / f"gannett_API_data_{dates}.csv"
    out_path = DATA_DIR / f"gannett_{name}_{dates}.csv"
    shots = DATA_DIR / f"screenshots_{name}_{dates}"
    (shots / "Errors").mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(in_path)
    if limit:
        df = df.head(limit).copy()
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    total = len(df)
    print(f"[{name}] {total} articles from {in_path} | mode={'account:' + profile if profile else 'guest'}")

    pg = PromptGenerator()
    scraper = scraper_cls(headless=headless, profile=profile)

    def restart():
        nonlocal scraper
        scraper.close()
        scraper = scraper_cls(headless=headless, profile=profile)

    try:
        for n, (idx, row) in enumerate(df.iterrows(), start=1):
            headline = str(row.get("headline") or "").strip()
            if not headline:
                df.loc[idx, ["status", "error"]] = ["bad_input", "empty headline"]
                continue
            prompt = pg.generate(headline, row.get("keywords", "") or "")
            df.loc[idx, "prompt"] = prompt

            time.sleep(random.uniform(*scraper.throttle))
            try:
                res = scraper.run_one(prompt)
                oc, rc = match_sources(res.citations, row.get("pageURL", ""), headline)
                osr, rsr = match_sources(res.search_results, row.get("pageURL", ""), headline)
                if oc or rc or osr or rsr:
                    res.screenshot_path = scraper.screenshot(shots / f"Article_{n}_SourceUsed.png")
                for k, v in res.to_row().items():
                    df.loc[idx, k] = v
                df.loc[idx, ["original_in_citations", "republisher_in_citations",
                             "original_in_search_results", "republisher_in_search_results",
                             "status", "error"]] = [oc, rc, osr, rsr, "done", ""]
            except ScraperError as e:
                shot = scraper.screenshot(shots / "Errors" / f"Article_{n}_{e.kind}.png") if scraper.driver else ""
                df.loc[idx, ["status", "error", "screenshot_path"]] = [e.kind, str(e)[:300], shot]
                print(f"  article {n}: {e.kind}: {e}")
                restart()
                if isinstance(e, BlockedError):
                    print(f"  blocked; pausing {blocked_pause:.0f} s")
                    time.sleep(blocked_pause)

            df.to_csv(out_path, index=False)
            print(f"[{name}] {n}/{total} ({n / total:.0%}) status={df.loc[idx, 'status']}")
    except KeyboardInterrupt:
        print("\nInterrupted. Saving progress...")
    finally:
        scraper.close()
        df.to_csv(out_path, index=False)
        print(f"[{name}] saved {out_path}")


def cli(scraper_cls: type[BaseScraper]):
    """
    Shared command line.
      python <scraper>.py --login --profile mj          log in once by hand, save the session
      python <scraper>.py 2026-10-20 --profile mj       run logged in with that profile
      python <scraper>.py 2026-10-20                    run as a logged-out guest
    Options: --headful (visible browser), --limit N (first N articles).
    """
    import argparse
    p = argparse.ArgumentParser(prog=f"{scraper_cls.name}_scraper.py")
    p.add_argument("dates", nargs="?", help="YYYY-MM-DD or YYYY-MM-DD_DD")
    p.add_argument("--profile", help="name of a saved login profile under profiles/")
    p.add_argument("--login", action="store_true", help="open a browser to log in by hand, then exit")
    p.add_argument("--headful", action="store_true", help="show the browser window")
    p.add_argument("--limit", type=int, help="only the first N articles")
    a = p.parse_args()

    if a.login:
        if not a.profile:
            p.error("--login needs --profile NAME")
        login_session(scraper_cls, a.profile)
        return
    if not a.dates:
        p.error("dates is required unless --login is given")
    run_csv(scraper_cls, a.dates, headless=not a.headful, limit=a.limit, profile=a.profile)
