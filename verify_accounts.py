"""Accounts: one account cannot reach, change, or detect another's data.

This suite works on the storage layer directly. verify_remote.py repeats the
proof from the outside, through every tool over HTTP.
"""
import sys
sys.path.insert(0, ".")

import inspect
import sqlite3
import tempfile
from pathlib import Path

from cryptography.fernet import InvalidToken

from backend.accounts import AccountError, Accounts
from backend.confidence import TimeConfidence
from backend.store import LOCKED, Store

results = []
BG = (44.7866, 20.4489)


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


def raises(kind, fn):
    try:
        fn()
    except kind as exc:
        return str(exc) or kind.__name__
    except Exception as exc:                # noqa: BLE001 -- wrong kind is a fail
        return None if kind else str(exc)
    return None


scratch = Path(tempfile.mkdtemp())

print("=" * 72)
print("1. A database from before accounts is migrated to one owner")
old = scratch / "old.db"
con = sqlite3.connect(old)
con.executescript("""
CREATE TABLE person (id INTEGER PRIMARY KEY, name TEXT NOT NULL, relation TEXT,
                     notes TEXT, created_at TEXT NOT NULL);
INSERT INTO person (name, relation, created_at) VALUES ('First', 'self', '2026-01-01');
INSERT INTO person (name, relation, created_at) VALUES ('Second', 'partner', '2026-01-02');
""")
con.commit()
con.close()
with Store(old) as s:
    people = s.people()
    owners = s.db.execute("SELECT * FROM account").fetchall()
    check("every existing profile is still there", [p["name"] for p in people]
          == ["First", "Second"])
    check("there is exactly one account, the owner",
          len(owners) == 1 and owners[0]["is_owner"] == 1)
    check("and every profile belongs to it",
          all(p["account_id"] == owners[0]["id"] for p in people))
    # A copy of the old code still running writes rows with no owner.
    s.db.execute("INSERT INTO person (name, created_at) VALUES ('Late', 'x')")
    s.db.commit()
with Store(old) as s:
    check("a row written by the old code is adopted on the next open",
          len(s.people()) == 3
          and s.db.execute("SELECT COUNT(*) FROM person WHERE account_id"
                           " IS NULL").fetchone()[0] == 0)
    check("opening twice does not create a second owner",
          s.db.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 1)

print()
print("=" * 72)
print("2. Nobody can sign themselves up")
shared = scratch / "shared.db"
acc = Accounts(shared)
check("registering without an invitation is refused",
      raises(AccountError, lambda: acc.register("stranger@example.com",
                                                "AAAA-BBBB-CCCC-DDDD",
                                                "a long password")))
check("and created nothing", acc.listing() == [])
code_a = acc.invite("Ana@Example.com", "Ana")
code_b = acc.invite("boris@example.com", "Boris")
check("a wrong invite code is refused",
      raises(AccountError, lambda: acc.register("ana@example.com",
                                                "AAAA-BBBB-CCCC-DDDD",
                                                "a long password")))
check("one person's code does not work for another's email",
      raises(AccountError, lambda: acc.register("ana@example.com", code_b,
                                                "a long password")))
check("a short password is refused",
      raises(AccountError, lambda: acc.register("ana@example.com", code_a,
                                                "short")))
a_id, a_key, a_recovery = acc.register("ana@example.com", code_a.lower(),
                                       "ana's long password")
b_id, b_key, b_recovery = acc.register("boris@example.com", code_b,
                                       "boris's long password")
check("the right code and email make a working account",
      acc.sign_in("ANA@example.com", "ana's long password") == (a_id, a_key))
check("an invite code works once",
      raises(AccountError, lambda: acc.register("ana@example.com", code_a,
                                                "another long password")))
check("a wrong password gets nothing",
      acc.sign_in("ana@example.com", "boris's long password") is None)
check("an unknown email gets the same nothing",
      acc.sign_in("nobody@example.com", "ana's long password") is None)
code_c = acc.invite("late@example.com")
acc.db.execute("UPDATE account SET invite_expires='2020-01-01T00:00:00+00:00'"
               " WHERE email='late@example.com'")
acc.db.commit()
check("an expired invitation is refused",
      raises(AccountError, lambda: acc.register(
          "late@example.com", code_c, "a long password")))
check("stored secrets are not the secrets themselves",
      not any(secret in str(dict(r)) for r in acc.db.execute(
          "SELECT * FROM account") for secret in
              ("ana's long password", code_a, a_recovery, a_key.decode())))

