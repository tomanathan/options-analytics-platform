"""Choose which ``uv.lock`` pins the Airflow image installs on top of the base image.

The official Airflow image already ships Airflow's own dependencies at the versions of its
constraints file, and those win: replacing numpy or cryptography under Airflow's providers
breaks them. What the image takes from the lock is oap's direct dependencies (so pandas,
pyarrow and pyiceberg are the tested versions) and every package the base image does not
ship. Both sources are fixed, so the build is reproducible.

This runs in the base image before oap is installed, so it uses the standard library only.
Usage: ``image_requirements.py requirements.txt pyproject.toml [--prefer-lock NAME ...]``.
The selected requirements go to stdout and the packages that stay at the base image's version
go to stderr, which ends up in the build log.
"""

import argparse
import importlib.metadata
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_NEVER_FROM_LOCK = ("apache-airflow", "dbt-")


def canonical(name: str) -> str:
    """Normalise a distribution name as PEP 503 does: lower case, runs of ``-_.`` to ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_dependencies(pyproject: Path) -> set[str]:
    """Return the canonical names in ``[project].dependencies``, without extras or specifiers."""
    data = tomllib.loads(pyproject.read_text())
    names: set[str] = set()
    for requirement in data["project"]["dependencies"]:
        match = _NAME.match(requirement.strip())
        if match is None:
            raise ValueError(f"cannot read a package name from {requirement!r}")
        names.add(canonical(match.group()))
    return names


def parse_pins(lines: Iterable[str]) -> list[tuple[str, str]]:
    """Read ``name==version`` pins from a ``uv export`` file.

    Indented lines (the ``# via`` annotations) and comments are skipped. Environment markers
    such as ``colorama==0.4.6 ; sys_platform == 'win32'`` stay on the line.

    Returns:
        ``(canonical name, pin line)`` pairs in file order.
    """
    pins: list[tuple[str, str]] = []
    for raw in lines:
        if not raw.strip() or raw[0].isspace() or raw.startswith("#") or "==" not in raw:
            continue
        line = raw.strip()
        pins.append((canonical(line.split("==", 1)[0]), line))
    return pins


def _version(pin: str) -> str:
    return pin.split("==", 1)[1].split(";")[0].strip()


def select(
    pins: Iterable[tuple[str, str]],
    direct: Iterable[str],
    installed: Mapping[str, str],
    prefer_lock: Iterable[str] = (),
) -> list[str]:
    """Pick the pins to install: direct dependencies, preferred ones and packages not yet installed.

    Args:
        pins: Output of ``parse_pins``.
        direct: Canonical names of oap's direct dependencies.
        installed: Canonical name to version of what the base image already has.
        prefer_lock: Further names to take from the lock even though the base image has them.

    Returns:
        Pin lines to install, in the order given.

    Raises:
        ValueError: If a pin is Airflow or dbt, which the image must never take from the lock.
    """
    wanted = {canonical(name) for name in direct} | {canonical(name) for name in prefer_lock}
    base = {canonical(name): version for name, version in installed.items()}
    selected: list[str] = []
    for name, line in pins:
        if name.startswith(_NEVER_FROM_LOCK):
            raise ValueError(f"{name} must not be installed from the lock: the image is Airflow")
        if name in wanted or name not in base:
            selected.append(line)
    return selected


def installed_distributions() -> dict[str, str]:
    """Return the canonical name and version of every distribution in this environment."""
    return {
        canonical(dist.metadata["Name"]): dist.version
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"]
    }


def main(argv: list[str] | None = None) -> int:
    """Print the requirements to install on stdout and the kept base versions on stderr."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("requirements", type=Path, help="uv export output")
    parser.add_argument("pyproject", type=Path, help="pyproject.toml with [project].dependencies")
    parser.add_argument(
        "--prefer-lock", action="append", default=[], metavar="NAME", help="take NAME from the lock"
    )
    args = parser.parse_args(argv)

    pins = parse_pins(args.requirements.read_text().splitlines())
    installed = installed_distributions()
    selected = select(pins, direct_dependencies(args.pyproject), installed, args.prefer_lock)
    for line in selected:
        print(line)
    chosen = set(selected)
    for name, line in pins:
        if line not in chosen:
            print(f"kept base {name}=={installed[name]} (lock {_version(line)})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
