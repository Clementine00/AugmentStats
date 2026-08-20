"""Shared fixtures. Payload builders live in tests/factories.py."""

import pytest

from augmentstats.db import get_connection, init_db


@pytest.fixture
def db_path(tmp_path):
    """A freshly initialised database, isolated per test."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def conn(db_path):
    connection = get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def raw_dir(tmp_path):
    folder = tmp_path / "raw"
    folder.mkdir()
    return folder
