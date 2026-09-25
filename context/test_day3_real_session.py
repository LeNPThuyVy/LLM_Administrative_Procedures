import asyncio
import json
import urllib.request
from http.cookies import SimpleCookie

import websockets

from context.context_service import get_context


BASE_HTTP = "http://127.0.0.1:8000"
BOOTSTRAP_URL = f"{BASE_HTTP}/api/session/bootstrap"
WS_URL = "ws://127.0.0.1:8000/ws/chat"


def bootstrap_real_session():
    """
    Gọi endpoint thật của Person 3 để lấy:
    - session_id thật
    - cookie session_id thật
    """

    request = urllib.request.Request(
        BOOTSTRAP_URL,
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        body = response.read().decode("utf-8")
        data = json.loads(body)

        session_id = data.get("session_id")

        set_cookie_header = response.headers.get(
            "Set-Cookie"
        )

    if not session_id:
        raise RuntimeError(
            "Bootstrap không trả về session_id."
        )

    if not set_cookie_header:
        raise RuntimeError(
            "Bootstrap không trả về cookie session_id."
        )

    cookie = SimpleCookie()
    cookie.load(set_cookie_header)

    if "session_id" not in cookie:
        raise RuntimeError(
            "Không tìm thấy session_id trong Set-Cookie."
        )

    cookie_session_id = (
        cookie["session_id"].value
    )

    if cookie_session_id != session_id:
        raise RuntimeError(
            "session_id trong JSON và cookie không giống nhau."
        )

    cookie_header = (
        f"session_id={cookie_session_id}"
    )

    return session_id, cookie_header


async def connect_websocket(cookie_header):
    """
    Hỗ trợ cả websockets version mới và cũ.
    """

    try:
        return await websockets.connect(
            WS_URL,
            additional_headers={
                "Cookie": cookie_header
            },
            open_timeout=20,
        )

    except TypeError:
        return await websockets.connect(
            WS_URL,
            extra_headers={
                "Cookie": cookie_header
            },
            open_timeout=20,
        )


async def receive_until_done(ws):
    """
    Đọc message cho đến event done.
    """

    events = []

    while True:

        raw = await asyncio.wait_for(
            ws.recv(),
            timeout=180,
        )

        data = json.loads(raw)

        events.append(data)

        event_type = data.get("type")

        print(
            f"[WS EVENT] {event_type}"
        )

        if event_type == "done":
            break

    return events


async def send_query(
    ws,
    query: str
):
    print()
    print("USER:")
    print(query)

    await ws.send(
        json.dumps(
            {
                "query": query
            },
            ensure_ascii=False,
        )
    )

    return await receive_until_done(ws)


async def wait_memory_update():
    """
    socket.py dùng asyncio.create_task(update_memory(...)),
    nên chờ ngắn để background task commit DB.
    """
    await asyncio.sleep(2)


async def main():

    print("=" * 70)
    print("PERSON 2 - DAY 3 REAL SESSION TEST")
    print("=" * 70)

    # =====================================================
    # 1. BOOTSTRAP COOKIE / SESSION THẬT
    # =====================================================

    session_id, cookie_header = (
        bootstrap_real_session()
    )

    print()
    print("REAL SESSION ID:")
    print(session_id)

    print()
    print("REAL SESSION TEST PASSED")

    # =====================================================
    # 2. WEBSOCKET CONNECT LẦN 1
    # =====================================================

    ws = await connect_websocket(
        cookie_header
    )

    connected_raw = await asyncio.wait_for(
        ws.recv(),
        timeout=20,
    )

    connected_data = json.loads(
        connected_raw
    )

    print()
    print("FIRST CONNECTION:")
    print(connected_data)

    if connected_data.get("type") != "connected":
        raise RuntimeError(
            "WebSocket không trả event connected."
        )

    connected_session = (
        connected_data
        .get("data", {})
        .get("session_id")
    )

    if connected_session != session_id:
        raise RuntimeError(
            "Session ID của WebSocket không khớp cookie."
        )

    print()
    print("WEBSOCKET CONNECT PASSED")

    # =====================================================
    # 3. GỬI CÂU HỎI ĐẦU
    # =====================================================

    await send_query(
        ws,
        (
            "Tôi muốn làm thủ tục "
            "đăng ký thường trú ở TP.HCM"
        ),
    )

    await wait_memory_update()

    context_before_reconnect = await get_context(
        session_id=session_id,
        query="test",
    )

    print()
    print("CONTEXT BEFORE RECONNECT:")
    print(
        context_before_reconnect.get(
            "structured_context",
            {}
        )
    )

    memory_before = (
        context_before_reconnect.get(
            "long_term_memory",
            {}
        )
    )

    if (
        memory_before.get("procedure_name")
        != "Đăng ký thường trú"
    ):
        raise RuntimeError(
            "Memory chưa lưu procedure_name."
        )

    if (
        memory_before.get("location")
        != "TP.HCM"
    ):
        raise RuntimeError(
            "Memory chưa lưu location."
        )

    # =====================================================
    # 4. DISCONNECT
    # =====================================================

    await ws.close()

    print()
    print("WEBSOCKET DISCONNECTED")

    await asyncio.sleep(1)

    # =====================================================
    # 5. RECONNECT BẰNG CHÍNH COOKIE CŨ
    # =====================================================

    ws2 = await connect_websocket(
        cookie_header
    )

    reconnect_raw = await asyncio.wait_for(
        ws2.recv(),
        timeout=20,
    )

    reconnect_data = json.loads(
        reconnect_raw
    )

    print()
    print("RECONNECT RESPONSE:")
    print(reconnect_data)

    reconnect_session = (
        reconnect_data
        .get("data", {})
        .get("session_id")
    )

    if reconnect_session != session_id:
        raise RuntimeError(
            "Session ID thay đổi sau reconnect."
        )

    print()
    print("WEBSOCKET RECONNECT PASSED")

    # =====================================================
    # 6. HỎI TIẾP MÀ KHÔNG NHẮC LẠI TÊN THỦ TỤC
    # =====================================================

    await send_query(
        ws2,
        "Tôi cần chuẩn bị giấy tờ gì?",
    )

    await wait_memory_update()

    # =====================================================
    # 7. ĐỌC MEMORY SAU RECONNECT
    # =====================================================

    final_context = await get_context(
        session_id=session_id,
        query="test",
    )

    structured = final_context.get(
        "structured_context",
        {}
    )

    memory = final_context.get(
        "long_term_memory",
        {}
    )

    print()
    print("=" * 70)
    print("STRUCTURED CONTEXT AFTER RECONNECT:")
    print(structured)

    print()
    print("LONG TERM MEMORY AFTER RECONNECT:")
    print(memory)

    # =====================================================
    # 8. ASSERT
    # =====================================================

    errors = []

    if (
        structured.get("procedure_name")
        != "Đăng ký thường trú"
    ):
        errors.append(
            "structured_context mất procedure_name"
        )

    if (
        structured.get("location")
        != "TP.HCM"
    ):
        errors.append(
            "structured_context mất location"
        )

    if (
        memory.get("procedure_name")
        != "Đăng ký thường trú"
    ):
        errors.append(
            "long_term_memory mất procedure_name"
        )

    if (
        memory.get("location")
        != "TP.HCM"
    ):
        errors.append(
            "long_term_memory mất location"
        )

    if errors:

        print()
        print("PERSON 2 DAY 3 FAILED")

        for error in errors:
            print("-", error)

        await ws2.close()

        raise RuntimeError(
            "Memory bị mất sau reconnect."
        )

    print()
    print("MEMORY PRESERVED AFTER RECONNECT")

    print()
    print("PERSON 2 DAY 3 PASSED")
    print("=" * 70)

    await ws2.close()


if __name__ == "__main__":
    asyncio.run(main())