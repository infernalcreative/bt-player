# /opt/bt-player/endpoints/mini.py
from fastapi import APIRouter, HTTPException, status
from core import core_engine

# Убираем "/notify" из префикса, чтобы путь формировался правильно
router = APIRouter(tags=["Kettle Plugin"])

@router.post("/notify/kettlemini")
async def notify_kettle():
    # Отправляем в ядро: имя колонки, имя mp3-файла
    success = core_engine.add_task(
        task_type="file",
        speaker_name="mini",
        payload="kettledone" # /opt/bt-player/mp3/kettledone.mp3
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Очередь аудиосистемы перегружена."
        )

    return {"status": "success", "plugin": "kettle", "message": "Задача для чайника добавлена в фоновую очередь."}

