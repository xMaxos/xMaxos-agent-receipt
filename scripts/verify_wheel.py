"""Install the built wheel into a fresh temporary target and test that artifact."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    wheels = list((ROOT / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Expected one built wheel in dist/")
    wheel = wheels[0]
    with tempfile.TemporaryDirectory(prefix="agent-receipt-wheel-") as temporary:
        target = Path(temporary) / "installed"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                        "--disable-pip-version-check", "--target", str(target), str(wheel)], check=True)
        env = dict(os.environ, PYTHONPATH=str(target), AGENT_RECEIPT_TEST_INSTALLED="1")
        probe = "import agent_receipt,sys; from pathlib import Path; assert Path(agent_receipt.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())"
        subprocess.run([sys.executable, "-c", probe, str(target)], env=env, cwd=temporary, check=True)
        tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                               env=env, cwd=ROOT, capture_output=True, text=True, timeout=90)
        output = tests.stdout + tests.stderr
        (ROOT / "evidence" / "wheel-tests.txt").write_text(output, encoding="utf-8")
        if tests.returncode:
            print(output)
            raise SystemExit(tests.returncode)
        count = int(re.search(r"Ran (\d+) tests", output).group(1))
        record = {"artifact": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                  "bytes": wheel.stat().st_size, "installed_artifact_import_verified": True,
                  "tests_passed": count, "network_used": False}
        (ROOT / "evidence" / "wheel-check.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
