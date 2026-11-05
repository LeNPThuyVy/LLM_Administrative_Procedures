import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select, delete, func

from context.database import AsyncSessionLocal
from context.models import ChatSession, Message, StructuredContext, User


router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"]
)

COOKIE_NAME = "hcc_session_id"
USER_COOKIE_NAME = "hcc_user_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 ngÃ y
USER_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 ngÃ y


async def _resolve_user_id(request: Request, db) -> uuid.UUID | None:
    """XÃ¡c Ä‘á»‹nh user_id tá»« cookie user_id hoáº·c tra cá»©u tá»« session_id hiá»‡n táº¡i."""
    cookie_user_id = request.cookies.get(USER_COOKIE_NAME)
    if cookie_user_id:
        try:
            return uuid.UUID(cookie_user_id)
        except ValueError:
            pass

    # Fallback: tra cá»©u tá»« session_id hiá»‡n táº¡i
    cookie_session_id = request.cookies.get(COOKIE_NAME)
    if cookie_session_id:
        try:
            s_uuid = uuid.UUID(cookie_session_id)
            res = await db.execute(
                select(ChatSession.user_id).where(ChatSession.id == s_uuid)
            )
            return res.scalar_one_or_none()
        except ValueError:
            pass

    return None



async def _require_authenticated_user_id(
    request: Request,
    db,
) -> uuid.UUID:
    """
    Bat buoc request phai co cookie user_id hop le.
    session_id khong duoc dung lam bang chung dinh danh
    cho cac thao tac doc/chuyen/xoa session.
    """
    raw_user_id = request.cookies.get(USER_COOKIE_NAME)

    if not raw_user_id:
        raise HTTPException(
            status_code=401,
            detail="Thieu thong tin dinh danh nguoi dung",
        )

    try:
        user_id = uuid.UUID(raw_user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Thong tin dinh danh nguoi dung khong hop le",
        )

    user_result = await db.execute(
        select(User.id).where(User.id == user_id)
    )
    existing_user_id = user_result.scalar_one_or_none()

    if existing_user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Thong tin dinh danh nguoi dung khong hop le",
        )

    return user_id

@router.get("")
async def list_user_sessions(request: Request):
    """
    Láº¥y danh sÃ¡ch cÃ¡c phiÃªn trÃ² chuyá»‡n cá»§a user hiá»‡n táº¡i Ä‘á»ƒ hiá»ƒn thá»‹ trÃªn sidebar.
    Má»—i phiÃªn kÃ¨m theo tiÃªu Ä‘á» tÃ³m táº¯t (tá»« cÃ¢u há»i Ä‘áº§u tiÃªn cá»§a user) vÃ  thá»i gian táº¡o.
    """
    async with AsyncSessionLocal() as db:
        user_id = await _resolve_user_id(request, db)
        if not user_id:
            return []

        # Truy váº¥n tá»‘i Ä‘a 30 sessions gáº§n nháº¥t
        sessions_res = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
            .limit(30)
        )
        sessions = sessions_res.scalars().all()

        results = []
        for s in sessions:
            # Láº¥y tin nháº¯n user Ä‘áº§u tiÃªn lÃ m tiÃªu Ä‘á»
            first_msg_res = await db.execute(
                select(Message.content)
                .where(
                    Message.session_id == s.id,
                    Message.role == "user"
                )
                .order_by(Message.created_at.asc())
                .limit(1)
            )
            first_msg = first_msg_res.scalar_one_or_none()

            # Äáº¿m tá»•ng sá»‘ tin nháº¯n
            count_res = await db.execute(
                select(func.count(Message.id)).where(Message.session_id == s.id)
            )
            msg_count = count_res.scalar() or 0

            if first_msg:
                # Cáº¯t gá»n tá»‘i Ä‘a 40 kÃ½ tá»±
                first_line = first_msg.strip().split("\n")[0]
                title = first_line[:40] + ("..." if len(first_line) > 40 else "")
            else:
                title = "Cuá»™c trÃ² chuyá»‡n má»›i"

            results.append({
                "id": str(s.id),
                "title": title,
                "message_count": msg_count,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            })

        return results


