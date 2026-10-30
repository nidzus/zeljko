"""The shared server, from the outside: sign-in, and isolation through every tool.

Starts the real server on a spare local port with an empty scratch database,
then behaves as Claude does: registers itself, is sent to the sign-in page,
exchanges the result for a token, and calls tools with it. Two friends are
set up, and one then tries every tool against everything the other owns.
"""
import sys
sys.path.insert(0, ".")

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx2

from backend.accounts import Accounts
from backend.confidence import TimeConfidence
from backend.store import Store

results = []


def check(name, ok, detail=""):
    # Coerce: passing a truthy non-bool (a dict, a list) would
    # otherwise corrupt the tally rather than fail loudly.
    ok = bool(ok)
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")


ROOT = Path(__file__).parent.resolve()
scratch = Path(tempfile.mkdtemp())
db = scratch / "shared.db"

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
BASE = f"http://localhost:{port}"
REDIRECT = "http://localhost:39917/callback"      # where "Claude" would listen


def launch(database: Path):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8",
           "JYOTISHA_SHARED_DB": str(database), "JYOTISHA_PORT": str(port),
           "JYOTISHA_PUBLIC_URL": BASE}
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend.remote"], cwd=str(scratch), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8")
    lines: list[str] = []
    # Drain the output, or a full pipe stalls the server (see verify_mcp_stdio).
    threading.Thread(target=lambda: lines.extend(proc.stdout), daemon=True).start()
    return proc, lines


print("=" * 72)
print("1. The shared server will not serve a personal database")
personal = scratch / "personal.db"
with Store(personal) as s:
    pid = s.add_person("Family Member")
    s.add_chart(pid, 1988, 3, 12, 16, 30, 0, "Belgrade, RS", 44.7866, 20.4489,
                TimeConfidence.EXACT)
proc, lines = launch(personal)
try:
    code = proc.wait(timeout=30)
except subprocess.TimeoutExpired:
    proc.kill()
    code = None
time.sleep(0.2)
check("it refuses to start", code == 1, " ".join(lines)[:110])

proc, lines = launch(db)
web = httpx2.Client(base_url=BASE, timeout=30, follow_redirects=False)
for _ in range(150):
    try:
        web.get("/.well-known/oauth-authorization-server")
        break
    except httpx2.HTTPError:
        time.sleep(0.2)


class Friend:
    """One person's Claude: a registered client holding that person's tokens."""

    def __init__(self):
        r = web.post("/register", json={
            "redirect_uris": [REDIRECT], "client_name": "check",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"})
        self.client_id = r.json()["client_id"]
        self.access = self.refresh = None
        self.recovery = None
        self._n = 0

    def start(self) -> str:
        """Ask to connect; returns the sign-in transaction Claude is sent to."""
        self.verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(
            self.verifier.encode()).digest()).decode().rstrip("=")
        r = web.get("/authorize", params={
            "response_type": "code", "client_id": self.client_id,
            "redirect_uri": REDIRECT, "code_challenge": challenge,
            "code_challenge_method": "S256", "state": "st",
            "resource": f"{BASE}/mcp"})
        return parse_qs(urlparse(r.headers["location"]).query)["tx"][0]

    def finish(self, response) -> bool:
        """Follow the redirect back to "Claude" and swap the code for tokens."""
        if response.status_code != 302:
            return False
        code = parse_qs(urlparse(response.headers["location"]).query)["code"][0]
        r = web.post("/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT, "client_id": self.client_id,
            "code_verifier": self.verifier})
        if r.status_code != 200:
            return False
        self.access, self.refresh = r.json()["access_token"], r.json()["refresh_token"]
        return True

    def join(self, email, invite, password):
        tx = self.start()
        page = web.post("/join", data={"tx": tx, "email": email, "invite": invite,
                                       "password": password, "again": password})
        found = re.search(r"class='code'>([A-Z0-9-]+)<", page.text)
        ticket = re.search(r"name='ticket' value='([^']+)'", page.text)
        if not (found and ticket):
            return page
        self.recovery = found.group(1)
        return self.finish(web.post("/continue", data={"ticket": ticket.group(1)}))

    def sign_in(self, email, password):
        tx = self.start()
        return self.finish(web.post("/signin", data={
            "tx": tx, "email": email, "password": password}))

    def rpc(self, method, params=None, token="use-mine"):
        self._n += 1
        token = self.access if token == "use-mine" else token
        headers = {"Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return web.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": self._n, "method": method,
            "params": params or {}})

    def call(self, tool, **arguments):
        """A tool call: (everything it returned as text, whether it failed)."""
        r = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        if r.status_code != 200:
            return f"HTTP {r.status_code}", True
        body = r.json()
        if "error" in body:
            return json.dumps(body["error"]), True
        result = body["result"]
        self.last = result
        text = "".join(c.get("text", "") for c in result.get("content", []))
        return text + json.dumps(result.get("structuredContent", "")), bool(
            result.get("isError"))

    def value(self, tool, **arguments):
        """A tool call's result as data."""
        text, err = self.call(tool, **arguments)
        if err:
            raise RuntimeError(f"{tool} failed: {text[:200]}")
        structured = self.last.get("structuredContent")
        if structured is not None:
            return structured.get("result", structured)
        return json.loads("".join(c.get("text", "")
                                  for c in self.last["content"]))


