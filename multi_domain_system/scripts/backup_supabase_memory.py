"""
scripts/backup_supabase_memory.py — Backup Supabase memory tables before Phase 1.
Dumps users, sessions, messages, structured_context, conversation_summary, long_term_memory to JSON.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime
from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from context.database import AsyncSessionLocal
from context.models import User, ChatSession, Message, StructuredContext, ConversationSummary, LongTermMemory

def default_json_serializer(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)

async def run_backup():
    output_path = ROOT_DIR / "data" / "backup_supabase_memory_pre_phase1.json"
    print(f"[backup] Connecting to database to backup memory tables...")

    backup_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "users": [],
        "sessions": [],
        "messages": [],
        "structured_context": [],
        "conversation_summary": [],
        "long_term_memory": [],
    }

    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(User))
            for u in res.scalars().all():
                backup_data["users"].append({"id": str(u.id), "name": u.name, "email": u.email})

            res = await db.execute(select(ChatSession))
            for s in res.scalars().all():
                backup_data["sessions"].append({"id": str(s.id), "user_id": str(s.user_id), "created_at": s.created_at})

            res = await db.execute(select(Message))
            for m in res.scalars().all():
                backup_data["messages"].append({
                    "id": str(m.id),
                    "session_id": str(m.session_id),
                    "role": m.role,
                    "content": m.content,
                    "evidence": m.evidence,
                    "created_at": m.created_at,
                })

            res = await db.execute(select(StructuredContext))
            for sc in res.scalars().all():
                backup_data["structured_context"].append({"session_id": str(sc.session_id), "data": sc.data})

            res = await db.execute(select(ConversationSummary))
            for sm in res.scalars().all():
                backup_data["conversation_summary"].append({"session_id": str(sm.session_id), "summary": sm.summary})

            res = await db.execute(select(LongTermMemory))
            for ltm in res.scalars().all():
                backup_data["long_term_memory"].append({"user_id": str(ltm.user_id), "data": ltm.data})

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2, default=default_json_serializer)

        print(f"[backup] Successfully backed up {len(backup_data['messages'])} messages, "
              f"{len(backup_data['structured_context'])} structured contexts, "
              f"{len(backup_data['conversation_summary'])} summaries, "
              f"{len(backup_data['long_term_memory'])} LTM records to {output_path}")
        return True
    except Exception as e:
        print(f"[backup] Error backing up database: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(run_backup())
