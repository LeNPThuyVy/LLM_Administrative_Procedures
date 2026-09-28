import asyncio
import uuid

from sqlalchemy import select

from context.database import AsyncSessionLocal
from context.models import User, ChatSession

from fastapi import (
    APIRouter,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)

from fastapi.encoders import jsonable_encoder

from backend.services.context_service import (
    get_context,
    update_memory,
)

from backend.services.ai_service import generate_answer
from backend.services.queue_service import queue_manager


router = APIRouter(
    tags=["anonymous-session", "websocket"]
)


COOKIE_NAME = "session_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 ngày


# =========================================================
# SESSION HELPER
# =========================================================
async def ensure_anonymous_session(session_id: str):
    async with AsyncSessionLocal() as db:
        session_uuid = uuid.UUID(session_id)

        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_uuid
            )
        )

        existing_session = result.scalar_one_or_none()

        if existing_session is not None:
            return

        anonymous_user = User(
            name=None,
            email=None,
        )

        db.add(anonymous_user)
        await db.flush()

        chat_session = ChatSession(
            id=session_uuid,
            user_id=anonymous_user.id,
        )

        db.add(chat_session)
        await db.commit()

        print(
            f"[SESSION] anonymous session created: "
            f"{session_id}"
        )


# =========================================================
# SESSION BOOTSTRAP
# =========================================================
@router.get("/api/session/bootstrap")
async def bootstrap_session(
    request: Request,
    response: Response,
):
    """
    Tạo anonymous session_id nếu browser chưa có cookie.
    Nếu đã có thì giữ nguyên session_id cũ.
    """

    session_id = request.cookies.get(COOKIE_NAME)

    if session_id:
        try:
            uuid.UUID(session_id)
        except ValueError:
            session_id = None

    if not session_id:
        session_id = str(uuid.uuid4())

        response.set_cookie(
            key=COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=COOKIE_MAX_AGE,
        )

        created = True

    else:
        created = False

    await ensure_anonymous_session(session_id)

    return {
        "session_id": session_id,
        "created": created,
    }


# =========================================================
# WEBSOCKET CHAT
# =========================================================
@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
):
    # =====================================================
    # Quan trọng:
    # Accept trước để browser nhận được custom close code
    # 4401 / 4400 thay vì HTTP 403 / WebSocket 1006.
    # =====================================================
    await websocket.accept()

    # Lấy session_id từ cookie
    session_id = websocket.cookies.get(COOKIE_NAME)

    # =====================================================
    # WS-02: Không có cookie
    # =====================================================
    if not session_id:
        await websocket.close(
            code=4401,
            reason="Missing session_id cookie",
        )
        return

    # =====================================================
    # WS-03: Cookie không phải UUID hợp lệ
    # =====================================================
    try:
        uuid.UUID(session_id)

    except (ValueError, TypeError):
        await websocket.close(
            code=4400,
            reason="Invalid session_id cookie",
        )
        return

    print(
        f"[WS] session={session_id} CONNECTED"
    )

    # Báo client socket đã kết nối
    await websocket.send_json({
        "type": "connected",
        "data": {
            "session_id": session_id,
        },
    })

    try:
        while True:

            # =================================================
            # NHẬN REQUEST
            # =================================================
            payload = await websocket.receive_json()

            query = str(
                payload.get("query", "")
            ).strip()

            # =================================================
            # WS-04 / WS-05:
            # Query rỗng hoặc không có key query
            # =================================================
            if not query:

                await websocket.send_json({
                    "type": "clarification",
                    "data": {
                        "question":
                            "Bạn vui lòng nhập câu hỏi.",
                    },
                })

                await websocket.send_json({
                    "type": "done",
                    "data": {
                        "needs_clarification": True,
                    },
                })

                continue

            # =================================================
            # QUEUE + SESSION LOCK
            # =================================================
            session_lock = (
                queue_manager.get_session_lock(
                    session_id
                )
            )

            async with session_lock:

                async with queue_manager.semaphore:

                    request_type = (
                        queue_manager.classify_request(
                            query
                        )
                    )

                    print(
                        f"[WS QUEUE] "
                        f"session={session_id} "
                        f"type={request_type} START"
                    )

                    # =========================================
                    # CONTEXT
                    # =========================================
                    # get_context() có thể raise ValueError
                    # khi session không tồn tại trong DB.
                    try:
                        context = await get_context(
                            session_id,
                            query,
                        )

                    except ValueError as exc:

                        print(
                            f"[WS] get_context error for "
                            f"session={session_id}: {exc}"
                        )

                        await websocket.send_json({
                            "type": "error",
                            "data": {
                                "message": (
                                    "Phiên làm việc không hợp lệ. "
                                    "Vui lòng tải lại trang."
                                ),
                            },
                        })

                        continue

                    # =========================================
                    # AI / RAG
                    # =========================================
                    result = await generate_answer(
                        query=query,
                        session_id=session_id,
                        context=context,
                    )

                    # =========================================
                    # 1. CLARIFICATION
                    # =========================================
                    if result["needs_clarification"]:

                        await websocket.send_json({
                            "type": "clarification",
                            "data": {
                                "question":
                                    result[
                                        "clarification_question"
                                    ]
                            },
                        })

                        await websocket.send_json({
                            "type": "done",
                            "data": {
                                "needs_clarification":
                                    True,
                            },
                        })

                        print(
                            f"[WS QUEUE] "
                            f"session={session_id} DONE"
                        )

                        asyncio.create_task(
                            update_memory(
                                session_id=session_id,
                                query=query,
                                final_result=result,
                            )
                        )

                        print(
                            f"[MEMORY] "
                            f"session={session_id} "
                            f"update scheduled"
                        )

                        continue

                    # =========================================
                    # 2. EVIDENCE
                    # =========================================
                    evidence_data = {
                        "evidence_list":
                            result["evidence_list"]
                    }

                    await websocket.send_json(
                        jsonable_encoder({
                            "type": "evidence",
                            "data": evidence_data,
                        })
                    )

                    # =========================================
                    # 3. CHUNK
                    # =========================================
                    for word in (
                        result["answer"].split()
                    ):

                        await websocket.send_json({
                            "type": "chunk",
                            "data": {
                                "text": word + " ",
                            },
                        })

                        await asyncio.sleep(0.05)

                    # =========================================
                    # 4. DONE
                    # =========================================
                    done_data = {
                        "answer":
                            result["answer"],

                        "evidence_list":
                            result["evidence_list"],

                        "needs_clarification":
                            False,
                    }

                    await websocket.send_json(
                        jsonable_encoder({
                            "type": "done",
                            "data": done_data,
                        })
                    )

                    print(
                        f"[WS QUEUE] "
                        f"session={session_id} DONE"
                    )

                    # =========================================
                    # LONG-TERM MEMORY
                    # =========================================
                    asyncio.create_task(
                        update_memory(
                            session_id=session_id,
                            query=query,
                            final_result=result,
                        )
                    )

                    print(
                        f"[MEMORY] "
                        f"session={session_id} "
                        f"update scheduled"
                    )

    except WebSocketDisconnect:

        print(
            f"[WS] "
            f"session={session_id} "
            f"DISCONNECTED"
        )