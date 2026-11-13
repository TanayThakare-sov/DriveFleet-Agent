"""Build a throwaway DB + model once per test session and point the app at them."""
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def fleet_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fleet")
    os.environ["DRIVEFLEET_DB"] = str(tmp / "fleet.db")
    os.environ["DRIVEFLEET_MODEL_DIR"] = str(tmp / "models")

    from drivefleet.config import get_settings
    from drivefleet.seed import build_database
    from drivefleet.train import train

    s = get_settings()
    build_database(s.db_path)
    train(s.db_path, s.model_dir)
    yield s
