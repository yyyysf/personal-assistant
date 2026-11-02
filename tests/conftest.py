"""测试环境：独立临时 SQLite，关闭调度与演示数据。"""

import os
import tempfile
from pathlib import Path

import pytest

TEST_DIR = Path(tempfile.mkdtemp(prefix="assistant-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_DIR / 'test.db').as_posix()}"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import app  # noqa: E402
from src.core.db import Base, engine  # noqa: E402


@pytest.fixture(scope="session")
def client():
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_database(client):
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    yield
