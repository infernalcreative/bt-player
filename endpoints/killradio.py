# /opt/bt-player/endpoints/killradio.py
from fastapi import APIRouter
from config_manager import config_manager
import utils

# Префикс /radio оставляем, роут будет: POST /radio/kill
router = APIRouter(prefix="/radio", tags=["Radio Killer Plugin"])

# Оперируем только именем колонки из speakers.conf
SPEAKER_NAME = "mini"

@router.post("/kill")
async def kill_radio():
    # 1. Принудительно останавливаем любой поток воспроизведения mpg123
    utils.stop_all_mpg123()

    # 2. Получаем актуальные параметры колонки из центрального конфига
    cfg = config_manager.get_speaker(SPEAKER_NAME)
    
    if cfg:
        # 3. Возвращаем базовую громкость, прописанную в speakers.conf (для mini это 45)
        try:
            utils.set_dbus_volume(cfg.default_volume, cfg.mac_dbus)
        except Exception:
            pass  # Игнорируем, если транспорт D-Bus недоступен

        # 4. Отключаем Bluetooth-колонку
        try:
            utils.manage_bluetooth("disconnect", cfg.mac_raw)
        except Exception as e:
            print(f"[Radio] Ошибка при отключении колонки {SPEAKER_NAME}: {e}")

    return {"status": "success", "plugin": "radio", "message": "stopped"}

