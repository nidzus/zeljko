"""Manage who can use the shared server.

Double-click "Manage accounts" for the menu, or give a command:

    python jyotisha.py accounts invite friend@example.com "Name"
    python jyotisha.py accounts list
    python jyotisha.py accounts disable friend@example.com
    python jyotisha.py accounts enable  friend@example.com
    python jyotisha.py accounts reset   friend@example.com
    python jyotisha.py accounts delete  friend@example.com

This works on the shared database only (shared.db in the data folder). It
never opens the family one. It can see who has an account and how much they have stored, and
it can remove things; it has no key, so it cannot read anyone's journal.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.accounts import AccountError, Accounts, INVITE_DAYS  # noqa: E402


def invite(acc: Accounts, email: str, name: str = "") -> None:
    code = acc.invite(email, name)
    print(f"\nInvited {email.strip().lower()}.")
    print(f"\n    Invite code:  {code}\n")
    print(f"Send them the code and the connector address. The code works once "
          f"and lasts {INVITE_DAYS} days.")
    print("It is not stored: if it is lost, invite them again for a new one.")


def listing(acc: Accounts) -> None:
    rows = acc.listing()
    if not rows:
        print("\nNo accounts yet.")
        return
    print(f"\n{'email':<34} {'status':<9} {'profiles':>8} {'decisions':>9}  last used")
    for r in rows:
        last = (r["last_seen_at"] or "never")[:10]
        print(f"{r['email']:<34} {r['status']:<9} {r['profiles']:>8} "
              f"{r['decisions']:>9}  {last}")


def disable(acc: Accounts, email: str) -> None:
    acc.disable(email)
    print(f"\n{email} is disabled and signed out. Their data is kept; "
          f"'enable' lets them back in.")


def enable(acc: Accounts, email: str) -> None:
    acc.enable(email)
    print(f"\n{email} can sign in again.")


def reset(acc: Accounts, email: str, sure: bool = False) -> None:
    print(f"\nThis is for when {email} has lost BOTH their password and their "
          f"recovery code.")
    print("Their journal and life events will be deleted -- nobody can unlock "
          "them. Profiles and charts are kept.")
    if not sure and input("Type RESET to go ahead: ").strip() != "RESET":
        print("Nothing was changed.")
        return
    code = acc.reset(email)
    print(f"\nDone. New invite code:  {code}")


def delete(acc: Accounts, email: str, sure: bool = False) -> None:
    print(f"\nThis deletes the account {email} and everything in it. "
          f"It cannot be undone.")
    if not sure and input("Type the email again to confirm: "
                          ).strip().lower() != email.strip().lower():
        print("Nothing was deleted.")
        return
    counts = acc.delete(email)
    print(f"\nDeleted, with {counts['profiles']} profile(s) and "
          f"{counts['decisions']} decision(s).")


COMMANDS = {"invite": invite, "list": listing, "disable": disable,
            "enable": enable, "reset": reset, "delete": delete}

MENU = """
  1  Invite a person
  2  List accounts
  3  Disable an account (keeps the data)
  4  Enable a disabled account
  5  Reset an account whose password and recovery code are both lost
  6  Delete an account and all its data
  0  Close
"""


def menu(acc: Accounts) -> None:
    print(f"Shared database: {acc.path}")
    while True:
        print(MENU)
        choice = input("Choose: ").strip()
        try:
            if choice == "0" or choice == "":
                return
            if choice == "2":
                listing(acc)
                continue
            if choice not in "13456" or len(choice) != 1:
                print("Type one of the numbers.")
                continue
            email = input("Email: ").strip()
            if not email:
                continue
            if choice == "1":
                invite(acc, email, input("Name (optional): ").strip())
            else:
                {"3": disable, "4": enable, "5": reset, "6": delete}[choice](
                    acc, email)
        except AccountError as exc:
            print(f"\n{exc}")
        except EOFError:
            return


def main(argv: list[str]) -> int:
    try:
        acc = Accounts()
    except PermissionError as exc:
        print(exc)
        return 1
    if not argv:
        menu(acc)
        return 0
    sure = "--yes" in argv
    argv = [a for a in argv if a != "--yes"]
    command = COMMANDS.get(argv[0])
    if command is None:
        print(__doc__)
        return 1
    try:
        if command in (reset, delete):
            command(acc, *argv[1:2], sure=sure)
        else:
            command(acc, *argv[1:])
    except AccountError as exc:
        print(exc)
        return 1
    except TypeError:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
