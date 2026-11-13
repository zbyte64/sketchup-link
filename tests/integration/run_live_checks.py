"""
Run every live Blender check in isolation, on a clean reference model, and report each one.

    python3 tests/integration/run_live_checks.py 4.5          # one Blender image
    python3 tests/integration/run_live_checks.py 4.5 5.2      # several

Before each check the reference model is reset and verified, so no check inherits another's state. Each
check runs in its own Blender process. A check passes only when its exit code is 0 AND it printed its
"OK" verdict line: a crash with exit 0, or a run that printed a FAIL, both count as failures.

Every tests/integration/live_*_check.py and gui_*_check.py is run. live_* run Blender in the background (or on
the host, if the check says it "Runs on the host"); gui_* run Blender's interface on a virtual display in the
debug image (sketchup-link-blender-debug:<version>), so screen-capture checks need no long-lived container.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reference_reset  # noqa: E402

REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
# The established order runs first; any other live_*_check.py found on disk is appended, so a new check
# cannot be left out of the runner by forgetting to list it here (the concave check once was).
_ORDER = [
    "live_import_check", "live_import_attribution_check", "live_delete_check", "live_sync_push_check",
    "live_sync_material_check", "live_scene_check", "live_sync_delete_push_check", "live_timer_delete_check",
    "live_timer_add_check", "live_timer_modify_check", "live_timer_overlap_check",
    "live_timer_imported_edit_check", "live_timer_reshape_check", "live_timer_conflict_check",
    "live_complex_import_check", "live_varied_import_check",
    "live_timer_hole_check",
]
_ON_DISK = sorted(f[:-3] for f in os.listdir(HERE) if re.fullmatch(r"(live|gui)_\w+_check\.py", f))
CHECKS = [c for c in _ORDER if c in _ON_DISK] + [c for c in _ON_DISK if c not in _ORDER]
_MISSING = [c for c in _ORDER if c not in _ON_DISK]
if _MISSING:
    raise SystemExit(f"run_live_checks: listed checks missing on disk: {_MISSING}")
OK_LINE = re.compile(r"^(LIVE|GUI)-[A-Z-]+ OK")
# gui_* checks run Blender with its interface on the Xvfb display that the debug image's entrypoint starts, in a
# throwaway container. They use the default bridge network, not host networking, because that entrypoint also
# starts sshd (22) and x11vnc (5900), which must not bind on the host; SketchUp is reached at the bridge gateway.
GUI_HOST = os.environ.get("SKETCHUP_LINK_GUI_HOST", "172.17.0.1")


def runs_on_host(check):
    """A check whose docstring says it "Runs on the host" talks to SketchUp only and needs no Blender."""
    with open(os.path.join(HERE, f"{check}.py"), encoding="utf-8") as f:
        return "Runs on the host" in f.read(2000)


def run(version, check):
    if runs_on_host(check):
        cmd = [sys.executable, os.path.join(HERE, f"{check}.py")]
    elif check.startswith("gui_"):
        cmd = ["docker", "run", "--rm", "-e", "DISPLAY=:99", "-e", f"SKETCHUP_LINK_HOST={GUI_HOST}",
               "-v", f"{REPO}:/plugin", "-w", "/plugin", f"sketchup-link-blender-debug:{version}",
               "blender", "--factory-startup", "--python", f"tests/integration/{check}.py"]
    else:
        cmd = ["docker", "run", "--rm", "--network", "host", "-v", f"{REPO}:/plugin", "-w", "/plugin",
               f"sketchup-link-blender:{version}", "blender", "--background", "--factory-startup",
               "--python", f"tests/integration/{check}.py"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    verdict = next((ln for ln in proc.stdout.splitlines() if OK_LINE.match(ln)), None)
    passed = proc.returncode == 0 and verdict is not None
    return passed, proc.returncode, verdict or next((ln for ln in proc.stdout.splitlines()
                                                     if "FAIL" in ln), "no verdict line")


def main(versions):
    if not versions:
        print("usage: run_live_checks.py <blender-version> [...]")
        return 2
    failures = []
    for version in versions:
        for check in CHECKS:
            reference_reset.reset()
            reference_reset.verify()
            passed, code, detail = run(version, check)
            tag = "PASS" if passed else "FAIL"
            print(f"{tag} {version} {check} exit={code} {detail[:90]}")
            if not passed:
                failures.append(f"{version} {check}")
    reference_reset.reset()
    reference_reset.verify()
    print(f"\n{len(CHECKS) * len(versions) - len(failures)}/{len(CHECKS) * len(versions)} live checks passed")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
