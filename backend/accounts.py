"""Accounts on the shared database: who may sign in, and what the operator
can do about them.

This is the only code that sees across accounts, and it deals in accounts,
not in what they hold: it can count a friend's profiles and delete them, but
it has no key and so cannot read a journal. Reading and writing a person's
data always goes through Store, opened for one account.

Invite-only. An account exists only because `invite` created it; there is no
path by which someone can make their own.
"""
from __future__ import annotations

import functools
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths, vault
from .store import SCHEMA, _now

SHARED_DB = paths.shared_db()

INVITE_DAYS = 14
MIN_PASSWORD = 10

# Sign-in state. Only fingerprints of the secrets are kept, and the account's
# data key rides along wrapped under the secret itself (see vault.py).
SIGNIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_client (
    client_id   TEXT PRIMARY KEY,
    info        TEXT NOT NULL,          -- JSON, as Claude registered itself
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_grant (
    fingerprint  TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,         -- code | access | refresh
    account_id   INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    client_id    TEXT NOT NULL,
    family       TEXT NOT NULL,         -- one sign-in; revoked together
    detail       TEXT NOT NULL,         -- JSON
    wrapped_key  TEXT NOT NULL,
    expires_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_grant_account ON oauth_grant(account_id);
"""


class AccountError(Exception):
    """Something the person at the keyboard can fix; the message is for them."""


def _email(text: str) -> str:
    return text.strip().lower()


def _locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class Accounts:
    def __init__(self, path: Path | str = SHARED_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

        # Look before touching anything. A file that already holds profiles
        # and is not marked shared is somebody's personal database -- the
        # family one, most likely -- and must never be served to others.
        tables = {r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        marked = "setting" in tables and self.db.execute(
            "SELECT 1 FROM setting WHERE key='mode' AND value='shared'"
        ).fetchone() is not None
        if tables and not marked:
            self.db.close()
            raise PermissionError(
                f"{self.path} is a personal database, not the shared one. "
                f"The shared server will not open it.")

        self.db.executescript(SCHEMA.read_text())
        self.db.executescript(SIGNIN_SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO setting (key, value)"
                        " VALUES ('mode', 'shared')")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def _row(self, email: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM account WHERE email=?",
                               (_email(email),)).fetchone()

    def _need(self, email: str) -> sqlite3.Row:
        row = self._row(email)
        if row is None:
            raise AccountError(f"There is no account for {_email(email)}.")
        return row

    # --------------------------------------------- what the operator can do

    @_locked
    def invite(self, email: str, name: str = "") -> str:
        """Create an account and return its one-time invite code."""
        email = _email(email)
        if "@" not in email or " " in email:
            raise AccountError(f"{email!r} does not look like an email address.")
        row = self._row(email)
        if row is not None and row["status"] != "invited":
            raise AccountError(
                f"{email} already has an account ({row['status']}).")
        code = vault.new_code(4)
        expires = (datetime.now(timezone.utc)
                   + timedelta(days=INVITE_DAYS)).isoformat(timespec="seconds")
        if row is None:
            self.db.execute(
                "INSERT INTO account (email, display_name, status, invite_hash,"
                " invite_expires, created_at) VALUES (?,?,'invited',?,?,?)",
                (email, name, vault.fingerprint(vault.normalise_code(code)),
                 expires, _now()))
        else:
            self.db.execute(
                "UPDATE account SET invite_hash=?, invite_expires=?,"
                " display_name=COALESCE(NULLIF(?, ''), display_name) WHERE id=?",
                (vault.fingerprint(vault.normalise_code(code)), expires, name,
                 row["id"]))
        self.db.commit()
        return code

    @_locked
    def listing(self) -> list[dict]:
        """Every account, with how much it holds -- counts, never content."""
        return [dict(r) for r in self.db.execute(
            "SELECT a.id, a.email, a.display_name, a.status, a.created_at,"
            "  a.last_seen_at, a.invite_expires,"
            "  (SELECT COUNT(*) FROM person p WHERE p.account_id=a.id)"
            "    AS profiles,"
            "  (SELECT COUNT(*) FROM decision d JOIN person p"
            "     ON p.id=d.person_id WHERE p.account_id=a.id) AS decisions"
            " FROM account a ORDER BY a.email")]

    @_locked
    def disable(self, email: str) -> None:
        """Shut an account out at once. Its data is kept."""
        row = self._need(email)
        self.db.execute("UPDATE account SET status='disabled' WHERE id=?",
                        (row["id"],))
        self.db.execute("DELETE FROM oauth_grant WHERE account_id=?",
                        (row["id"],))
        self.db.commit()

    @_locked
    def enable(self, email: str) -> None:
        row = self._need(email)
        if row["status"] != "disabled":
            raise AccountError(f"{row['email']} is not disabled.")
        status = "active" if row["key_by_password"] else "invited"
        self.db.execute("UPDATE account SET status=? WHERE id=?",
                        (status, row["id"]))
        self.db.commit()

    @_locked
    def delete(self, email: str) -> dict:
        """Remove an account and everything belonging to it."""
        row = self._need(email)
        counts = {
            "profiles": self.db.execute(
                "SELECT COUNT(*) FROM person WHERE account_id=?",
                (row["id"],)).fetchone()[0],
            "decisions": self.db.execute(
                "SELECT COUNT(*) FROM decision d JOIN person p"
                " ON p.id=d.person_id WHERE p.account_id=?",
                (row["id"],)).fetchone()[0],
        }
        # Decisions point at charts without a cascade, so they go first.
        self._wipe_journal(row["id"])
        self.db.execute("DELETE FROM person WHERE account_id=?", (row["id"],))
        self.db.execute("DELETE FROM oauth_grant WHERE account_id=?",
                        (row["id"],))
        self.db.execute("DELETE FROM account WHERE id=?", (row["id"],))
        self.db.commit()
        return counts

    @_locked
    def reset(self, email: str) -> str:
        """For someone who lost both their password and their recovery code.

        Nobody can recover the key, so what it locked is deleted: the journal
        and the life events. Profiles and charts are kept. Returns a fresh
        invite code, with which they register again.
        """
        row = self._need(email)
        self._wipe_journal(row["id"])
        self.db.execute("DELETE FROM oauth_grant WHERE account_id=?",
                        (row["id"],))
        self.db.execute(
            "UPDATE account SET status='invited', key_by_password=NULL,"
            " key_by_recovery=NULL WHERE id=?", (row["id"],))
        self.db.commit()
        return self.invite(row["email"])

    def _wipe_journal(self, account_id: int) -> None:
        mine = "(SELECT id FROM person WHERE account_id=?)"
        for table in ("decision", "conversation", "life_event"):
            self.db.execute(
                f"DELETE FROM {table} WHERE person_id IN {mine}", (account_id,))
        self.db.execute(
            f"UPDATE chart SET rectification_note=NULL WHERE person_id IN {mine}",
            (account_id,))

    # ------------------------------------------------ what a friend can do

    @_locked
    def register(self, email: str, invite_code: str,
                 password: str) -> tuple[int, bytes, str]:
        """Turn an invite into a working account.

        Returns the account id, its new data key, and the recovery code --
        which is shown to the person once and exists nowhere else.
        """
        row = self._row(email)
        given = vault.fingerprint(vault.normalise_code(invite_code))
        # One answer for every way this can be wrong, so the page cannot be
        # used to find out which emails have been invited.
        if (row is None or row["status"] != "invited" or not row["invite_hash"]
                or row["invite_hash"] != given
                or row["invite_expires"] < _now()):
            raise AccountError("That email and invite code do not match an "
                               "open invitation. Check both, or ask for a "
                               "new code.")
        if len(password) < MIN_PASSWORD:
            raise AccountError(
                f"Choose a password of at least {MIN_PASSWORD} characters.")
        key = vault.new_data_key()
        recovery = vault.new_code(5)
        self.db.execute(
            "UPDATE account SET status='active', invite_hash=NULL,"
            " invite_expires=NULL, key_by_password=?, key_by_recovery=?"
            " WHERE id=?",
            (vault.wrap_with_secret(key, password),
             vault.wrap_with_secret(key, vault.normalise_code(recovery)),
             row["id"]))
        self.db.commit()
        return row["id"], key, recovery

    @_locked
    def sign_in(self, email: str, password: str) -> tuple[int, bytes] | None:
        row = self._row(email)
        if row is None or row["status"] != "active":
            # Spend the same time as a real attempt would.
            vault.unwrap_with_secret("AAAAAAAAAAAAAAAAAAAAAA==.x", password)
            return None
        key = vault.unwrap_with_secret(row["key_by_password"], password)
        if key is None:
            return None
        return row["id"], key

    @_locked
    def recover(self, email: str, recovery_code: str,
                new_password: str) -> tuple[int, bytes, str] | None:
        """Set a new password using the recovery code, which is then replaced."""
        row = self._row(email)
        if row is None or row["status"] != "active":
            vault.unwrap_with_secret("AAAAAAAAAAAAAAAAAAAAAA==.x", recovery_code)
            return None
        key = vault.unwrap_with_secret(row["key_by_recovery"],
                                       vault.normalise_code(recovery_code))
        if key is None:
            return None
        if len(new_password) < MIN_PASSWORD:
            raise AccountError(
                f"Choose a password of at least {MIN_PASSWORD} characters.")
        recovery = vault.new_code(5)
        self.db.execute(
            "UPDATE account SET key_by_password=?, key_by_recovery=? WHERE id=?",
            (vault.wrap_with_secret(key, new_password),
             vault.wrap_with_secret(key, vault.normalise_code(recovery)),
             row["id"]))
        # Whoever held the old password is signed out everywhere.
        self.db.execute("DELETE FROM oauth_grant WHERE account_id=?",
                        (row["id"],))
        self.db.commit()
        return row["id"], key, recovery

    # ------------------------------------------------------ sign-in grants

    @_locked
    def put_grant(self, kind: str, secret: str, account_id: int,
                  client_id: str, family: str, detail: dict, key: bytes,
                  ttl_seconds: int) -> int:
        expires = int(time.time()) + ttl_seconds
        self.db.execute(
            "INSERT INTO oauth_grant (fingerprint, kind, account_id, client_id,"
            " family, detail, wrapped_key, expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (vault.fingerprint(secret), kind, account_id, client_id, family,
             json.dumps(detail), vault.wrap_with_token(key, secret), expires))
        self.db.execute("DELETE FROM oauth_grant WHERE expires_at < ?",
                        (int(time.time()) - 86400,))
        self.db.commit()
        return expires

    @_locked
    def grant(self, kind: str, secret: str, take: bool = False) -> dict | None:
        """What a code or token stands for, if it is still good.

        None for anything else: unknown, expired, the wrong kind, or belonging
        to an account that is no longer active. `take` uses it up.
        """
        row = self.db.execute(
            "SELECT g.*, a.status FROM oauth_grant g JOIN account a"
            " ON a.id=g.account_id WHERE g.fingerprint=? AND g.kind=?",
            (vault.fingerprint(secret), kind)).fetchone()
        if row is None:
            return None
        if take:
            self.db.execute("DELETE FROM oauth_grant WHERE fingerprint=?",
                            (row["fingerprint"],))
            self.db.commit()
        if row["status"] != "active" or row["expires_at"] < time.time():
            return None
        key = vault.unwrap_with_token(row["wrapped_key"], secret)
        if key is None:
            return None
        return {"account_id": row["account_id"], "client_id": row["client_id"],
                "family": row["family"], "expires_at": row["expires_at"],
                "detail": json.loads(row["detail"]), "key": key}

    @_locked
    def drop_family(self, secret: str) -> None:
        """Sign out: remove a token and everything issued alongside it."""
        row = self.db.execute(
            "SELECT family FROM oauth_grant WHERE fingerprint=?",
            (vault.fingerprint(secret),)).fetchone()
        if row is not None:
            self.db.execute("DELETE FROM oauth_grant WHERE family=?",
                            (row["family"],))
            self.db.commit()

    @_locked
    def seen(self, account_id: int) -> None:
        self.db.execute("UPDATE account SET last_seen_at=? WHERE id=?",
                        (_now(), account_id))
        self.db.commit()

    # ------------------------------------------------------------ clients

    @_locked
    def client(self, client_id: str) -> str | None:
        row = self.db.execute("SELECT info FROM oauth_client WHERE client_id=?",
                              (client_id,)).fetchone()
        return row["info"] if row else None

    @_locked
    def save_client(self, client_id: str, info: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO oauth_client (client_id, info, created_at)"
            " VALUES (?,?,?)", (client_id, info, _now()))
        self.db.commit()
