"""Connection configuration loaded from environment variables."""
import os
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()


def pg_dsn():
    override = os.getenv("PG_DSN")
    if override:
        return override
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("Missing POSTGRES_PASSWORD: copy .env.example to .env")
    user = quote(os.getenv("POSTGRES_USER", "lab2"), safe="")
    name = quote(os.getenv("POSTGRES_DB", "hospital_lab2"), safe="")
    host = os.getenv("PG_HOST", "127.0.0.1")
    port = int(os.getenv("PG_PORT", "5436"))
    return f"postgresql://{user}:{quote(password, safe='')}@{host}:{port}/{name}"


def mongo_uri():
    return os.getenv("MONGO_URI", "mongodb://127.0.0.1:27018/")


def mongo_db():
    return os.getenv("MONGO_DB", "hospital_lab2")


def redis_url():
    return os.getenv("REDIS_URL", "redis://127.0.0.1:6381/0")