print()
print("=" * 72)
print("3. The shared database opens only for a signed-in account")
check("not without an account", raises(PermissionError, lambda: Store(shared)))
check("not without that account's key",
      raises(PermissionError, lambda: Store(shared, account_id=a_id)))
check("not for an account that does not exist",
      raises(PermissionError, lambda: Store(shared, account_id=999, key=a_key)))
check("and the account tool refuses a personal database",
      raises(PermissionError, lambda: Accounts(old)))

A = Store(shared, account_id=a_id, key=a_key)
B = Store(shared, account_id=b_id, key=b_key)


def fill(store, name, question, event):
    pid = store.add_person(name, relation="self")
    cid = store.add_chart(pid, 1988, 3, 12, 16, 30, 0, "Belgrade, RS", *BG,
                          TimeConfidence.REMEMBERED,
                          rectification_note=f"note for {name}")
    eid = store.add_life_event(pid, "2011-04-15", event, category="career")
    conv = store.start_conversation(pid, f"talk of {name}")
    store.add_message(conv, "user", question)
    did = store.record_decision(pid, cid, question, question_type="career",
                                conversation_id=conv, verdict=f"verdict {name}",
                                window_opens="2026-12-01")
    store.add_citation(did, f"claim of {name}", "cited", {"stated": name})
    return {"pid": pid, "cid": cid, "eid": eid, "conv": conv, "did": did}


a = fill(A, "Ana Private", "Should Ana leave the firm?", "Ana was promoted")
b = fill(B, "Boris Private", "Should Boris sell the flat?", "Boris moved out")

print()
print("=" * 72)
print("4. Each account sees its own data and only its own")
check("A lists only A's profile", [p["name"] for p in A.people()] == ["Ana Private"])
check("B lists only B's profile", [p["name"] for p in B.people()] == ["Boris Private"])
check("A reads its own journal back unlocked",
      A.decisions(a["pid"])[0]["question"] == "Should Ana leave the firm?"
      and A.life_events(a["pid"])[0]["title"] == "Ana was promoted"
      and A.citations(a["did"])[0]["claim"] == "claim of Ana Private"
      and A.messages(a["conv"])[0]["content"] == "Should Ana leave the firm?"
      and A.active_chart_row(a["pid"])["rectification_note"] == "note for Ana Private")
A.record_choice(a["did"], "Stayed")
A.record_outcome(a["did"], "Promoted again", 2)
check("choice and outcome round-trip through the lock",
      A.decision(a["did"])["chose"] == "Stayed"
      and A.decision(a["did"])["outcome_rating"] == 2)
check("ids in the shared database are not a running count",
      min(a["pid"], b["pid"], a["did"], b["did"]) >= 1000
      and abs(a["pid"] - b["pid"]) > 1)

print()
print("=" * 72)
print("5. Every store method, called by A with B's ids, gets nothing")
print("   An id that is someone else's must behave exactly like an id that")
print("   does not exist. The table below must name every public method.")
chart_b = B.active_chart_row(b["pid"])
MISSING = 987654321                       # an id nobody has


def probes(pid, cid, conv, did):
    """Each method reaching for the given ids, as A."""
    return {
        "person": lambda: A.person(pid),
        "add_chart": lambda: A.add_chart(pid, 1990, 1, 1, 1, 1, 0, "x", *BG,
                                         TimeConfidence.EXACT),
        "active_chart_row": lambda: A.active_chart_row(pid),
        "chart_versions": lambda: A.chart_versions(pid),
        "add_life_event": lambda: A.add_life_event(pid, "2020-01-01", "planted"),
        "life_events": lambda: A.life_events(pid),
        "start_conversation": lambda: A.start_conversation(pid, "planted"),
        "add_message": lambda: A.add_message(conv, "user", "planted"),
        "messages": lambda: A.messages(conv),
        "record_decision": lambda: A.record_decision(pid, cid, "planted"),
        "record_choice": lambda: A.record_choice(did, "planted"),
        "record_outcome": lambda: A.record_outcome(did, "planted", 1),
        "decisions": lambda: A.decisions(pid),
        "decision": lambda: A.decision(did),
        "add_citation": lambda: A.add_citation(did, "planted", "cited", {}),
        "citations": lambda: A.citations(did),
        "context_prefix": lambda: A.context_prefix(pid),
    }


