"""Write the OpenAPI document of the explorer API, which the web app generates its types from.

The output is ``json.dumps(app.openapi(), indent=2, sort_keys=True)`` plus a newline, so it is
deterministic and ``tests/api/test_openapi.py`` can compare it with the committed file. The
document does not depend on the database or on the environment.

Usage: ``export_openapi.py [--out apps/web/openapi.json]``. Prints nothing; exit code 0.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

from oap.api.main import create_app, openapi_text
from oap.api.settings import ApiSettings

DEFAULT_OUT = Path("apps/web/openapi.json")


def main(argv: Sequence[str] | None = None) -> int:
    """Write the OpenAPI document.

    Args:
        argv: Command-line arguments; ``sys.argv[1:]`` when None.

    Returns:
        The process exit code, 0 on success.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="file to write")
    args = parser.parse_args(argv)
    text = openapi_text(create_app(ApiSettings()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
