# /opt/bt-player/endpoints/neo.py
from fastapi import APIRouter, HTTPException, status
from core import core_engine

# Префикс /notify оставляем, чтобы роут превратился в /notify/kettleneo
router = APIRouter(prefix="/notify", tags=["Kettle Neo Plugin"])

# Имя файла из вашей папки /opt/bt-player/mp3 без пути и расширения
AUDIO_FILENAME = "kettledone" # /opt/bt-player/mp3/kettledone.mp3
SPEAKER_NAME = "neo"

@router.post("/kettleneo")
async def notify_kettle_neo():
    # Отправляем в фоновую очередь: тип "file", имя колонки "neo", имя файла "kettledone"
    success = core_engine.add_task(
        task_type="file",
        speaker_name=SPEAKER_NAME,
        payload=AUDIO_FILENAME
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Очередь аудиосистемы перегружена."
        )

    return {
        "status": "success", 
        "plugin": "kettle_neo", 
        "message": "Задача для чайника на колонке Neo успешно добавлена в очередь."
    }