# Methods that take no id of a stored thing, with the reason each is safe.
NO_ID = {
    "close": "closes the connection",
    "people": "lists the caller's own profiles (checked in section 4)",
    "add_person": "creates a profile in the caller's own account",
    "compute": "pure arithmetic on a row the caller already holds",
    "dasha_tree": "pure arithmetic on a row the caller already holds",
    "reliability": "pure arithmetic on a row the caller already holds",
    "set": "refused in the shared database (checked below)",
    "get": "refused in the shared database (checked below)",
}

before = B.db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
snapshot = lambda: [  # noqa: E731
    [tuple(r) for r in B.db.execute(f"SELECT * FROM {t} ORDER BY 1")]
    for t in ("person", "chart", "life_event", "conversation", "message",
              "decision", "citation")]
state = snapshot()

foreign = probes(b["pid"], b["cid"], b["conv"], b["did"])
absent = probes(MISSING, MISSING, MISSING, MISSING)
public = {n for n, m in inspect.getmembers(Store, inspect.isfunction)
          if not n.startswith("_")}
uncovered = public - set(foreign) - set(NO_ID)
check("every public store method is accounted for", not uncovered,
      f"not covered: {sorted(uncovered)}" if uncovered
      else f"{len(foreign)} probed, {len(NO_ID)} take no id")

leaks = []
for name in sorted(foreign):
    theirs = raises(KeyError, foreign[name])
    none = raises(KeyError, absent[name])
    if theirs is None:
        leaks.append(f"{name} did not refuse")
    elif none is None or theirs.replace(str(b["pid"]), "#").replace(
            str(b["did"]), "#").replace(str(b["conv"]), "#").replace(
            str(b["cid"]), "#") != none.replace(str(MISSING), "#"):
        leaks.append(f"{name} answers differently for a real id: "
                     f"{theirs!r} vs {none!r}")
check("each one refuses B's id", not [l for l in leaks if "refuse" in l],
      "; ".join(leaks)[:300])
check("and refuses it in the same words as an id that does not exist",
      not leaks, "; ".join(leaks)[:300])
check("nothing of B's was changed by the attempts", snapshot() == state)
check("A's chart cannot be hung on B's person, nor B's chart on A's decision",
      raises(KeyError, lambda: A.record_decision(a["pid"], b["cid"], "x"))
      and raises(KeyError, lambda: A.add_chart(
          a["pid"], 1990, 1, 1, 1, 1, 0, "x", *BG, TimeConfidence.EXACT,
          derived_from_id=b["cid"])))
check("a decision cannot be filed under someone else's conversation",
      raises(KeyError, lambda: A.record_decision(
          a["pid"], a["cid"], "x", conversation_id=b["conv"])))
check("the settings table is closed to accounts",
      raises(PermissionError, lambda: A.set("k", "v"))
      and raises(PermissionError, lambda: A.get("mode")))

print()
print("=" * 72)
print("6. The journal cannot be read from the database file")
A.db.commit()
B.db.commit()
raw = shared.read_bytes()
secrets_in_file = [s for s in (
    b"Should Ana leave the firm", b"Ana was promoted", b"verdict Ana",
    b"claim of Ana", b"talk of Ana", b"note for Ana", b"Stayed",
    b"Promoted again", b"Should Boris sell the flat", b"Boris moved out",
    b"2011-04-15", b"2026-12-01") if s in raw]
check("no question, verdict, choice, outcome, event or date is in the file",
      not secrets_in_file, f"found: {secrets_in_file}" if secrets_in_file
      else f"searched {len(raw)} bytes")
check("names and birth data are readable, as agreed",
      b"Ana Private" in raw and b"Belgrade, RS" in raw and b"1988-03-12" in raw)
stored = dict(B.db.execute("SELECT * FROM decision WHERE id=?",
                           (a["did"],)).fetchone())
check("every locked column of a decision is stored locked",
      all(str(stored[f]).startswith("enc:v1:") for f in LOCKED["decision"]
          if stored[f] is not None),
      ", ".join(f for f in LOCKED["decision"] if stored[f] is not None))
wrong = Store(shared, account_id=a_id, key=b_key)
check("another account's key does not open it",
      raises(InvalidToken, lambda: wrong.decisions(a["pid"])))
wrong.close()

print()
print("=" * 72)
print("7. Sign-in tokens carry the key; the database alone does not")
acc.put_grant("access", "token-one", a_id, "client", "fam", {"scopes": []},
              a_key, 3600)
