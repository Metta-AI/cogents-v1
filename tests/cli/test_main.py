import os
import sys

from cli.__main__ import _preprocess_argv


def test_preprocess_argv_sets_local_checkout_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr("cli.local_dev._REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["cogent", "local", "status"])
    monkeypatch.delenv("COGENT_ID", raising=False)
    monkeypatch.delenv("USE_LOCAL_DB", raising=False)
    monkeypatch.delenv("COGENT_LOCAL_DATA", raising=False)

    try:
        _preprocess_argv()

        assert sys.argv == ["cogent", "status"]
        assert os.environ["COGENT_ID"] == "local"
        assert os.environ["USE_LOCAL_DB"] == "1"
        assert os.environ["COGENT_LOCAL_DATA"] == str(tmp_path / ".local" / "cogos")
    finally:
        os.environ.pop("COGENT_ID", None)
        os.environ.pop("USE_LOCAL_DB", None)
        os.environ.pop("COGENT_LOCAL_DATA", None)
