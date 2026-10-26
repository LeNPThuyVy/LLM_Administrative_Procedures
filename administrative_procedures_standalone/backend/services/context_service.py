from context.context_service import (
    get_context as real_get_context,
    update_memory as real_update_memory,
)


async def get_context(session_id: str, query: str):
    return await real_get_context(
        session_id=session_id,
        query=query
    )


async def update_memory(
    session_id: str,
    query: str,
    final_result: dict
):
    await real_update_memory(
        session_id=session_id,
        query=query,
        final_result=final_result
    )