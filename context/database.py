import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine
)

from sqlalchemy.orm import DeclarativeBase


# Đọc .env (KHÔNG commit .env vào git — DATABASE_URL của Supabase có
# password thật trong đó). File .env đã có sẵn trong .gitignore.
load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # Fallback cho dev local nếu không có .env
    "postgresql+asyncpg://postgres:postgres@localhost:5432/"
    "administrative_ai",
)

DB_SSL = os.getenv("DB_SSL", "true").lower() == "true"

connect_args = {
    "statement_cache_size": 0,
}

if DB_SSL:
    connect_args["ssl"] = "require"


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args=connect_args,
)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session