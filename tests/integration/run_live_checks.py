"""
Run every live Blender check in isolation, on a clean reference model, and report each one.

    python3 tests/integration/run_live_checks.py 4.5          # one Blender image
    python3 tests/integration/run_live_checks.py 4.5 5.2      # several

Before each check the reference model is reset and verified, so no check inherits another's state. Each
check runs in its own Blender process. A check passes only when its exit code is 0 AND it printed its
"OK" verdict line: a crash with exit 0, or a run that printed a FAIL, both count as failures.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import reference_reset  # noqa: E402

REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
CHECKS = [
    "live_import_check", "live_import_attribution_check", "live_delete_check", "live_sync_push_check",
    "live_sync_material_check", "live_scene_check", "live_sync_delete_push_check", "live_timer_delete_check",
    "live_timer_add_check", "live_timer_modify_check", "live_timer_overlap_check",
    "live_timer_imported_edit_check", "live_timer_reshape_check", "live_timer_conflict_check",
    "live_complex_import_check", "live_varied_import_check",
    "live_timer_hole_check",
]
OK_LINE = re.compile(r"^LIVE-[A-Z-]+ OK")


def run(version, check):
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
