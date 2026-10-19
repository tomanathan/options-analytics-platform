from pathlib import Path

import pytest

from scripts import image_requirements

REPO = Path(__file__).resolve().parents[2]


def test_direct_dependencies_of_the_repo() -> None:
    # numpy is a direct dependency of the engine; the set may grow, these must stay.
    expected = {
        "great-expectations",
        "httpx",
        "pandas",
        "pandas-market-calendars",
        "pandera",
        "pyarrow",
        "pyiceberg",
        "tenacity",
    }
    assert expected <= image_requirements.direct_dependencies(REPO / "pyproject.toml")


def test_parse_pins_skips_annotations_and_keeps_markers() -> None:
    lines = [
        "altair==6.3.0",
        "    # via great-expectations",
        "# a comment",
        "",
        "colorama==0.4.6 ; sys_platform == 'win32'",
        "    # via click",
        "Typing_Extensions==4.15.0",
    ]

    assert image_requirements.parse_pins(lines) == [
        ("altair", "altair==6.3.0"),
        ("colorama", "colorama==0.4.6 ; sys_platform == 'win32'"),
        ("typing-extensions", "Typing_Extensions==4.15.0"),
    ]


def test_select_keeps_direct_and_unshipped_and_drops_shipped() -> None:
    pins = image_requirements.parse_pins(
        ["pandas==2.3.3", "numpy==2.5.3", "pyiceberg-core==0.9.0", "boto3==1.43.108"]
    )
    installed = {"pandas": "2.1.4", "numpy": "1.26.4", "boto3": "1.42.61"}

    assert image_requirements.select(pins, {"pandas"}, installed) == [
        "pandas==2.3.3",
        "pyiceberg-core==0.9.0",
    ]
    assert image_requirements.select(pins, {"pandas"}, installed, {"boto3"}) == [
        "pandas==2.3.3",
        "pyiceberg-core==0.9.0",
        "boto3==1.43.108",
    ]


def test_names_are_normalised() -> None:
    pins = image_requirements.parse_pins(["Typing_Extensions==4.15.0", "ruamel.yaml==0.19.0"])
    installed = {"typing-extensions": "4.12.2", "ruamel-yaml": "0.18.0"}

    assert image_requirements.select(pins, set(), installed) == []
    assert image_requirements.select(pins, {"Typing.Extensions"}, installed) == [
        "Typing_Extensions==4.15.0"
    ]
    assert image_requirements.select(pins, set(), installed, {"RUAMEL_yaml"}) == [
        "ruamel.yaml==0.19.0"
    ]


@pytest.mark.parametrize(
    "pin", ["apache-airflow==2.11.2", "apache-airflow-providers-http==5.0", "dbt-core==1.10.0"]
)
def test_refuses_airflow_and_dbt_pins(pin: str) -> None:
    with pytest.raises(ValueError, match="must not be installed from the lock"):
        image_requirements.select(image_requirements.parse_pins([pin]), set(), {})


def test_committed_requirements_are_runtime_only() -> None:
    text = (REPO / "docker" / "requirements.txt").read_text()
    names = [name for name, _ in image_requirements.parse_pins(text.splitlines())]

    assert not [name for name in names if name.startswith(("apache-airflow", "dbt-"))]
    assert "pyarrow==25.0.1" in text
    assert "pandas==2.3.3" in text
