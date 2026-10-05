"""Who is asking: browser sessions, the principals that own faces, and
the links that join a browser to a principal.

- A **session** is a random token in the `wfb_session` cookie. The store
  keeps only its hash (`sessions/<sha256>.json`), so a copied state
  directory hands out no live cookie.
- A **principal** owns documents (`meta.json`'s `owner`). Each browser gets
  an anonymous one on its first request. Logging in, later, is only one
  more way to bind a session to a principal: nothing a principal owns
  changes. `identities` is where a login will record who it is.
- The **owner** principal holds every document created before faces had
  owners, and the face named on `wfb studio`'s command line. The browser
  that opens the startup link (`?claim=<code>`) is bound to it.
- A **claim** is a single-use code that binds the browser opening it to a
  principal: the startup link's, or one a browser asks for to open its own
  faces in another browser (`CLAIM_SECONDS`).

Faces are kept until their owner deletes them, so a session that reaches
a face is kept too: pruning forgets only a session whose principal owns
nothing, once it is unseen for `IDLE_DAYS`. The cookie lasts `COOKIE_DAYS`
from the last visit, the longest a browser keeps one.

With `single_user`, every request is the owner, as before sessions.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import OWNER, StoreError, _write_atomic

#: The session cookie's name.
COOKIE = "wfb_session"
#: How long a claim link to another browser lasts.
CLAIM_SECONDS = 600.0
#: How long the cookie lasts from the last visit: browsers cap a cookie's
#: lifetime at 400 days.
COOKIE_DAYS = 400
#: How long a session that reaches no face is kept unseen.
IDLE_DAYS = 30.0


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Claim:
    principal: str
    expires: float | None


class Sessions:
    """Sessions and principals under ``root`` (the store's own root)."""

    def __init__(self, root: Path, *, single_user: bool = False) -> None:
        self.root = root
        self.single_user = single_user
        self._lock = threading.Lock()
        self._claims: dict[str, Claim] = {}
        try:
            (root / "sessions").mkdir(parents=True, exist_ok=True)
            (root / "principals").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError(f"cannot create the session store under {root}: {exc}") from exc
        if not (root / "principals" / f"{OWNER}.json").is_file():
            self._write_principal(OWNER, "owner")

    # -- principals -------------------------------------------------------------------

    def _write_principal(self, principal: str, kind: str) -> None:
        data = {"kind": kind, "created": time.time(), "identities": []}
        _write_atomic(self.root / "principals" / f"{principal}.json", json.dumps(data).encode())

    def principals(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "principals").glob("*.json"))

    # -- sessions ---------------------------------------------------------------------

    def principal_of(self, token: str | None) -> str | None:
        """The principal a request's cookie names, or `None` when it names
        no session. The token only ever reaches a path hashed."""
        if self.single_user:
            return OWNER
        if token and len(token) <= 256:
            path = self.root / "sessions" / f"{_hash(token)}.json"
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                data = None
            if isinstance(data, dict) and isinstance(data.get("principal"), str):
                if time.time() - float(data.get("last_seen", 0)) > 60:
                    data["last_seen"] = time.time()
                    _write_atomic(path, json.dumps(data).encode())
                return str(data["principal"])
        return None

    def new_browser(self) -> tuple[str, str]:
        """A new anonymous principal and a session token bound to it, for a
        browser loading the editor with no session."""
        principal = uuid.uuid4().hex
        self._write_principal(principal, "anonymous")
        return principal, self._bind(principal)

    def _bind(self, principal: str) -> str:
        """A new session token bound to ``principal``."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        data = {"principal": principal, "created": now, "last_seen": now}
        _write_atomic(self.root / "sessions" / f"{_hash(token)}.json", json.dumps(data).encode())
        return token

    # -- claims -----------------------------------------------------------------------

    def startup_claim(self) -> str:
        """A code that binds the browser opening it to the owner principal,
        valid until used or the server stops."""
        code = secrets.token_urlsafe(24)
        with self._lock:
            self._claims[code] = Claim(OWNER, None)
        return code

    def claim_for(self, principal: str) -> str:
        """A single-use code that binds another browser to ``principal``,
        for `CLAIM_SECONDS`."""
        code = secrets.token_urlsafe(24)
        with self._lock:
            self._claims[code] = Claim(principal, time.time() + CLAIM_SECONDS)
        return code

    def redeem(self, code: str) -> str | None:
        """A new session token bound to the code's principal, or `None` when
        the code is unknown, used or expired. A code works once."""
        with self._lock:
            claim = self._claims.pop(code, None)
        if claim is None or (claim.expires is not None and claim.expires < time.time()):
            return None
        return self._bind(claim.principal)

    # -- pruning ----------------------------------------------------------------------

    def prune(self, owners: set[str], now: float | None = None) -> list[str]:
        """Remove sessions unseen for `IDLE_DAYS` whose principal owns no
        document (``owners``), then every anonymous principal with no
        session and no document."""
        now = time.time() if now is None else now
        removed: list[str] = []
        bound: set[str] = set()
        for path in (self.root / "sessions").glob("*.json"):
            try:
                data: Any = json.loads(path.read_text())
                seen = float(data.get("last_seen", 0))
            except (OSError, ValueError, AttributeError):
                path.unlink(missing_ok=True)
                continue
            if str(data.get("principal")) not in owners and now - seen > IDLE_DAYS * 86400:
                path.unlink(missing_ok=True)
                removed.append(f"session {path.stem[:8]}: no face, and unseen for over "
                               f"{IDLE_DAYS:g} days")
            else:
                bound.add(str(data.get("principal")))
        for principal in self.principals():
            if principal != OWNER and principal not in bound and principal not in owners:
                (self.root / "principals" / f"{principal}.json").unlink(missing_ok=True)
                removed.append(f"principal {principal[:8]}: no session and no face")
        return removed
