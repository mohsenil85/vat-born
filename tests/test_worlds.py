"""Which world file `vat-born` opens, what it refuses, and what the file guarantees."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests.harness import play, run


def test_seed_opens_that_world_in_the_data_dir_and_remembers_it(tmp_path: Path) -> None:
    made = run(["--seed", "5"], ["wait 1 hour"], data_home=tmp_path)
    assert made.code == 0, made.err
    worlds = tmp_path / "vat-born"
    assert (worlds / "5.db").is_file()
    assert (worlds / "last-world").read_text() == "5.db\n"
    resumed = run([], ["status"], data_home=tmp_path)
    assert resumed.code == 0, resumed.err
    assert "A new world" not in resumed.out
    assert "Seed 5, clone 1." in resumed.out


def test_no_flags_makes_a_world_then_resumes_it(tmp_path: Path) -> None:
    made = run([], [], data_home=tmp_path)
    assert made.code == 0, made.err
    assert "A new world" in made.out
    worlds = tmp_path / "vat-born"
    assert (worlds / (worlds / "last-world").read_text().strip()).is_file()
    resumed = run([], [], data_home=tmp_path)
    assert resumed.code == 0, resumed.err
    assert "A new world" not in resumed.out


def test_world_flag_leaves_the_data_dir_alone(tmp_path: Path) -> None:
    made = run(["--world", str(tmp_path / "world.db")], [], data_home=tmp_path / "data")
    assert made.code == 0, made.err
    assert (tmp_path / "world.db").is_file()
    assert not (tmp_path / "data").exists()


def test_refuses_a_seed_that_is_not_the_worlds(tmp_path: Path) -> None:
    world = str(tmp_path / "world.db")
    assert run(["--world", world, "--seed", "1"], [], data_home=tmp_path).code == 0
    refused = run(["--world", world, "--seed", "2"], [], data_home=tmp_path)
    assert refused.code == 2
    assert "seed 1, not 2" in refused.err


def test_refuses_a_file_that_is_not_a_world(tmp_path: Path) -> None:
    junk = tmp_path / "junk.db"
    junk.write_text("not a database\n")
    refused = run(["--world", str(junk)], [], data_home=tmp_path)
    assert refused.code == 2
    assert "is not a Vat-Born world" in refused.err


def test_the_log_is_append_only(tmp_path: Path) -> None:
    world = tmp_path / "world.db"
    play(world, 1, ["wait"])
    with closing(sqlite3.connect(world)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE log SET kind = 'edited'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM log")
