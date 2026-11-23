import pytest

from mab.cli import main


def test_unknown_topic_is_a_usage_error():
    with pytest.raises(SystemExit):
        main(["report", "nope"])
