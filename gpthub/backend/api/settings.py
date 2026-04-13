"""
Settings API — manage API key at runtime.
The key is stored as an env var (MWS_API_KEY) and can be updated via this API.
It persists in a file so it survives container restarts.
"""

import os
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

_KEY_FILE = Path("/app/data/api_key.txt")


class ApiKeyUpdate(BaseModel):
    api_key: str


@router.get("")
async def get_settings():
    """Return current settings (API key masked)."""
    key = os.environ.get("MWS_API_KEY", "")
    masked = key[:8] + "..." + key[-4:] if len(key) > 12 else ("*" * len(key) if key else "")
    return {
        "api_key_set": bool(key),
        "api_key_masked": masked,
        "api_base": os.environ.get("MWS_API_BASE", ""),
    }


@router.put("/api-key")
async def update_api_key(body: ApiKeyUpdate):
    """Update the MWS API key at runtime."""
    new_key = body.api_key.strip()
    if not new_key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")

    # Update env var for current process
    os.environ["MWS_API_KEY"] = new_key

    # Persist to file so it survives restarts
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(new_key)
        logger.info("API key updated and persisted to %s", _KEY_FILE)
    except Exception:
        logger.warning("Failed to persist API key to file", exc_info=True)

    masked = new_key[:8] + "..." + new_key[-4:] if len(new_key) > 12 else "***"
    return {"status": "updated", "api_key_masked": masked}


def load_persisted_key():
    """Load API key from file if it exists (called at startup)."""
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_text().strip()
        if key:
            os.environ["MWS_API_KEY"] = key
            logger.info("Loaded persisted API key from %s", _KEY_FILE)
