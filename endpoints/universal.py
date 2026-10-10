# /opt/bt-player/endpoints/universal.py
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from core import core_engine


router = APIRouter(tags=["Universal Player"])

class TTSRequest(BaseModel):
    speaker: str    # "neo", "mini" и т.д.
    text: str       # Текст для озвучки Piper TTS

class FileRequest(BaseModel):
    speaker: str    # "neo", "mini" и т.д.
    filename: str   # Только имя файла без пути и расширения (например, "kettledone")

@router.post("/say", status_code=status.HTTP_202_ACCEPTED)
async def say_text(payload: TTSRequest):
    """Синтезировать произвольный текст голосом на указанной колонке."""
    success = core_engine.add_task(
        task_type="tts",
        speaker_name=payload.speaker,
        payload=payload.text
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось поставить задачу в очередь. Проверьте имя колонки '{payload.speaker}'."
        )
    return {"status": "queued", "message": "Текст успешно поставлен в очередь на озвучку."}

@router.post("/play", status_code=status.HTTP_202_ACCEPTED)
async def play_file(payload: FileRequest):
    """Воспроизвести готовый MP3-файл из каталога по его имени."""
    success = core_engine.add_task(
        task_type="file",
        speaker_name=payload.speaker,
        payload=payload.filename
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось поставить задачу в очередь. Проверьте имя колонки '{payload.speaker}'."
        )
    return {"status": "queued", "message": f"Файл {payload.filename}.mp3 успешно поставлен в очередь."}

