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
from backend.services.ai_service import (
    generate_answer,
    generate_answer_stream,
)
from backend.services.queue_service import queue_manager


router = APIRouter(
    tags=["anonymous-session", "websocket"]
)

COOKIE_NAME = "session_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 ngày
USER_COOKIE_NAME = "user_id"
USER_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 ngày


async def ensure_anonymous_session(session_id: str, user_id: str | None = None) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        session_uuid = uuid.UUID(session_id)

        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_uuid
            )
        )

        existing_session = result.scalar_one_or_none()

        if existing_session is not None:
            return str(existing_session.id), str(existing_session.user_id)

        # Kiểm tra user_id nếu có
        user = None
        if user_id:
            try:
                user_uuid = uuid.UUID(user_id)
                user_result = await db.execute(
                    select(User).where(User.id == user_uuid)
                )
                user = user_result.scalar_one_or_none()
            except ValueError:
                user = None

        if user is None:
            user = User(
                id=uuid.UUID(user_id) if user_id else uuid.uuid4(),
                name=None,
                email=None,
            )
            db.add(user)
            await db.flush()

        chat_session = ChatSession(
            id=session_uuid,
            user_id=user.id,
        )

        db.add(chat_session)
        await db.commit()

        print(
            f"[SESSION] anonymous session created: "
            f"{session_id} for user: {user.id}"
        )
        return str(chat_session.id), str(user.id)


@router.get("/api/session/bootstrap")
async def bootstrap_session(
    request: Request,
    response: Response,
):
    """
    Tạo anonymous session_id và persistent user_id nếu browser chưa có cookie.
    Nếu đã có thì giữ nguyên.
    """

    user_id = request.cookies.get(USER_COOKIE_NAME)
    if user_id:
        try:
            uuid.UUID(user_id)
        except ValueError:
            user_id = None

    if not user_id:
        user_id = str(uuid.uuid4())
        response.set_cookie(
            key=USER_COOKIE_NAME,
            value=user_id,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=USER_COOKIE_MAX_AGE,
        )

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

    await ensure_anonymous_session(session_id, user_id=user_id)

    return {
        "session_id": session_id,
        "user_id": user_id,
        "created": created,
    }


# ==============================================================================
# [DEV/TEST ONLY] Reset cookie endpoint - Có thể xóa khối này khi không cần nữa
# ==============================================================================
@router.api_route("/api/session/reset", methods=["GET", "POST"])
async def reset_session(response: Response):
    """Xóa cookie session_id và user_id để tạo mới hoàn toàn (dùng cho testing)."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=USER_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return {"status": "ok", "message": "Cookie đã được xóa"}
# ==============================================================================


@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
):
    # Lấy session_id trực tiếp từ cookie
    session_id = websocket.cookies.get(COOKIE_NAME)

    # Bắt buộc phải có cookie
    if not session_id:
        await websocket.close(
            code=4401,
            reason="Missing session_id cookie",
        )
        return

    # Kiểm tra UUID
    try:
        uuid.UUID(session_id)
    except ValueError:
        await websocket.close(
            code=4400,
            reason="Invalid session_id cookie",
        )
        return

    await websocket.accept()

    print(
        f"[WS] session={session_id} CONNECTED"
    )

    # Báo client biết socket đã kết nối
    await websocket.send_json({
        "type": "connected",
        "data": {
            "session_id": session_id,
        },
    })

    try:
        while True:
            # Nhận JSON từ client
            payload = await websocket.receive_json()

            query = str(
                payload.get("query", "")
            ).strip()

            domain = payload.get("domain", None)

            from domains import is_valid_domain
            if not is_valid_domain(domain):
                await websocket.send_json({
                    "type": "error",
                    "data": {
                        "code": 400,
                        "message": "Domain không hợp lệ",
                    }
                })
                continue

            # Query rỗng
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

            # Queue giống SSE cũ
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

                    # Truyền session_id xuống Context
                    # BUG-F fix: get_context() raises ValueError nếu
                    # session không tồn tại (race condition / DB reset).
                    # Bắt lỗi và báo client thay vì để crash WS.
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

                    result = None
                    try:
                        async with queue_manager.semaphore:
                            async for event_type, payload in generate_answer_stream(
                                query=query,
                                session_id=session_id,
                                context=context,
                                domain=domain,
                            ):
                                if event_type == "chunk":
                                    await websocket.send_json({
                                        "type": "chunk",
                                        "data": {"text": payload},
                                    })
                                elif event_type == "final":
                                    result = payload
                    except Exception as gen_exc:
                        print(f"[WS GENERATE ERROR] session={session_id}: {gen_exc}")
                        await websocket.send_json({
                            "type": "error",
                            "data": {
                                "message": "Hệ thống đang bận hoặc gặp lỗi xử lý. Bạn vui lòng thử lại sau ít giây.",
                            },
                        })
                        await websocket.send_json({
                            "type": "done",
                            "data": {
                                "answer": "Hệ thống đang bận hoặc gặp sự cố tạm thời. Bạn vui lòng thử gửi lại câu hỏi.",
                                "evidence_list": [],
                                "needs_clarification": False,
                            },
                        })
                        continue

                    if not result:
                        await websocket.send_json({
                            "type": "done",
                            "data": {
                                "answer": "Chưa nhận được câu trả lời từ hệ thống. Bạn vui lòng thử lại.",
                                "evidence_list": [],
                                "needs_clarification": False,
                            },
                        })
                        continue

                    # =========================
                    # 1. CLARIFICATION
                    # =========================
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

                        # Update memory theo session_id
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

                    # =========================
                    # 2. EVIDENCE
                    # =========================
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

                    # =========================
                    # 3. DONE
                    # =========================
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

                    # Truyền đúng session_id
                    # xuống Long-term Memory
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