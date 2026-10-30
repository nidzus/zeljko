"""Run every verification. One command to confirm the foundation is sound."""
import os, subprocess, sys, pathlib

os.chdir(pathlib.Path(__file__).resolve().parent)
PY = sys.executable
suites = ["verify_ephemeris.py", "verify_timeplace.py",
          "verify_dasha.py", "verify_confidence.py",
          "verify_transits.py", "verify_store.py",
          "verify_coords.py", "verify_api.py",
          "verify_advisor.py",
          "verify_panchanga.py", "verify_strength.py",
          "verify_yogas.py", "verify_rectify.py",
          "verify_chartsvg.py", "verify_shani.py", "verify_personalday.py", "verify_divisional.py",
          "verify_shadbala.py", "verify_contacts.py", "verify_karaka.py",
          "verify_mcp.py", "verify_mcp_stdio.py",
          "verify_accounts.py", "verify_remote.py"]
failed = []
for s in suites:
    r = subprocess.run([PY, s], capture_output=True, text=True)
    tail = [l for l in r.stdout.splitlines() if "checks passed" in l]
    print(f"{s:<24} {tail[-1] if tail else 'NO RESULT'}")
    if r.returncode != 0:
        failed.append(s)

# Last, and as binding as any suite: nothing personal in the tracked files.
r = subprocess.run([PY, "tools/check_clean.py", "--all"], capture_output=True, text=True)
print(f"{'privacy check':<24} {(r.stdout.strip().splitlines() or ['NO RESULT'])[0]}")
if r.returncode != 0:
    print(r.stdout)
    failed.append("privacy check")
print()
print("ALL SUITES PASS" if not failed else f"FAILED: {', '.join(failed)}")
sys.exit(1 if failed else 0)
