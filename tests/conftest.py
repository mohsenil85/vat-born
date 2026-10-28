import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--regen",
        action="store_true",
        help="rewrite each scenario transcript from what the game does now; review the diff before committing",
    )