g = acc.grant("access", "token-one")
check("a good token gives back the account and its key",
      g and g["account_id"] == a_id and g["key"] == a_key)
check("an unknown token gives nothing", acc.grant("access", "token-two") is None)
check("a token of the wrong kind gives nothing",
      acc.grant("refresh", "token-one") is None)
row = dict(acc.db.execute("SELECT * FROM oauth_grant").fetchone())
check("neither the token nor the key is stored",
      "token-one" not in str(row) and a_key.decode() not in str(row))
acc.put_grant("access", "token-old", a_id, "client", "fam", {"scopes": []},
              a_key, -10)
check("an expired token gives nothing", acc.grant("access", "token-old") is None)

print()
print("=" * 72)
print("8. Managing accounts")
rows = {r["email"]: r for r in acc.listing()}
check("the list shows counts, not content",
      rows["ana@example.com"]["profiles"] == 1
      and rows["ana@example.com"]["decisions"] == 1
      and "Ana" not in str({k: v for k, v in rows["ana@example.com"].items()
                            if k not in ("email", "display_name")}))

acc.disable("ana@example.com")
check("a disabled account cannot sign in",
      acc.sign_in("ana@example.com", "ana's long password") is None)
check("its tokens stop working at once", acc.grant("access", "token-one") is None)
check("and its store will not open",
      raises(PermissionError, lambda: Store(shared, account_id=a_id, key=a_key)))
check("its data is kept", acc.listing()[0]["profiles"] == 1)
acc.enable("ana@example.com")
check("enabling lets it back in",
      acc.sign_in("ana@example.com", "ana's long password") is not None)

found = acc.recover("ana@example.com", a_recovery, "ana's second password")
check("the recovery code sets a new password and keeps the journal",
      found and found[1] == a_key
      and acc.sign_in("ana@example.com", "ana's second password") == (a_id, a_key)
      and acc.sign_in("ana@example.com", "ana's long password") is None)
check("the recovery code is replaced once used",
      acc.recover("ana@example.com", a_recovery, "a third long password") is None
      and found[2] != a_recovery)
check("a wrong recovery code gets nothing",
      acc.recover("boris@example.com", a_recovery, "a long password") is None)

new_code = acc.reset("boris@example.com")
left = B.db.execute(
    "SELECT (SELECT COUNT(*) FROM person WHERE account_id=?),"
    " (SELECT COUNT(*) FROM decision WHERE person_id=?),"
    " (SELECT COUNT(*) FROM life_event WHERE person_id=?),"
    " (SELECT COUNT(*) FROM citation WHERE decision_id=?)",
    (b_id, b["pid"], b["pid"], b["did"])).fetchone()
check("a reset keeps the profile and deletes what the lost key locked",
      tuple(left) == (1, 0, 0, 0), f"profiles, decisions, events, citations: {tuple(left)}")
check("the old password no longer signs in",
      acc.sign_in("boris@example.com", "boris's long password") is None)
b2 = acc.register("boris@example.com", new_code, "boris's new password")
check("and the new invite code registers the same account again",
      b2[0] == b_id and b2[1] != b_key)

counts = acc.delete("ana@example.com")
remaining = sum(acc.db.execute(
    f"SELECT COUNT(*) FROM {t} WHERE {col} IN ({','.join('?' * len(ids))})",
    ids).fetchone()[0] for t, col, ids in (
        ("account", "id", [a_id]), ("person", "id", [a["pid"]]),
        ("chart", "person_id", [a["pid"]]),
        ("life_event", "person_id", [a["pid"]]),
        ("conversation", "person_id", [a["pid"]]),
        ("message", "conversation_id", [a["conv"]]),
        ("decision", "person_id", [a["pid"]]),
        ("citation", "decision_id", [a["did"]]),
        ("oauth_grant", "account_id", [a_id])))
check("deleting an account removes every row it owned", remaining == 0
      and counts == {"profiles": 1, "decisions": 1},
      f"{remaining} rows left; removed {counts}")
check("and leaves the other account alone",
      [r["email"] for r in acc.listing() if r["status"] == "active"]
      == ["boris@example.com"] and acc.listing()[0]["profiles"] == 1)
check("an unknown email is reported, not ignored",
      raises(AccountError, lambda: acc.delete("ana@example.com")))

A.close()
B.close()
acc.close()
print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
