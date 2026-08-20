"""patch_from_version derives the 'major.minor' label games are grouped by."""

import pytest

from augmentstats.db import patch_from_version


@pytest.mark.parametrize(
    ("game_version", "expected"),
    [
        ("16.15.801.3452", "16.15"),
        ("16.16.900.1111", "16.16"),
        ("9.4.1.2", "9.4"),
        ("16.15", "16.15"),
    ],
)
def test_derives_major_minor(game_version, expected):
    assert patch_from_version(game_version) == expected


@pytest.mark.parametrize("game_version", [None, "", "not-a-version", "16", "x.y.z.w", "16.x"])
def test_returns_none_when_unparseable(game_version):
    assert patch_from_version(game_version) is None
