"""
accounts.py
-----------
Login accounts for the scrapers, read from accounts.toml at the repo root
(gitignored). Copy accounts.example.toml to accounts.toml and fill it in.

Each account gets its own persistent Chrome profile under profiles/<name>/.
The scraper logs in automatically when that profile has no valid session, so a
new machine only needs this file: the first run logs every account in.

Handing over to a teammate: share accounts.toml through a password manager or
an encrypted archive, not Slack or email.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = Path(os.environ.get("SCRAPER_ACCOUNTS", ROOT / "accounts.toml"))

LOGIN_METHODS = {
    # method:  services it works for
    "google": {"chatgpt", "perplexity"},   # "Continue with Google" on both sites
    "password": {"chatgpt"},               # ChatGPT email + password (no Google)
}


@dataclass
class Account:
    name: str
    email: str
    password: str
    login: str = "google"
    services: list = field(default_factory=lambda: ["chatgpt", "perplexity"])

    def supports(self, service: str) -> bool:
        return service in self.services and service in LOGIN_METHODS.get(self.login, set())

    def __repr__(self) -> str:  # never print the password
        return f"Account(name={self.name!r}, email={self.email!r}, login={self.login!r}, services={self.services})"


class AccountsError(ValueError):
    pass


def load_accounts(path: str | Path | None = None, service: str | None = None) -> list[Account]:
    """All accounts in the file, optionally only those usable for `service`."""
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise AccountsError(f"{path}: not valid TOML: {e}") from e

    out, names = [], set()
    for i, raw in enumerate(data.get("account", []), start=1):
        missing = [k for k in ("name", "email", "password") if not raw.get(k)]
        if missing:
            raise AccountsError(f"{path}: account #{i} is missing {', '.join(missing)}")
        acct = Account(
            name=str(raw["name"]),
            email=str(raw["email"]),
            password=str(raw["password"]),
            login=str(raw.get("login", "google")),
            services=list(raw.get("services", ["chatgpt", "perplexity"])),
        )
        if acct.login not in LOGIN_METHODS:
            raise AccountsError(f"{path}: account {acct.name!r}: login must be one of {sorted(LOGIN_METHODS)}")
        if acct.name in names:
            raise AccountsError(f"{path}: duplicate account name {acct.name!r}")
        names.add(acct.name)
        for svc in acct.services:
            if svc not in LOGIN_METHODS[acct.login]:
                raise AccountsError(
                    f"{path}: account {acct.name!r}: login '{acct.login}' does not work for {svc} "
                    f"(Perplexity has no password login; use login = \"google\")")
        out.append(acct)
    if service:
        out = [a for a in out if a.supports(service)]
    return out


def get_account(name: str, service: str, path: str | Path | None = None) -> Account | None:
    for a in load_accounts(path, service):
        if a.name == name:
            return a
    return None
