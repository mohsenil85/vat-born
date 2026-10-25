from vat_born.cli import main


def test_scaffold_message(capsys):
    main()
    assert "not implemented yet" in capsys.readouterr().out
