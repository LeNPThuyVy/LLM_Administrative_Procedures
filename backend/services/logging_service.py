import json
import logging
import sys
from datetime import datetime, timezone


logger = logging.getLogger("rag_backend")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(message)s")
    )

    logger.addHandler(handler)

logger.setLevel(logging.INFO)
logger.propagate = False


def log_event(
    event: str,
    **fields,
) -> None:
    payload = {
        "timestamp":
            datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }

    logger.info(
        json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )
    )