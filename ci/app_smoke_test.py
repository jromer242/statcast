"""Smoke test for the Streamlit app: run every page headlessly and fail on any exception.

Uses Streamlit's own test runner, against the committed extracts in app/data/. Run from
the project root:  python ci/app_smoke_test.py
"""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))  # pages import data_access, as they do under streamlit run


def main() -> int:
    failures = 0
    for page in sorted((APP_DIR / "views").glob("*.py")):
        at = AppTest.from_file(str(page), default_timeout=120).run()
        errors = [e.value for e in at.exception]
        print(f"{page.name}: {'ok' if not errors else errors}")
        failures += bool(errors)

    # Change every selectbox on the spray page once: a different season and park can hit
    # code paths the defaults don't (no wall outline, a hitter with few balls).
    at = AppTest.from_file(str(APP_DIR / "views" / "spray.py"), default_timeout=120).run()
    for i in range(len(at.selectbox)):
        # Re-read the widget each time: changing the season rebuilds the hitter list.
        box = at.selectbox[i]
        box.select_index(len(box.options) - 1).run()
        if at.exception:
            print(f"spray.py, selectbox {i}: {[e.value for e in at.exception]}")
            failures += 1
            break
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
