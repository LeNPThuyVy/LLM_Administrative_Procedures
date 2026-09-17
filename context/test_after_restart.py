import asyncio
import json
import uuid

from context.context_service import get_context


SESSION_1_ID = "c2d277b2-8932-4773-a0d2-91809936ec4f"
SESSION_2_ID = "2fc5572b-c0f6-4daf-a044-91cf1792efe4"


async def main():
    context_1 = await get_context(
        uuid.UUID(SESSION_1_ID),
        "test restart"
    )

    context_2 = await get_context(
        uuid.UUID(SESSION_2_ID),
        "test restart"
    )

    print("\n===== AFTER RESTART - SESSION 1 =====")

    print(
        json.dumps(
            context_1,
            ensure_ascii=False,
            indent=2
        )
    )

    print("\n===== AFTER RESTART - SESSION 2 =====")

    print(
        json.dumps(
            context_2,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())