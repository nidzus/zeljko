"""The shared server: the same tools over HTTP, behind a sign-in.

Friends add this to their own Claude as a custom connector. Claude sends them
to the sign-in page here; once they are through, every call it makes carries a
token that stands for exactly one account, and the tools are handed that
account's store and nothing else.

It serves the shared database only. It will not open a personal one, and it
has no code path that reaches the family data.

Run it with  python jyotisha.py serve  (or "Start shared server").
"""
from __future__ import annotations

import functools
import html
import os
import sys
import threading
import time
from urllib.parse import urlparse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, RefreshToken,
    TokenError, construct_redirect_uri)
from mcp.server.auth.settings import (
    AuthSettings, ClientRegistrationOptions, RevocationOptions)
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from . import guidance as guides
from . import mcp_server, vault
from .accounts import AccountError, Accounts, MIN_PASSWORD, SHARED_DB
from .store import Store

CODE_SECONDS = 5 * 60
ACCESS_SECONDS = 60 * 60
REFRESH_SECONDS = 60 * 24 * 60 * 60
SIGNIN_PAGE_SECONDS = 15 * 60
IDLE_SECONDS = 15 * 60          # how long an unused account's key stays in memory
MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60
# The AGPL asks that people who use this over a network can get its source.
# Point it at your own copy if you run a changed version.
SOURCE_URL = os.environ.get("JYOTISHA_SOURCE_URL", "https://github.com/nidzus/jyotisha")

INSTRUCTIONS = """START HERE

The person reaches you through a connector and has nothing else installed, so
the working guidance comes from the guidance tool. Call list_people first. If
it comes back empty they are new: call guidance with topic "onboard" and
follow it. Before advising on a decision call guidance with topic "ask";
before reviewing past advice, topic "journal". Once per conversation each.

They see only their own profiles and their own journal.

""" + mcp_server.INSTRUCTIONS


