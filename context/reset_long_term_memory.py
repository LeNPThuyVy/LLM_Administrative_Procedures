import asyncio
from sqlalchemy import text

from context.database import engine
from context.models import LongTermMemory


async def reset_long_term_memory():
    async with engine.begin() as conn:
        await conn.execute(
            text("DROP TABLE IF EXISTS long_term_memory CASCADE")
        )

        await conn.run_sync(
            LongTermMemory.__table__.create
        )

    print("long_term_memory reset successfully.")


if __name__ == "__main__":
    asyncio.run(reset_long_term_memory())