@router.post("/new")
async def create_new_session(request: Request, response: Response):
    """
    Táº¡o phiÃªn trÃ² chuyá»‡n má»›i cho user hiá»‡n táº¡i vÃ  cáº­p nháº­t cookie session_id.
    """
    async with AsyncSessionLocal() as db:
        user_id = await _resolve_user_id(request, db)
        if not user_id:
            user = User(id=uuid.uuid4(), name=None, email=None)
            db.add(user)
            await db.flush()
            user_id = user.id
            response.set_cookie(
                key=USER_COOKIE_NAME,
                value=str(user_id),
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=USER_COOKIE_MAX_AGE,
            )

        new_session_id = uuid.uuid4()
        chat_session = ChatSession(
            id=new_session_id,
            user_id=user_id,
        )
        db.add(chat_session)
        await db.commit()

        response.set_cookie(
            key=COOKIE_NAME,
            value=str(new_session_id),
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=COOKIE_MAX_AGE,
        )

        return {
            "session_id": str(new_session_id),
            "title": "Cuá»™c trÃ² chuyá»‡n má»›i",
            "message_count": 0,
            "created_at": chat_session.created_at.isoformat() if chat_session.created_at else None,
        }


@router.post("/{session_id}/switch")
async def switch_session(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
):
    """
    Chuyá»ƒn phiÃªn hoáº¡t Ä‘á»™ng sang session_id Ä‘Æ°á»£c chá»n vÃ  cáº­p nháº­t cookie session_id.
    """
    async with AsyncSessionLocal() as db:
        session_res = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = session_res.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="PhiÃªn khÃ´ng tá»“n táº¡i")

        user_id = await _require_authenticated_user_id(
            request,
            db,
        )

        if session.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Khong co quyen truy cap phien nay",
            )

        response.set_cookie(
            key=COOKIE_NAME,
            value=str(session_id),
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=COOKIE_MAX_AGE,
        )

        return {"status": "ok", "session_id": str(session_id)}


@router.delete("/{session_id}")
async def delete_session(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
):
    """
    XÃ³a phiÃªn trÃ² chuyá»‡n vÃ  toÃ n bá»™ dá»¯ liá»‡u tin nháº¯n/bá»™ nhá»› liÃªn quan.
    """
    async with AsyncSessionLocal() as db:
        session_res = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = session_res.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="PhiÃªn khÃ´ng tá»“n táº¡i")

        user_id = await _require_authenticated_user_id(
            request,
            db,
        )

        if session.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Khong co quyen truy cap phien nay",
            )

        # XÃ³a tin nháº¯n
        await db.execute(
            delete(Message).where(Message.session_id == session_id)
        )
        # XÃ³a structured context
        await db.execute(
            delete(StructuredContext).where(StructuredContext.session_id == session_id)
        )
        # XÃ³a session
        await db.delete(session)
        await db.commit()

        # Náº¿u Ä‘ang xÃ³a Ä‘Ãºng session hiá»‡n táº¡i trong cookie, xÃ³a cookie session_id
        cookie_session_id = request.cookies.get(COOKIE_NAME)
        if cookie_session_id == str(session_id):
            response.delete_cookie(
                key=COOKIE_NAME,
                path="/",
                httponly=True,
                samesite="lax",
            )

        return {"status": "ok", "deleted_session_id": str(session_id)}


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: uuid.UUID,
    request: Request,
):
    """
    Tráº£ lá»‹ch sá»­ tin nháº¯n cá»§a má»™t session.
    Cho phÃ©p Ä‘á»c náº¿u session_id trÃ¹ng cookie session_id HOáº¶C thuá»™c cÃ¹ng user_id.
    """
    async with AsyncSessionLocal() as db:
        session_result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = session_result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found"
            )

        user_id = await _require_authenticated_user_id(
            request,
            db,
        )

        if session.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="KhÃ´ng cÃ³ quyá»n truy cáº­p vÃ o phiÃªn nÃ y",
            )

        messages_result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        )
        messages = messages_result.scalars().all()

        return {
            "session_id": str(session.id),
            "user_id": str(session.user_id),
            "messages": [
                {
                    "id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "citations": (
                        message.evidence
                        if message.role == "assistant"
                        else None
                    ),
                    "created_at": (
                        message.created_at.isoformat()
                        if message.created_at
                        else None
                    )
                }
                for message in messages
            ]
        }