try:
    print()
    print("=" * 72)
    print("2. A call with no valid sign-in gets nothing")
    nobody = Friend()
    r = nobody.rpc("tools/list", token=None)
    check("no token: refused before any tool is reached", r.status_code == 401,
          f"HTTP {r.status_code}")
    check("and told where to sign in",
          "resource_metadata" in r.headers.get("www-authenticate", ""))
    for label, bad in [("a made-up token", "not-a-real-token"),
                       ("a guess of the right shape", secrets.token_urlsafe(32))]:
        r = nobody.rpc("tools/call", {"name": "list_people", "arguments": {}},
                       token=bad)
        check(f"{label}: refused", r.status_code == 401
              and "person_id" not in r.text, f"HTTP {r.status_code}")
    meta = web.get("/.well-known/oauth-authorization-server").json()
    check("Claude can discover how to register and sign in",
          all(k in meta for k in ("authorization_endpoint", "token_endpoint",
                                  "registration_endpoint"))
          and "S256" in meta.get("code_challenge_methods_supported", []))

    print()
    print("=" * 72)
    print("3. Invite-only, through the real sign-in pages")
    acc = Accounts(db)
    stranger = Friend()
    page = stranger.join("stranger@example.com", "AAAA-BBBB-CCCC-DDDD",
                         "a long password")
    check("a stranger with a guessed code is turned away",
          page is not True and stranger.access is None
          and "do not match" in getattr(page, "text", ""))
    check("and no account was made for them", acc.listing() == [])
    check("signing in to an account that does not exist fails",
          stranger.sign_in("stranger@example.com", "a long password") is False)

    A, B, C = Friend(), Friend(), Friend()
    code_a = acc.invite("ana@example.com", "Ana")
    code_b = acc.invite("boris@example.com", "Boris")
    code_c = acc.invite("cveta@example.com", "Cveta")
    check("an invited friend registers and is signed in",
          A.join("ana@example.com", code_a, "ana's long password") is True
          and B.join("boris@example.com", code_b, "boris's long password") is True
          and C.join("cveta@example.com", code_c, "cveta's long password") is True)
    check("each is shown a recovery code once",
          A.recovery and B.recovery and A.recovery != B.recovery, A.recovery[:4] + "-...")
    check("the same invite code cannot be used again",
          Friend().join("ana@example.com", code_a, "ana's long password") is not True)
    A2 = Friend()
    check("afterwards they sign in with email and password",
          A2.sign_in("ana@example.com", "ana's long password") is True)
    check("a wrong password does not sign in",
          Friend().sign_in("ana@example.com", "boris's long password") is False)
    stale = A.start()
    check("a sign-in page cannot be replayed with an invented transaction",
          web.post("/signin", data={"tx": "invented", "email": "ana@example.com",
                                    "password": "ana's long password"}
                   ).status_code == 400)

    print()
    print("=" * 72)
    print("4. What a friend's Claude is given without the plugin")
    init = A.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "check", "version": "1"}}).json()
    ins = init["result"].get("instructions", "")
    check("the instructions open by pointing at the guidance",
          ins.startswith("START HERE") and "guidance" in ins[:600])
    check("and carry the advisor's voice from SYSTEM_RULES",
          "never calculate" in ins.lower())
    prompts = A.rpc("prompts/list").json()["result"]["prompts"]
    check("onboard, ask and journal are offered as prompts",
          sorted(p["name"] for p in prompts) == ["ask", "journal", "onboard"])
    asked = A.rpc("prompts/get", {"name": "ask", "arguments": {
        "question": "Should I move?"}}).json()["result"]["messages"][0]["content"]["text"]
    check("the ask prompt carries the question and the skill's own text",
          "Should I move?" in asked and "past_decisions" in asked
          and "$ARGUMENTS" not in asked)
    guide, err = A.call("guidance", topic="onboard")
    check("the guidance tool serves the onboarding steps",
          not err and "How well that time is known" in guide)
    tools = A.rpc("tools/list").json()["result"]["tools"]
    check("all twenty-seven tools are there, plus guidance", len(tools) == 28,
          f"{len(tools)} tools")

    print()
    print("=" * 72)
    print("5. A new account starts empty and sees nobody")
    text, err = C.call("list_people")
    check("no profiles are listed", "Private" not in text and "person_id" not in text)

    def setup(friend, name, place, question, event):
        made = friend.value("create_profile", name=name, birth_date="1988-03-12",
                            birth_time="16:30", place_name=place,
                            latitude=44.7866, longitude=20.4489,
                            time_confidence="REMEMBERED")
        friend.call("add_life_event", happened_on="2011-04-15", title=event)
        saved = friend.value("record_decision", question=question,
                             verdict=f"verdict for {name}",
                             window_opens="2026-12-01", relied_on=[f"fact of {name}"])
        return made["person_id"], saved["decision_id"]

    a_pid, a_did = setup(A, "Ana Private", "Anatown", "Should Ana leave the firm?",
                         "Ana was promoted")
    b_pid, b_did = setup(B, "Boris Private", "Boristown",
                         "Should Boris sell the flat?", "Boris moved out")
    B_MARKS = ["Boris", "Boristown", "sell the flat", "moved out",
               str(b_pid), str(b_did)]

    text, _ = A.call("chart_context")
    check("with one profile of their own, a friend need not name it",
          "Ana Private" in text and "Ana was promoted" in text)
    text, err = C.call("chart_context")
    check("an account with no profile is NOT handed someone else's only one",
          err and "No profiles yet" in text and "Private" not in text, text[:80])
    text, _ = A.call("list_people")
    check("A's list holds A's profile and not B's",
          "Ana Private" in text and "Boris" not in text)
    text, _ = A.call("past_decisions")
    check("A's journal holds A's decision and not B's",
          "leave the firm" in text and "Boris" not in text)

    print()
    print("=" * 72)
    print("6. A tries every tool against everything B owns")
    print("   By B's profile id, by B's name, and by B's decision id. The answer")
    print("   must be an error, must contain nothing of B's, and must read the")
    print("   same as the answer for something that does not exist at all.")
    FILL = {"date": "2026-11-15", "start": "2026-11-01", "end": "2026-12-01",
            "varga": 9, "body": "Saturn", "candidates": ["10:00"], "house": 10,
            "birth_time": "10:00", "note": "planted", "question": "planted?",
            "verdict": "planted", "happened_on": "2020-01-01", "title": "planted",
            "chose": "planted", "outcome": "planted", "rating": 1}
    NO_IDENTIFIER = {"list_people", "search_places", "parse_coordinates",
                     "create_profile", "guidance"}
    ABSENT_ID, ABSENT_NAME = 987654321, "Nemo Nobody"

    def blank(text, *words):
        for w in words:
            text = text.replace(str(w), "#")
        return text

    problems, unknown, probed = [], [], 0
    for t in tools:
        props = t["inputSchema"].get("properties", {})
        required = t["inputSchema"].get("required", [])
        ids = [p for p in props if p.endswith("_id")]
        if set(ids) - {"person_id", "decision_id"}:
            unknown.append(f"{t['name']} takes {ids}")
        if not ids:
            if t["name"] not in NO_IDENTIFIER:
                unknown.append(f"{t['name']} takes no id but is not listed")
            continue
        base = {k: FILL[k] for k in required if k not in ids}
        attempts = []
        if "person_id" in props:
            attempts += [("person_id", b_pid, ABSENT_ID),
                         ("person_id", str(b_pid), str(ABSENT_ID)),
                         ("person_id", "Boris Private", ABSENT_NAME),
                         ("person_id", "boris", ABSENT_NAME)]
        if "decision_id" in props:
            attempts += [("decision_id", b_did, ABSENT_ID)]
        for field, theirs, absent in attempts:
            probed += 1
            got, err = A.call(t["name"], **base, **{field: theirs})
            none, _ = A.call(t["name"], **base, **{field: absent})
            where = f"{t['name']}({field}={theirs!r})"
            if not err:
                problems.append(f"{where} was answered")
            if any(m in blank(got, theirs) for m in B_MARKS):
                problems.append(f"{where} mentions B: {got[:90]}")
            if blank(got, theirs) != blank(none, absent):
                problems.append(f"{where} differs from a missing one: "
                                f"{got[:70]!r} vs {none[:70]!r}")
    check("every tool is covered by the attempt", not unknown,
          "; ".join(unknown) if unknown else
          f"{probed} attempts across {len(tools) - len(NO_IDENTIFIER)} tools")
    check("every attempt is refused",
          not [p for p in problems if "answered" in p], "; ".join(problems)[:300])
    check("no refusal reveals anything of B's",
          not [p for p in problems if "mentions" in p], "; ".join(problems)[:300])
    check("B's things are indistinguishable from things that do not exist",
          not [p for p in problems if "differs" in p], "; ".join(problems)[:300])

    text, _ = B.call("chart_context")
    journal, _ = B.call("past_decisions")
    check("nothing A tried was written into B's account",
          "planted" not in text and "planted" not in journal
          and "2020-01-01" not in text
          and "BIRTH: 1988-03-12 16:30:00" in text)
    check("B still sees its own profile, event and decision intact",
          "Boris Private" in text and "Boris moved out" in text
          and "sell the flat" in journal and '"chose": null' in journal.replace("None", "null"))
    made = A.value("create_profile", name="Boris Private", birth_date="1990-01-01",
                   birth_time="10:00", place_name="Anatown", latitude=44.0,
                   longitude=20.0, time_confidence="EXACT")
    check("A may use a name B also uses, without colliding",
          made.get("person_id") not in (None, b_pid)
          and "Boristown" not in A.call("chart_context", person_id="Boris Private")[0])

    print()
    print("=" * 72)
    print("7. The journal is locked in the file the server writes")
    raw = db.read_bytes()
    found = [m for m in (b"leave the firm", b"sell the flat", b"Ana was promoted",
                         b"Boris moved out", b"verdict for", b"fact of",
                         b"2011-04-15") if m in raw]
    check("no question, verdict, event or citation is readable in it", not found,
          f"found {found}" if found else f"searched {len(raw)} bytes")
    check("no token or password is stored in it",
          not any(s.encode() in raw for s in (A.access, A.refresh, B.access,
                                              "ana's long password")))

    print()
    print("=" * 72)
    print("8. Tokens: refreshed, signed out, and cut off")
    old_refresh, old_access = B.refresh, B.access
    r = web.post("/token", data={"grant_type": "refresh_token",
                                 "refresh_token": old_refresh,
                                 "client_id": B.client_id})
    B.access = r.json().get("access_token")
    check("a refresh gives a working new token, still B's",
          r.status_code == 200 and "Boris Private" in B.call("list_people")[0])
    check("a used refresh token is dead",
          web.post("/token", data={"grant_type": "refresh_token",
                                   "refresh_token": old_refresh,
                                   "client_id": B.client_id}).status_code == 400)
    check("one friend's refresh token is no use to another's Claude",
          web.post("/token", data={"grant_type": "refresh_token",
                                   "refresh_token": r.json()["refresh_token"],
                                   "client_id": A.client_id}).status_code == 400)

    acc.disable("ana@example.com")
    check("disabling an account cuts off its live token at once",
          A.rpc("tools/list").status_code == 401
          and A2.rpc("tools/list").status_code == 401)
    check("and its refresh token",
          web.post("/token", data={"grant_type": "refresh_token",
                                   "refresh_token": A.refresh,
                                   "client_id": A.client_id}).status_code == 400)
    check("and it cannot sign in again",
          Friend().sign_in("ana@example.com", "ana's long password") is False)
    check("the other account carries on",
          "Boris Private" in B.call("list_people")[0])
    acc.delete("boris@example.com")
    check("deleting an account ends its access too",
          B.rpc("tools/list").status_code == 401)
    check("and its profile is gone from the file",
          b"Boris Private" not in Path(db).read_bytes()
          or acc.db.execute("SELECT COUNT(*) FROM person WHERE name="
                            "'Boris Private' AND account_id NOT IN "
                            "(SELECT id FROM account WHERE email="
                            "'ana@example.com')").fetchone()[0] == 0)
    acc.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

print()
print("=" * 72)
print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