class Provider:
    """Sign-in for Claude, in the shape the MCP library asks for.

    Nothing secret is stored as it was issued. Codes and tokens are kept as
    fingerprints, and each carries the account's data key wrapped under
    itself -- so the key can be recovered from a token Claude presents, and
    from nothing that is in the database.
    """

    def __init__(self, accounts: Accounts, public_url: str):
        self.accounts = accounts
        self.public_url = public_url.rstrip("/")
        # Sign-ins in progress. Short-lived, and gone if the server restarts,
        # in which case the person simply starts connecting again.
        self.pending: dict[str, tuple[str, AuthorizationParams, float]] = {}
        self.ready: dict[str, tuple[str, int, bytes, float]] = {}
        self.failures: dict[str, tuple[int, float]] = {}

    # -- clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        info = self.accounts.client(client_id)
        return OAuthClientInformationFull.model_validate_json(info) if info else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.accounts.save_client(client_info.client_id,
                                  client_info.model_dump_json())

    # -- the sign-in itself

    async def authorize(self, client: OAuthClientInformationFull,
                        params: AuthorizationParams) -> str:
        now = time.time()
        for stale in [k for k, v in self.pending.items() if v[2] < now]:
            del self.pending[stale]
        tx = vault.new_token()
        self.pending[tx] = (client.client_id, params, now + SIGNIN_PAGE_SECONDS)
        return f"{self.public_url}/signin?tx={tx}"

    def open_sign_in(self, tx: str) -> bool:
        entry = self.pending.get(tx)
        return entry is not None and entry[2] >= time.time()

    def complete(self, tx: str, account_id: int, key: bytes) -> str | None:
        """Finish a sign-in: the address to send the browser back to Claude."""
        entry = self.pending.pop(tx, None)
        if entry is None or entry[2] < time.time():
            return None
        client_id, params, _ = entry
        code = vault.new_token()
        self.accounts.put_grant(
            "code", code, account_id, client_id, family=vault.new_token(),
            detail={"scopes": params.scopes or [],
                    "code_challenge": params.code_challenge,
                    "redirect_uri": str(params.redirect_uri),
                    "explicit": params.redirect_uri_provided_explicitly,
                    "resource": params.resource},
            key=key, ttl_seconds=CODE_SECONDS)
        return construct_redirect_uri(str(params.redirect_uri), code=code,
                                      state=params.state)

    def locked_out(self, email: str) -> bool:
        count, until = self.failures.get(email.strip().lower(), (0, 0.0))
        return count >= MAX_FAILURES and until > time.time()

    def failed(self, email: str) -> None:
        email = email.strip().lower()
        count, until = self.failures.get(email, (0, 0.0))
        if until < time.time():
            count = 0
        self.failures[email] = (count + 1, time.time() + LOCKOUT_SECONDS)

    def succeeded(self, email: str) -> None:
        self.failures.pop(email.strip().lower(), None)

    # -- codes and tokens

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        g = self.accounts.grant("code", authorization_code)
        if g is None or g["client_id"] != client.client_id:
            return None
        d = g["detail"]
        return AuthorizationCode(
            code=authorization_code, scopes=d["scopes"],
            expires_at=g["expires_at"], client_id=g["client_id"],
            code_challenge=d["code_challenge"], redirect_uri=d["redirect_uri"],
            redirect_uri_provided_explicitly=d["explicit"],
            resource=d["resource"], subject=str(g["account_id"]))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        g = self.accounts.grant("code", authorization_code.code, take=True)
        if g is None or g["client_id"] != client.client_id:
            raise TokenError("invalid_grant", "authorization code is not valid")
        return self._issue(g, g["detail"]["scopes"])

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> RefreshToken | None:
        g = self.accounts.grant("refresh", refresh_token)
        if g is None or g["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=g["client_id"],
                            scopes=g["detail"]["scopes"],
                            expires_at=g["expires_at"],
                            subject=str(g["account_id"]))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        g = self.accounts.grant("refresh", refresh_token.token, take=True)
        if g is None or g["client_id"] != client.client_id:
            raise TokenError("invalid_grant", "refresh token is not valid")
        return self._issue(g, scopes)

    def _issue(self, g: dict, scopes: list[str]) -> OAuthToken:
        access, refresh = vault.new_token(), vault.new_token()
        detail = {"scopes": scopes, "resource": g["detail"].get("resource")}
        for kind, secret, ttl in (("access", access, ACCESS_SECONDS),
                                  ("refresh", refresh, REFRESH_SECONDS)):
            self.accounts.put_grant(kind, secret, g["account_id"],
                                    g["client_id"], g["family"], detail,
                                    g["key"], ttl)
        self.accounts.seen(g["account_id"])
        return OAuthToken(access_token=access, expires_in=ACCESS_SECONDS,
                          refresh_token=refresh,
                          scope=" ".join(scopes) or None)

    async def load_access_token(self, token: str) -> AccessToken | None:
        g = self.accounts.grant("access", token)
        if g is None:
            return None
        return AccessToken(token=token, client_id=g["client_id"],
                           scopes=g["detail"]["scopes"],
                           expires_at=g["expires_at"],
                           resource=g["detail"].get("resource"),
                           subject=str(g["account_id"]))

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self.accounts.drop_family(token.token)

    async def exchange_identity_assertion(self, client, params) -> OAuthToken:
        raise TokenError("unsupported_grant_type",
                         "this server does not accept identity assertions")


# ------------------------------------------------------------------- pages

