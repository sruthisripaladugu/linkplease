import os
import pytest
import pytest_asyncio
import tempfile
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import init_db
from app.config import settings


@pytest_asyncio.fixture
async def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    settings.DATABASE_PATH = path
    await init_db(path)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


@pytest_asyncio.fixture
async def client(temp_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
