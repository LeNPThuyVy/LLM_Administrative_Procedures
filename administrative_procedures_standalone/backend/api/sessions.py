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
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 ngày
USER_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 ngày


async def _resolve_user_id(request: Request, db) -> uuid.UUID | None:
    """Xác định user_id từ cookie user_id hoặc tra cứu từ session_id hiện tại."""
    cookie_user_id = request.cookies.get(USER_COOKIE_NAME)
    if cookie_user_id:
        try:
            return uuid.UUID(cookie_user_id)
        except ValueError:
            pass

    # Fallback: tra cứu từ session_id hiện tại
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


@router.get("")
async def list_user_sessions(request: Request):
    """
    Lấy danh sách các phiên trò chuyện của user hiện tại để hiển thị trên sidebar.
    Mỗi phiên kèm theo tiêu đề tóm tắt (từ câu hỏi đầu tiên của user) và thời gian tạo.
    """
    async with AsyncSessionLocal() as db:
        user_id = await _resolve_user_id(request, db)
        if not user_id:
            return []

        # Truy vấn tối đa 30 sessions gần nhất
        sessions_res = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
            .limit(30)
        )
        sessions = sessions_res.scalars().all()

        results = []
        for s in sessions:
            # Lấy tin nhắn user đầu tiên làm tiêu đề
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

            # Đếm tổng số tin nhắn
            count_res = await db.execute(
                select(func.count(Message.id)).where(Message.session_id == s.id)
            )
            msg_count = count_res.scalar() or 0

            if first_msg:
                # Cắt gọn tối đa 40 ký tự
                first_line = first_msg.strip().split("\n")[0]
                title = first_line[:40] + ("..." if len(first_line) > 40 else "")
            else:
                title = "Cuộc trò chuyện mới"

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
    Tạo phiên trò chuyện mới cho user hiện tại và cập nhật cookie session_id.
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
            "title": "Cuộc trò chuyện mới",
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
    Chuyển phiên hoạt động sang session_id được chọn và cập nhật cookie session_id.
    """
    async with AsyncSessionLocal() as db:
        session_res = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = session_res.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Phiên không tồn tại")

        user_id = await _resolve_user_id(request, db)
        if user_id and session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Không có quyền truy cập phiên này")

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
    Xóa phiên trò chuyện và toàn bộ dữ liệu tin nhắn/bộ nhớ liên quan.
    """
    async with AsyncSessionLocal() as db:
        session_res = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = session_res.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Phiên không tồn tại")

        user_id = await _resolve_user_id(request, db)
        if user_id and session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Không có quyền xóa phiên này")

        # Xóa tin nhắn
        await db.execute(
            delete(Message).where(Message.session_id == session_id)
        )
        # Xóa structured context
        await db.execute(
            delete(StructuredContext).where(StructuredContext.session_id == session_id)
        )
        # Xóa session
        await db.delete(session)
        await db.commit()

        # Nếu đang xóa đúng session hiện tại trong cookie, xóa cookie session_id
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
    Trả lịch sử tin nhắn của một session.
    Cho phép đọc nếu session_id trùng cookie session_id HOẶC thuộc cùng user_id.
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

        cookie_session_id = request.cookies.get(COOKIE_NAME)
        user_id = await _resolve_user_id(request, db)

        # Kiểm tra quyền: trùng session_id cookie hoặc cùng user_id
        has_access = False
        if cookie_session_id and cookie_session_id == str(session_id):
            has_access = True
        elif user_id and session.user_id == user_id:
            has_access = True

        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="Không có quyền truy cập vào phiên này"
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