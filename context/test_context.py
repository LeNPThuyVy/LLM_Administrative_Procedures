import asyncio
import json
import uuid

from context.context_service import get_context


SESSION_ID = "34398793-cba5-4d9d-ac7a-7773035e3284"


async def main():
    context = await get_context(
        session_id=uuid.UUID(SESSION_ID),
        query="Tôi cần chuẩn bị giấy tờ gì?"
    )

    print(
        json.dumps(
            context,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())