STYLE = """
body{font:16px/1.5 system-ui,sans-serif;background:#f6f4ef;color:#1d1b16;margin:0}
main{max-width:26rem;margin:8vh auto;padding:2rem;background:#fff;border-radius:10px;
 box-shadow:0 1px 4px rgba(0,0,0,.12)}
h1{font-size:1.3rem;margin:0 0 1rem}
label{display:block;margin:.9rem 0 .25rem;font-size:.9rem}
input{width:100%;box-sizing:border-box;padding:.6rem;font:inherit;border:1px solid #b9b3a5;
 border-radius:6px}
button{margin-top:1.3rem;width:100%;padding:.7rem;font:inherit;border:0;border-radius:6px;
 background:#5b3a8c;color:#fff;cursor:pointer}
.err{background:#fbe9e7;border:1px solid #d9796b;padding:.6rem .8rem;border-radius:6px}
.code{font:1.25rem/1.6 ui-monospace,monospace;background:#f1eee6;padding:.8rem;
 border-radius:6px;text-align:center;letter-spacing:.05em;user-select:all}
p.small,nav{font-size:.9rem;color:#5d584c}nav{margin-top:1.4rem}nav a{margin-right:1rem}
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><main><h1>{html.escape(title)}</h1>{body}"
        f"<p class='small'>Free software under the AGPL-3.0: "
        f"<a href='{html.escape(SOURCE_URL)}'>source code</a>.</p></main></body></html>",
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                 "Referrer-Policy": "no-referrer"})


def _expired() -> HTMLResponse:
    return _page("This sign-in has expired",
                 "<p>Go back to Claude and connect the Jyotisha connector "
                 "again. Nothing was changed.</p>", 400)


def _error(message: str) -> str:
    return f"<p class='err'>{html.escape(message)}</p>" if message else ""


def _field(label: str, name: str, kind: str = "text", value: str = "",
           extra: str = "") -> str:
    return (f"<label for='{name}'>{html.escape(label)}</label>"
            f"<input id='{name}' name='{name}' type='{kind}' "
            f"value='{html.escape(value, quote=True)}' required {extra}>")


def _nav(tx: str, *links: tuple[str, str]) -> str:
    q = html.escape(tx, quote=True)
    return "<nav>" + "".join(f"<a href='/{path}?tx={q}'>{html.escape(text)}</a>"
                             for path, text in links) + "</nav>"


def _form(tx: str, action: str, fields: str, button: str) -> str:
    return (f"<form method='post' action='/{action}'>"
            f"<input type='hidden' name='tx' value='{html.escape(tx, quote=True)}'>"
            f"{fields}<button>{html.escape(button)}</button></form>")


def _signin_page(tx: str, email: str = "", message: str = "") -> HTMLResponse:
    return _page("Sign in to Jyotisha", _error(message) + _form(
        tx, "signin",
        _field("Email", "email", "email", email, "autofocus")
        + _field("Password", "password", "password"), "Sign in")
        + _nav(tx, ("join", "I have an invite code"),
               ("recover", "Forgot password")))


def _join_page(tx: str, email: str = "", message: str = "") -> HTMLResponse:
    return _page("Use your invite", _error(message) + _form(
        tx, "join",
        _field("Email", "email", "email", email, "autofocus")
        + _field("Invite code", "invite", extra="autocomplete='off'")
        + _field(f"Choose a password (at least {MIN_PASSWORD} characters)",
                 "password", "password", extra="autocomplete='new-password'")
        + _field("The same password again", "again", "password",
                 extra="autocomplete='new-password'"), "Create my account")
        + _nav(tx, ("signin", "I already have an account")))


def _recover_page(tx: str, email: str = "", message: str = "") -> HTMLResponse:
    return _page("Set a new password", _error(message)
                 + "<p class='small'>You need the recovery code you were shown "
                   "when you created your account.</p>" + _form(
        tx, "recover",
        _field("Email", "email", "email", email, "autofocus")
        + _field("Recovery code", "recovery", extra="autocomplete='off'")
        + _field(f"New password (at least {MIN_PASSWORD} characters)",
                 "password", "password", extra="autocomplete='new-password'")
        + _field("The same password again", "again", "password",
                 extra="autocomplete='new-password'"), "Set password")
        + _nav(tx, ("signin", "Back to sign in")))


def _recovery_code_page(ticket: str, recovery: str) -> HTMLResponse:
    return _page("Write this down now", (
        "<p>This is your recovery code. It is shown <strong>once</strong> and "
        "is stored nowhere.</p>"
        f"<p class='code'>{html.escape(recovery)}</p>"
        "<p>Your journal and life events are locked with your password, so "
        "nobody -- including the person who runs this service -- can reset it "
        "for you. If you forget your password, this code is the only way "
        "back to them.</p>"
        "<form method='post' action='/continue'>"
        f"<input type='hidden' name='ticket' value='{html.escape(ticket, quote=True)}'>"
        "<button>I have saved it. Continue</button></form>"))


def _add_pages(server: MCPServer, provider: Provider) -> None:
    accounts = provider.accounts

    def hold(tx: str, account_id: int, key: bytes) -> str:
        ticket = vault.new_token()
        provider.ready[ticket] = (tx, account_id, key,
                                  time.time() + SIGNIN_PAGE_SECONDS)
        return ticket

    def back_to_claude(tx: str, account_id: int, key: bytes) -> Response:
        target = provider.complete(tx, account_id, key)
        if target is None:
            return _expired()
        return RedirectResponse(target, status_code=302,
                                headers={"Cache-Control": "no-store"})

    @server.custom_route("/signin", methods=["GET", "POST"])
    async def signin(request: Request) -> Response:
        if request.method == "GET":
            tx = request.query_params.get("tx", "")
            return _signin_page(tx) if provider.open_sign_in(tx) else _expired()
        form = await request.form()
        tx, email = str(form.get("tx", "")), str(form.get("email", ""))
        if not provider.open_sign_in(tx):
            return _expired()
        if provider.locked_out(email):
            return _signin_page(tx, email, "Too many wrong attempts. Wait a "
                                           "quarter of an hour and try again.")
        found = accounts.sign_in(email, str(form.get("password", "")))
        if found is None:
            provider.failed(email)
            return _signin_page(tx, email,
                                "That email and password do not match.")
        provider.succeeded(email)
        return back_to_claude(tx, *found)

    @server.custom_route("/join", methods=["GET", "POST"])
    async def join(request: Request) -> Response:
        if request.method == "GET":
            tx = request.query_params.get("tx", "")
            return _join_page(tx) if provider.open_sign_in(tx) else _expired()
        form = await request.form()
        tx, email = str(form.get("tx", "")), str(form.get("email", ""))
        if not provider.open_sign_in(tx):
            return _expired()
        if provider.locked_out(email):
            return _join_page(tx, email, "Too many wrong attempts. Wait a "
                                         "quarter of an hour and try again.")
        if form.get("password") != form.get("again"):
            return _join_page(tx, email, "The two passwords are not the same.")
        try:
            account_id, key, recovery = accounts.register(
                email, str(form.get("invite", "")), str(form.get("password", "")))
        except AccountError as exc:
            provider.failed(email)
            return _join_page(tx, email, str(exc))
        provider.succeeded(email)
        return _recovery_code_page(hold(tx, account_id, key), recovery)

    @server.custom_route("/recover", methods=["GET", "POST"])
    async def recover(request: Request) -> Response:
        if request.method == "GET":
            tx = request.query_params.get("tx", "")
            return _recover_page(tx) if provider.open_sign_in(tx) else _expired()
        form = await request.form()
        tx, email = str(form.get("tx", "")), str(form.get("email", ""))
        if not provider.open_sign_in(tx):
            return _expired()
        if provider.locked_out(email):
            return _recover_page(tx, email, "Too many wrong attempts. Wait a "
                                            "quarter of an hour and try again.")
        if form.get("password") != form.get("again"):
            return _recover_page(tx, email, "The two passwords are not the same.")
        try:
            found = accounts.recover(email, str(form.get("recovery", "")),
                                     str(form.get("password", "")))
        except AccountError as exc:
            return _recover_page(tx, email, str(exc))
        if found is None:
            provider.failed(email)
            return _recover_page(tx, email, "That email and recovery code do "
                                            "not match.")
        provider.succeeded(email)
        account_id, key, recovery = found
        mcp_server.forget_account(account_id)
        return _recovery_code_page(hold(tx, account_id, key), recovery)

    @server.custom_route("/continue", methods=["POST"])
    async def carry_on(request: Request) -> Response:
        form = await request.form()
        entry = provider.ready.pop(str(form.get("ticket", "")), None)
        if entry is None or entry[3] < time.time():
            return _expired()
        return back_to_claude(*entry[:3])


# ------------------------------------------------------------------ server


class Sessions:
    """Hands each call the store of the account that signed in.

    This is what the tools get in place of the local store. There is no
    fallback: no token, an unknown one, an expired one, or one whose account
    has been disabled or deleted all end in the same refusal.
    """

    def __init__(self, accounts: Accounts):
        self.accounts = accounts
        self._stores: dict[int, tuple[Store, bytes, float]] = {}
        self._lock = threading.Lock()

    def __call__(self) -> Store:
        token = get_access_token()
        g = self.accounts.grant("access", token.token) if token else None
        if g is None:
            raise ToolError("Not signed in. Reconnect the Jyotisha connector "
                            "and sign in again.")
        now = time.time()
        with self._lock:
            for account_id in [a for a, entry in self._stores.items()
                               if now - entry[2] > IDLE_SECONDS]:
                self._drop(account_id)
            entry = self._stores.get(g["account_id"])
            # An account that was reset has a new key; never reuse the old.
            if entry is not None and entry[1] != g["key"]:
                self._drop(g["account_id"])
                entry = None
            store = entry[0] if entry else Store(
                self.accounts.path, account_id=g["account_id"], key=g["key"])
            self._stores[g["account_id"]] = (store, g["key"], now)
        return store

    def _drop(self, account_id: int) -> None:
        store = self._stores.pop(account_id)[0]
        mcp_server.forget_account(account_id)
        store.close()


def build(accounts: Accounts, public_url: str) -> MCPServer:
    """The shared server, ready to run. Also switches the tools over to
    per-account stores -- after this, this process has no local store."""
    public_url = public_url.rstrip("/")
    provider = Provider(accounts, public_url)
    server = MCPServer(
        name="jyotisha", title="Jyotisha advisor", instructions=INSTRUCTIONS,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=public_url,
            resource_server_url=f"{public_url}/mcp",
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True)))

    for fn in mcp_server.TOOLS:
        server.tool()(fn)

    @server.tool()
    def guidance(topic: str) -> str:
        """How to do the three things this advisor is for. Read the relevant
        one before doing it for the first time in a conversation.

        topic is "onboard" (set up a profile: birth data, how well the time is
        known, life events), "ask" (advise on a decision) or "journal" (review
        past advice, record choices and outcomes).
        """
        try:
            return guides.text(topic)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    @server.prompt(name="onboard", title="Set up a profile",
                   description="Add yourself or someone close to you: birth "
                               "data, how well the time is known, life events.")
    def onboard() -> str:
        return guides.text("onboard")

    @server.prompt(name="ask", title="Ask about a decision",
                   description="Get a timed answer on a choice you are weighing.")
    def ask(question: str = "") -> str:
        return guides.text("ask", question)

    @server.prompt(name="journal", title="Review the journal",
                   description="Look back over past advice and record how "
                               "things turned out.")
    def journal() -> str:
        return guides.text("journal")

    _add_pages(server, provider)
    mcp_server._session_store = Sessions(accounts)
    return server


def main() -> None:
    import anyio

    public_url = os.environ.get("JYOTISHA_PUBLIC_URL", "http://localhost:8765")
    host = os.environ.get("JYOTISHA_HOST", "127.0.0.1")
    port = int(os.environ.get("JYOTISHA_PORT", "8765"))
    try:
        accounts = Accounts(SHARED_DB)
    except PermissionError as exc:
        print(exc)
        sys.exit(1)
    server = build(accounts, public_url)

    # Off this machine, only requests addressed to the public name are served.
    security = None
    public = urlparse(public_url)
    if public.hostname not in ("localhost", "127.0.0.1", "::1"):
        security = TransportSecuritySettings(
            allowed_hosts=[public.netloc], allowed_origins=[public_url])

    print(f"Shared Jyotisha server. Database: {accounts.path}")
    print(f"Connector address: {public_url}/mcp")
    print("Close this window to stop it.")
    anyio.run(functools.partial(
        server.run_streamable_http_async, host=host, port=port,
        stateless_http=True, json_response=True, transport_security=security))


if __name__ == "__main__":
    main()
