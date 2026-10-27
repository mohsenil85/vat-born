import pytest

from vat_born.cli import main


def test_scaffold_message(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    assert "not implemented yet" in capsys.readouterr().out
