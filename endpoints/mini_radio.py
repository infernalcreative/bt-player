# /opt/bt-player/endpoints/mini_radio_enj.py
from fastapi import APIRouter, HTTPException, status
from config_manager import config_manager
import utils
import asyncio

# Сохраняем префикс /radio, итоговый путь: POST /radio/mini_nrj
router = APIRouter(prefix="/radio", tags=["Radio NRJ Plugin"])

SPEAKER_NAME = "mini"
STREAM_URL = "http://streamurl"

@router.post("/mini_nrj")
async def play_radio_nrj():
    # 1. Получаем актуальные параметры колонки из центрального конфига
    cfg = config_manager.get_speaker(SPEAKER_NAME)
    if not cfg:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Колонка '{SPEAKER_NAME}' не найдена в конфигурации speakers.conf"
        )

    # 2. Подключаем Bluetooth-колонку (выполняется асинхронно в контексте запроса)
    utils.manage_bluetooth("connect", cfg.mac_raw)
    await asyncio.sleep(1.0)
    
    # 3. Управляем громкостью (выставляем активную громкость из конфига, для mini это 64)
    if cfg.active_volume > 0:
        utils.set_dbus_volume(cfg.active_volume, cfg.mac_dbus)
        await asyncio.sleep(1.0)

    # 4. Запускаем бесконечный поток радио в фоновом режиме (не блокирует FastAPI и очередь)
    try:
        utils.play_stream(cfg.mac_raw, STREAM_URL)
    except Exception as e:
        print(f"[Radio] Ошибка фонового запуска потока: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось запустить аудиопоток радио."
        )

    return {"status": "success", "plugin": "radio", "message": "ok"}

