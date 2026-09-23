import uuid

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect


router = APIRouter(tags=["anonymous-session", "websocket"])


COOKIE_NAME = "session_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 ngày


@router.get("/api/session/bootstrap")
async def bootstrap_session(
    request: Request,
    response: Response
):
    """
    Tạo anonymous session_id nếu browser chưa có cookie.
    Nếu đã có thì giữ nguyên session_id cũ.
    """

    session_id = request.cookies.get(COOKIE_NAME)

    # Nếu chưa có cookie hoặc cookie không phải UUID hợp lệ
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
            secure=False,       # local HTTP
            samesite="lax",
            max_age=COOKIE_MAX_AGE,
        )

        created = True

    else:
        created = False

    return {
        "session_id": session_id,
        "created": created
    }


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):

    session_id = websocket.cookies.get(COOKIE_NAME)

    # Socket bắt buộc phải có cookie session_id
    if not session_id:
        await websocket.close(
            code=4401,
            reason="Missing session_id cookie"
        )
        return

    try:
        uuid.UUID(session_id)
    except ValueError:
        await websocket.close(
            code=4400,
            reason="Invalid session_id cookie"
        )
        return

    await websocket.accept()

    print(
        f"[WS] session={session_id} CONNECTED"
    )

    # Message đầu tiên để client biết reconnect
    # vẫn đang dùng đúng session.
    await websocket.send_json({
        "type": "connected",
        "data": {
            "session_id": session_id
        }
    })

    try:
        while True:

            payload = await websocket.receive_json()

            # Day 1: mới test transport/connect/reconnect.
            # Day 2 mới nối RAG thật.
            await websocket.send_json({
                "type": "echo",
                "data": {
                    "session_id": session_id,
                    "received": payload
                }
            })

    except WebSocketDisconnect:

        print(
            f"[WS] session={session_id} DISCONNECTED"
        )