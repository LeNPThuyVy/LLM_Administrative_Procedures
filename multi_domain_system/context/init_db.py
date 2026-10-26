import asyncio

from context.database import Base, engine
import context.models


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("Database tables created successfully.")


if __name__ == "__main__":
    asyncio.run(init_db())