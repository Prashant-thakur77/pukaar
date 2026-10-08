from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from Pukaar.core.settings import get_settings


def get_upload_dir() -> Path:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir


def persist_upload(file: UploadFile | None, prefix: str) -> str | None:
    if not file or not file.filename:
        return None

    safe_name = Path(file.filename).name
    extension = Path(safe_name).suffix or '.bin'
    stored_name = f'{prefix}-{uuid4().hex}{extension}'
    target_path = get_upload_dir() / stored_name
    file.file.seek(0)
    with target_path.open('wb') as buffer:
        buffer.write(file.file.read())
    return str(target_path)
