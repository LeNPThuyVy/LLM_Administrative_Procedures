import asyncio
import time
import uuid

import my_config
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
from backend.services.queue_service import (
    queue_manager,
    QueueFullError,
    QueueTimeoutError,
)
from backend.services.rate_limit_service import (
    rate_limiter,
    RateLimitExceeded,
)
from backend.services.logging_service import log_event


router = APIRouter(
    tags=[
        "anonymous-session",
        "websocket",
    ]
)

COOKIE_NAME = "session_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 ngày


# =========================================================
# SESSION HELPERS
# =========================================================

async def ensure_anonymous_session(
    session_id: str,
):
    async with AsyncSessionLocal() as db:
        session_uuid = uuid.UUID(
            session_id
        )

        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id
                == session_uuid
            )
        )

        existing_session = (
            result.scalar_one_or_none()
        )

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
            "[SESSION] anonymous session "
            f"created: {session_id}"
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
    Tạo anonymous session_id nếu browser
    chưa có cookie.

    Nếu đã có thì giữ nguyên session_id cũ.
    """

    session_id = request.cookies.get(
        COOKIE_NAME
    )

    if session_id:
        try:
            uuid.UUID(session_id)
        except ValueError:
            session_id = None

    if not session_id:
        session_id = str(
            uuid.uuid4()
        )

        response.set_cookie(
            key=COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=(
                request.url.scheme
                == "https"
            ),
            samesite="lax",
            max_age=COOKIE_MAX_AGE,
        )

        created = True

    else:
        created = False

    await ensure_anonymous_session(
        session_id
    )

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
    # Một ID riêng cho mỗi WebSocket connection.
    connection_id = str(
        uuid.uuid4()
    )

    # =====================================================
    # ORIGIN CHECK
    # =====================================================

    origin = websocket.headers.get(
        "origin"
    )

    allowed_origins = {
        item.strip()
        for item
        in my_config.ALLOWED_ORIGINS.split(
            ","
        )
        if item.strip()
    }

    if (
        origin
        and origin
        not in allowed_origins
    ):
        log_event(
            "ws_rejected",
            connection_id=connection_id,
            reason="origin_not_allowed",
        )

        await websocket.close(
            code=4403,
            reason="Origin not allowed",
        )

        return

    # =====================================================
    # SESSION COOKIE CHECK
    # =====================================================

    session_id = websocket.cookies.get(
        COOKIE_NAME
    )

    if not session_id:
        log_event(
            "ws_rejected",
            connection_id=connection_id,
            reason="missing_session_cookie",
        )

        await websocket.close(
            code=4401,
            reason=(
                "Missing session_id cookie"
            ),
        )

        return

    try:
        uuid.UUID(session_id)

    except ValueError:
        log_event(
            "ws_rejected",
            connection_id=connection_id,
            reason="invalid_session_cookie",
        )

        await websocket.close(
            code=4400,
            reason=(
                "Invalid session_id cookie"
            ),
        )

        return

    # =====================================================
    # ACCEPT CONNECTION
    # =====================================================

    await websocket.accept()

    client_ip = (
        websocket.client.host
        if websocket.client
        else "unknown"
    )

    # Helper log cho từng message.
    # Không log query, cookie, token hoặc IP.
    def log_ws_message(
        message_id: str,
        started: float,
        status: str,
        **extra,
    ) -> None:
        latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )

        log_event(
            "ws_message",
            connection_id=connection_id,
            message_id=message_id,
            status=status,
            latency_ms=latency_ms,
            **extra,
        )

    print(
        "[WS] "
        f"session={session_id} "
        "CONNECTED"
    )

    log_event(
        "ws_connected",
        connection_id=connection_id,
    )

    await websocket.send_json({
        "type": "connected",
        "data": {
            "session_id": session_id,
        },
    })

    # =====================================================
    # MESSAGE LOOP
    # =====================================================

    try:
        while True:
            payload = (
                await websocket.receive_json()
            )

            message_id = str(
                uuid.uuid4()
            )

            message_started = (
                time.perf_counter()
            )

            query = str(
                payload.get(
                    "query",
                    "",
                )
            ).strip()

            domain = payload.get(
                "domain",
                None,
            )

            # =============================================
            # DOMAIN VALIDATION
            # =============================================

            from domains import (
                is_valid_domain,
            )

            if not is_valid_domain(
                domain
            ):
                await websocket.send_json({
                    "type": "error",
                    "data": {
                        "code": 400,
                        "message":
                            "Domain không hợp lệ",
                    },
                })

                log_ws_message(
                    message_id,
                    message_started,
                    "invalid_domain",
                )

                continue

            # =============================================
            # EMPTY QUERY
            # =============================================

            if not query:
                await websocket.send_json({
                    "type": "clarification",
                    "data": {
                        "question":
                            "Bạn vui lòng nhập "
                            "câu hỏi.",
                    },
                })

                await websocket.send_json({
                    "type": "done",
                    "data": {
                        "needs_clarification":
                            True,
                    },
                })

                log_ws_message(
                    message_id,
                    message_started,
                    "clarification",
                    reason="empty_query",
                )

                continue

            # =============================================
            # RATE LIMIT
            # =============================================

            try:
                await rate_limiter.check(
                    session_id=session_id,
                    ip_address=client_ip,
                )

            except RateLimitExceeded as exc:
                await websocket.send_json({
                    "type": "error",
                    "data": {
                        "code": 429,
                        "message": (
                            "Bạn gửi yêu cầu "
                            "quá nhanh. "
                            "Vui lòng thử lại sau."
                        ),
                        "scope":
                            exc.scope,
                        "retry_after":
                            exc.retry_after,
                    },
                })

                log_ws_message(
                    message_id,
                    message_started,
                    "rate_limited",
                    scope=exc.scope,
                )

                continue

            # =============================================
            # QUEUE + AI
            # =============================================

            try:
                async with (
                    queue_manager.session_scope(
                        session_id
                    )
                ):
                    # Chỉ giữ semaphore
                    # trong lúc xử lý AI.
                    async with (
                        queue_manager.execution_slot()
                    ):
                        request_type = (
                            queue_manager
                            .classify_request(
                                query
                            )
                        )

                        print(
                            "[WS QUEUE] "
                            f"session={session_id} "
                            f"type={request_type} "
                            "START"
                        )

                        # =================================
                        # CONTEXT
                        # =================================

                        try:
                            context = (
                                await get_context(
                                    session_id,
                                    query,
                                )
                            )

                        except ValueError as exc:
                            print(
                                "[WS] "
                                "get_context error "
                                f"for session="
                                f"{session_id}: "
                                f"{exc}"
                            )

                            await websocket.send_json({
                                "type": "error",
                                "data": {
                                    "message": (
                                        "Phiên làm việc "
                                        "không hợp lệ. "
                                        "Vui lòng tải "
                                        "lại trang."
                                    ),
                                },
                            })

                            log_ws_message(
                                message_id,
                                message_started,
                                "context_error",
                            )

                            continue

                        # =================================
                        # AI
                        # =================================

                        result = (
                            await generate_answer(
                                query=query,
                                session_id=(
                                    session_id
                                ),
                                context=context,
                                domain=domain,
                            )
                        )

                    # =====================================
                    # Semaphore đã được release từ đây.
                    # Chỉ gửi dữ liệu về client.
                    # =====================================

                    # =====================================
                    # 1. CLARIFICATION
                    # =====================================

                    if result[
                        "needs_clarification"
                    ]:
                        await websocket.send_json({
                            "type":
                                "clarification",
                            "data": {
                                "question":
                                    result[
                                        "clarification_question"
                                    ],
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
                            "[WS QUEUE] "
                            f"session={session_id} "
                            "DONE"
                        )

                        asyncio.create_task(
                            update_memory(
                                session_id=(
                                    session_id
                                ),
                                query=query,
                                final_result=(
                                    result
                                ),
                            )
                        )

                        print(
                            "[MEMORY] "
                            f"session={session_id} "
                            "update scheduled"
                        )

                        log_ws_message(
                            message_id,
                            message_started,
                            "clarification",
                        )

                        continue

                    # =====================================
                    # 2. EVIDENCE
                    # =====================================

                    evidence_data = {
                        "evidence_list":
                            result[
                                "evidence_list"
                            ]
                    }

                    await websocket.send_json(
                        jsonable_encoder({
                            "type":
                                "evidence",
                            "data":
                                evidence_data,
                        })
                    )

                    # =====================================
                    # 3. CHUNK
                    # =====================================
                    #
                    # Tạm thời vẫn streaming giả.
                    # Sau khi B cung cấp
                    # answer_question_stream()
                    # thì mới nối streaming thật.
                    # =====================================

                    for word in (
                        result["answer"].split()
                    ):
                        await websocket.send_json({
                            "type": "chunk",
                            "data": {
                                "text":
                                    word + " ",
                            },
                        })

                        await asyncio.sleep(
                            0.05
                        )

                    # =====================================
                    # 4. DONE
                    # =====================================

                    done_data = {
                        "answer":
                            result["answer"],
                        "evidence_list":
                            result[
                                "evidence_list"
                            ],
                        "needs_clarification":
                            False,
                    }

                    await websocket.send_json(
                        jsonable_encoder({
                            "type": "done",
                            "data": done_data,
                        })
                    )

                    # Chỉ log OK sau khi client
                    # đã nhận event done.
                    log_ws_message(
                        message_id,
                        message_started,
                        "ok",
                    )

                    print(
                        "[WS QUEUE] "
                        f"session={session_id} "
                        "DONE"
                    )

                    # Update memory chạy nền.
                    asyncio.create_task(
                        update_memory(
                            session_id=(
                                session_id
                            ),
                            query=query,
                            final_result=result,
                        )
                    )

                    print(
                        "[MEMORY] "
                        f"session={session_id} "
                        "update scheduled"
                    )

            # =============================================
            # QUEUE FULL
            # =============================================

            except QueueFullError:
                await websocket.send_json({
                    "type": "error",
                    "data": {
                        "code": 429,
                        "message": (
                            "Hệ thống đang "
                            "quá tải. "
                            "Vui lòng thử lại sau."
                        ),
                    },
                })

                log_ws_message(
                    message_id,
                    message_started,
                    "queue_full",
                )

            # =============================================
            # QUEUE TIMEOUT
            # =============================================

            except QueueTimeoutError:
                await websocket.send_json({
                    "type": "error",
                    "data": {
                        "code": 429,
                        "message": (
                            "Yêu cầu chờ quá lâu. "
                            "Vui lòng thử lại sau."
                        ),
                    },
                })

                log_ws_message(
                    message_id,
                    message_started,
                    "queue_timeout",
                )

    # =====================================================
    # DISCONNECT
    # =====================================================

    except WebSocketDisconnect:
        print(
            "[WS] "
            f"session={session_id} "
            "DISCONNECTED"
        )

        log_event(
            "ws_disconnected",
            connection_id=connection_id,
        )