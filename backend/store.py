"""Persistence. Everything lives in one SQLite file on your machine.

Two decisions worth knowing about:

Charts store the birth MOMENT, not the computed positions. Recomputing a chart
takes under a millisecond, so caching the output would buy nothing and would
introduce a way for stored positions to drift out of step with the ephemeris.

Reads that feed Claude's context are deterministically ordered. The chart and
life events form the stable prefix of every request, and prompt caching is a
byte-exact prefix match -- rows arriving in a different order would silently
cost real money on every question.

A Store is always opened FOR ONE ACCOUNT and can reach nothing else. Every
method that takes a person, decision or conversation id checks first that the
id belongs to that account, and an id belonging to someone else raises exactly
what an id that does not exist raises -- so a caller cannot even learn that it
is there. verify_accounts.py walks every public method to prove it, and fails
if a method is added without being covered.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import confidence, dasha, ephemeris, paths, timeplace, vault

# In the data folder, never the app folder. JYOTISHA_DB overrides it, so the
# MCP server finds the same database whatever directory its host starts it in.
DB_PATH = paths.family_db()
SCHEMA = Path(__file__).with_name("schema.sql")

CLAIM_KINDS = ("house_placement", "aspect", "dasha_lord", "dasha_date",
               "navamsa", "shashtiamsa")

# What is encrypted in the shared database: everything a person says about
# their life and their decisions. Names and birth data are left readable.
# In a personal database nothing is encrypted and these lists do nothing.
LOCKED = {
    "chart": ("rectification_note",),
    "life_event": ("happened_on", "category", "title", "description"),
    "conversation": ("title",),
    "message": ("content",),
    "decision": ("question", "question_type", "houses_consulted", "verdict",
                 "confidence", "window_opens", "window_closes",
                 "astral_snapshot", "chose", "outcome", "outcome_rating"),
    "citation": ("claim", "fact"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str = DB_PATH,
                 account_id: int | None = None, key: bytes | None = None):
        """Open the database for one account.

        With no account given this is a personal database and the store acts
        as its owner. The shared database has no owner: it opens only for a
        named, active account together with that account's data key.
        """
        self.path = Path(path)
        if str(self.path.parent) not in (".", ""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI runs sync endpoints in a thread pool, and a dependency's
        # setup can land on a different pool thread from the endpoint body --
        # so one connection legitimately crosses threads within a request.
        # That is safe here because each request gets its own connection and
        # uses it sequentially; it is never shared between requests.
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA.read_text())
        self._migrate()
        self.db.commit()
        # Tool calls run on worker threads, and two calls for the same account
        # can overlap; this keeps a multi-statement write from interleaving.
        self._lock = threading.RLock()

        self.shared = self._setting("mode") == "shared"
        if account_id is None:
            if self.shared:
                self.db.close()
                raise PermissionError(
                    "this is the shared database: it opens only for a "
                    "signed-in account")
            account_id = self._owner_account()
            # Rows written by a copy of the code that predates accounts.
            self.db.execute("UPDATE person SET account_id=? WHERE account_id"
                            " IS NULL", (account_id,))
            self.db.commit()
        else:
            row = self.db.execute("SELECT status FROM account WHERE id=?",
                                  (account_id,)).fetchone()
            if row is None or row["status"] != "active":
                self.db.close()
                raise PermissionError("no active account")
            if self.shared and key is None:
                self.db.close()
                raise PermissionError(
                    "the shared database needs the account's key")
        self.account_id = account_id
        self._cipher = vault.Cipher(key) if key is not None else None
        # A personal database counts ids up, so id order is age order. The
        # shared one draws them at random (see _new_id) and has to go by time.
        self._oldest = "created_at, id" if self.shared else "id"
        self._newest = "created_at DESC, id DESC" if self.shared else "id DESC"

    def _migrate(self) -> None:
        """Bring a database from before accounts up to the current shape."""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(person)")}
        if "account_id" not in cols:
            self.db.execute("ALTER TABLE person ADD COLUMN account_id INTEGER"
                            " REFERENCES account(id) ON DELETE CASCADE")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_person_account"
                        " ON person(account_id)")

    def _owner_account(self) -> int:
        row = self.db.execute(
            "SELECT id FROM account WHERE is_owner=1").fetchone()
        if row is not None:
            return row["id"]
        if self.db.execute("SELECT 1 FROM account").fetchone() is not None:
            self.db.close()
            raise PermissionError("this database has accounts but no owner; "
                                  "it opens only for a named account")
        cur = self.db.execute(
            "INSERT INTO account (display_name, is_owner, status, created_at)"
            " VALUES ('Owner', 1, 'active', ?)", (_now(),))
        return cur.lastrowid

    def _setting(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value FROM setting WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # ------------------------------------------------------------- ownership

    def _own_person(self, person_id: int) -> None:
        if self.db.execute(
                "SELECT 1 FROM person WHERE id=? AND account_id=?",
                (person_id, self.account_id)).fetchone() is None:
            raise KeyError(f"no person with id {person_id}")

    def _own_decision(self, decision_id: int) -> None:
        if self.db.execute(
                "SELECT 1 FROM decision d JOIN person p ON p.id=d.person_id"
                " WHERE d.id=? AND p.account_id=?",
                (decision_id, self.account_id)).fetchone() is None:
            raise KeyError(f"no decision with id {decision_id}")

    def _own_conversation(self, conversation_id: int) -> None:
        if self.db.execute(
                "SELECT 1 FROM conversation c JOIN person p ON p.id=c.person_id"
                " WHERE c.id=? AND p.account_id=?",
                (conversation_id, self.account_id)).fetchone() is None:
            raise KeyError(f"no conversation with id {conversation_id}")

    def _new_id(self, table: str) -> int | None:
        """The id for a new row.

        A personal database counts up. The shared one draws ids at random, so
        the gap between two of your own ids says nothing about how much
        anyone else has stored.
        """
        if not self.shared:
            return None
        while True:
            candidate = 1000 + secrets.randbelow(2 ** 31 - 1000)
            if self.db.execute(f"SELECT 1 FROM {table} WHERE id=?",
                               (candidate,)).fetchone() is None:
                return candidate

    def _lock_value(self, value):
        return self._cipher.lock(value) if self._cipher else value

    def _open(self, table: str, row: sqlite3.Row | None) -> dict | None:
        """A stored row as a dict, with its locked fields readable again."""
        if row is None:
            return None
        out = dict(row)
        if self._cipher:
            for field in LOCKED[table]:
                out[field] = self._cipher.open(out[field])
        return out

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------------------------------------------------------- people

    def add_person(self, name: str, relation: str = "self", notes: str = "") -> int:
        cur = self.db.execute(
            "INSERT INTO person (id, account_id, name, relation, notes,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (self._new_id("person"), self.account_id, name, relation, notes,
             _now()))
        self.db.commit()
        return cur.lastrowid

    def people(self) -> list[sqlite3.Row]:
        return self.db.execute(
            f"SELECT * FROM person WHERE account_id=? ORDER BY {self._oldest}",
            (self.account_id,)).fetchall()

    def person(self, person_id: int) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT * FROM person WHERE id=? AND account_id=?",
            (person_id, self.account_id)).fetchone()
        if row is None:
            raise KeyError(f"no person with id {person_id}")
        return row

    # ---------------------------------------------------------------- charts

    def add_chart(
        self, person_id: int, year: int, month: int, day: int,
        hour: int, minute: int, second: int,
        place_name: str, latitude: float, longitude: float,
        time_confidence: confidence.TimeConfidence,
        ayanamsa: str = "LAHIRI",
        derived_from_id: int | None = None,
        rectification_note: str | None = None,
    ) -> int:
        """Resolve a birth moment and store it, superseding the active chart.

        Nothing is overwritten: the previous version stays, flagged inactive,
        so a rectification can always be compared against what it replaced.
        """
        self._own_person(person_id)
        if derived_from_id is not None and self.db.execute(
                "SELECT 1 FROM chart WHERE id=? AND person_id=?",
                (derived_from_id, person_id)).fetchone() is None:
            raise KeyError(f"no chart with id {derived_from_id}")
        moment = timeplace.resolve(year, month, day, hour, minute,
                                   latitude, longitude, second=second)
        with self._lock:
            return self._insert_chart(
                person_id, year, month, day, hour, minute, second, place_name,
                latitude, longitude, time_confidence, ayanamsa,
                derived_from_id, rectification_note, moment)

    def _insert_chart(self, person_id, year, month, day, hour, minute, second,
                      place_name, latitude, longitude, time_confidence,
                      ayanamsa, derived_from_id, rectification_note,
                      moment) -> int:
        self.db.execute("UPDATE chart SET is_active=0 WHERE person_id=?", (person_id,))
        cur = self.db.execute(
            "INSERT INTO chart (id,"
            "  person_id, birth_date, birth_time, place_name, latitude, longitude,"
            "  timezone_name, utc_offset_hours, iana_offset_hours,"
            "  used_local_mean_time, julian_day_ut, time_ambiguous,"
            "  time_nonexistent, time_confidence, ayanamsa, is_active,"
            "  derived_from_id, rectification_note, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
            (self._new_id("chart"), person_id,
             f"{year:04d}-{month:02d}-{day:02d}",
             f"{hour:02d}:{minute:02d}:{second:02d}",
             place_name, latitude, longitude,
             moment.timezone_name, moment.utc_offset_hours, moment.iana_offset_hours,
             int(moment.used_local_mean_time), moment.julian_day_ut,
             int(moment.ambiguous), int(moment.nonexistent),
             time_confidence.name, ayanamsa,
             derived_from_id, self._lock_value(rectification_note), _now()))
        self.db.commit()
        return cur.lastrowid

    def active_chart_row(self, person_id: int) -> dict:
        self._own_person(person_id)
        row = self.db.execute(
            "SELECT * FROM chart WHERE person_id=? AND is_active=1"
            f" ORDER BY {self._newest} LIMIT 1", (person_id,)).fetchone()
        if row is None:
            raise KeyError(f"person {person_id} has no active chart")
        return self._open("chart", row)

    def chart_versions(self, person_id: int) -> list[dict]:
        self._own_person(person_id)
        return [self._open("chart", r) for r in self.db.execute(
            f"SELECT * FROM chart WHERE person_id=? ORDER BY {self._oldest}",
            (person_id,)).fetchall()]

    def compute(self, chart_row: sqlite3.Row) -> ephemeris.Chart:
        """Rebuild the live chart from the stored moment."""
        return ephemeris.compute_chart(
            chart_row["julian_day_ut"], chart_row["latitude"],
            chart_row["longitude"], chart_row["ayanamsa"])

    def dasha_tree(self, chart_row: sqlite3.Row, levels: int = 3) -> dasha.DashaTree:
        chart = self.compute(chart_row)
        return dasha.compute(chart.get("Moon").longitude,
                             chart_row["julian_day_ut"], levels=levels)

    def reliability(self, chart_row: sqlite3.Row) -> confidence.Reliability:
        """What this stored chart is entitled to claim."""
        y, mo, d = (int(x) for x in chart_row["birth_date"].split("-"))
        hh, mm, _ss = (int(x) for x in chart_row["birth_time"].split(":"))
        return confidence.assess(
            y, mo, d, hh, mm, chart_row["latitude"], chart_row["longitude"],
            confidence.TimeConfidence[chart_row["time_confidence"]],
            chart_row["ayanamsa"])

    # ----------------------------------------------------------- life events

    def add_life_event(self, person_id: int, happened_on: str, title: str,
                       precision: str = "day", category: str | None = None,
                       description: str = "", significance: int = 3) -> int:
        if precision not in ("day", "month", "year"):
            raise ValueError("precision must be day, month or year")
        if not 1 <= significance <= 5:
            raise ValueError("significance must be between 1 and 5")
        self._own_person(person_id)
        lock = self._lock_value
        cur = self.db.execute(
            "INSERT INTO life_event (id, person_id, happened_on, precision,"
            "  category, title, description, significance, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (self._new_id("life_event"), person_id, lock(happened_on),
             precision, lock(category), lock(title), lock(description),
             significance, _now()))
        self.db.commit()
        return cur.lastrowid

    def life_events(self, person_id: int) -> list[dict]:
        self._own_person(person_id)
        # Deterministic order: this feeds the cached prompt prefix. Sorted
        # here rather than in SQL because the date is one of the locked fields.
        rows = [self._open("life_event", r) for r in self.db.execute(
            "SELECT * FROM life_event WHERE person_id=? ORDER BY id",
            (person_id,)).fetchall()]
        return sorted(rows, key=lambda e: (e["happened_on"], e["id"]))

    # --------------------------------------------------------- conversations

    def start_conversation(self, person_id: int, title: str = "") -> int:
        self._own_person(person_id)
        cur = self.db.execute(
            "INSERT INTO conversation (id, person_id, title, started_at)"
            " VALUES (?,?,?,?)",
            (self._new_id("conversation"), person_id, self._lock_value(title),
             _now()))
        self.db.commit()
        return cur.lastrowid

    def add_message(self, conversation_id: int, role: str, content: str) -> int:
        if role not in ("user", "assistant"):
            raise ValueError("role must be user or assistant")
        self._own_conversation(conversation_id)
        cur = self.db.execute(
            "INSERT INTO message (conversation_id, role, content, created_at)"
            " VALUES (?,?,?,?)",
            (conversation_id, role, self._lock_value(content), _now()))
        self.db.commit()
        return cur.lastrowid

    def messages(self, conversation_id: int) -> list[dict]:
        self._own_conversation(conversation_id)
        return [self._open("message", r) for r in self.db.execute(
            "SELECT * FROM message WHERE conversation_id=? ORDER BY id",
            (conversation_id,)).fetchall()]

    # ------------------------------------------------------------- decisions

    def record_decision(self, person_id: int, chart_id: int, question: str,
                        question_type: str | None = None,
                        houses_consulted: list[int] | None = None,
                        conversation_id: int | None = None,
                        verdict: str = "", confidence_note: str = "",
                        window_opens: str | None = None,
                        window_closes: str | None = None,
                        astral_snapshot: dict | None = None,
                        reliability_snapshot: dict | None = None) -> int:
        self._own_person(person_id)
        if self.db.execute("SELECT 1 FROM chart WHERE id=? AND person_id=?",
                           (chart_id, person_id)).fetchone() is None:
            raise KeyError(f"no chart with id {chart_id}")
        if conversation_id is not None:
            self._own_conversation(conversation_id)
        lock = self._lock_value
        cur = self.db.execute(
            "INSERT INTO decision (id, person_id, chart_id, conversation_id,"
            "  asked_at, question, question_type, houses_consulted, verdict,"
            "  confidence, window_opens, window_closes, astral_snapshot,"
            "  reliability)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self._new_id("decision"), person_id, chart_id, conversation_id,
             _now(), lock(question), lock(question_type),
             lock(json.dumps(houses_consulted or [])), lock(verdict),
             lock(confidence_note), lock(window_opens), lock(window_closes),
             lock(json.dumps(astral_snapshot or {}, sort_keys=True)),
             json.dumps(reliability_snapshot or {}, sort_keys=True)))
        self.db.commit()
        return cur.lastrowid

    def record_choice(self, decision_id: int, chose: str) -> None:
        self._own_decision(decision_id)
        self.db.execute("UPDATE decision SET chose=?, chose_at=? WHERE id=?",
                        (self._lock_value(chose), _now(), decision_id))
        self.db.commit()

    def record_outcome(self, decision_id: int, outcome: str, rating: int) -> None:
        """Rating runs -2 (went badly) to +2 (went well). This is the eval set."""
        if not -2 <= rating <= 2:
            raise ValueError("rating must be between -2 and +2")
        self._own_decision(decision_id)
        self.db.execute(
            "UPDATE decision SET outcome=?, outcome_at=?, outcome_rating=?"
            " WHERE id=?", (self._lock_value(outcome), _now(),
                            self._lock_value(rating), decision_id))
        self.db.commit()

    def _open_decision(self, row: sqlite3.Row | None) -> dict | None:
        out = self._open("decision", row)
        if out is not None and out["outcome_rating"] is not None:
            out["outcome_rating"] = int(out["outcome_rating"])
        return out

    def decisions(self, person_id: int) -> list[dict]:
        self._own_person(person_id)
        return [self._open_decision(r) for r in self.db.execute(
            "SELECT * FROM decision WHERE person_id=? ORDER BY asked_at, id",
            (person_id,)).fetchall()]

    def decision(self, decision_id: int) -> dict:
        self._own_decision(decision_id)
        return self._open_decision(self.db.execute(
            "SELECT * FROM decision WHERE id=?", (decision_id,)).fetchone())

    def add_citation(self, decision_id: int, claim: str,
                     fact_kind: str, fact: dict) -> int:
        self._own_decision(decision_id)
        cur = self.db.execute(
            "INSERT INTO citation (decision_id, claim, fact_kind, fact)"
            " VALUES (?,?,?,?)",
            (decision_id, self._lock_value(claim), fact_kind,
             self._lock_value(json.dumps(fact, sort_keys=True))))
        self.db.commit()
        return cur.lastrowid

    def citations(self, decision_id: int) -> list[dict]:
        self._own_decision(decision_id)
        return [self._open("citation", r) for r in self.db.execute(
            "SELECT * FROM citation WHERE decision_id=? ORDER BY id",
            (decision_id,)).fetchall()]

    # -------------------------------------------------------------- settings

    # One table for the whole file, so not something an account may touch in
    # the shared database: a value set by one would be read by all.

    def set(self, key: str, value: str) -> None:
        if self.shared:
            raise PermissionError("settings are not per-account")
        self.db.execute(
            "INSERT INTO setting (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.db.commit()

    def get(self, key: str, default: str | None = None) -> str | None:
        if self.shared:
            raise PermissionError("settings are not per-account")
        value = self._setting(key)
        return default if value is None else value

    # --------------------------------------------------------------- context

    def context_prefix(self, person_id: int) -> str:
        """The stable, cacheable block describing this person.

        Byte-identical between requests as long as the underlying rows have not
        changed, which is what lets prompt caching work. Nothing volatile --
        no timestamps, no "today is..." -- may ever appear here.
        """
        person = self.person(person_id)
        row = self.active_chart_row(person_id)
        chart = self.compute(row)
        rel = self.reliability(row)

        lmt = " (birthplace local mean time)" if row["used_local_mean_time"] else ""
        out = [
            f"PERSON: {person['name']} ({person['relation']})",
            f"BIRTH: {row['birth_date']} {row['birth_time']} local, {row['place_name']}",
            f"  timezone {row['timezone_name']},"
            f" offset {row['utc_offset_hours']:+.4f}h{lmt}",
            f"  time confidence: {row['time_confidence']}",
            f"CHART: ayanamsa {row['ayanamsa']}, whole-sign houses",
            f"  Lagna {ephemeris.dms(chart.ascendant.degrees_in_sign)}"
            f" {chart.ascendant.sign} ({chart.ascendant.sign_english}),"
            f" {chart.ascendant.nakshatra} pada {chart.ascendant.pada}",
        ]
        out.extend(f"  {pos}" for pos in chart.positions)

        out.append("PERMITTED CLAIMS:")
        for claim in CLAIM_KINDS:
            out.append(f"  {claim}: {'yes' if rel.allows(claim) else 'NO'}")
        out.append(f"  dasha dates may be stated: {rel.date_precision}")

        events = self.life_events(person_id)
        if events:
            out.append("LIFE EVENTS:")
            for e in events:
                cat = f" [{e['category']}]" if e["category"] else ""
                out.append(f"  {e['happened_on']} ({e['precision']}){cat} {e['title']}")
        return "\n".join(out)
