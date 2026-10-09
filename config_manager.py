# /opt/bt-player/config_manager.py
import os
import configparser
from dataclasses import dataclass

@dataclass
class SpeakerConfig:
    name: str
    mac_raw: str
    mac_dbus: str
    active_volume: int
    default_volume: int

class ConfigManager:
    def __init__(self, config_path: str = "speakers.conf"):
        self.config_path = config_path
        self.speakers = {}
        # Настройки по умолчанию на случай, если секция SETTINGS пуста
        self.mp3_dir = "/opt/bt-player/mp3"
        self.model_path = "/opt/bt-player/models/voice.onnx"

    def load_config(self):
        """Парсит секции SETTINGS и SPEAKERS из файла конфигурации."""
        if not os.path.exists(self.config_path):
            print(f"[Config] КРИТИЧЕСКАЯ ОШИБКА: Файл {self.config_path} не найден!")
            return

        print(f"[Config] Чтение конфигурации из {self.config_path}...")
        config = configparser.ConfigParser()
        config.read(self.config_path, encoding="utf-8")

        # 1. Читаем общие настройки программы
        if "SETTINGS" in config:
            self.mp3_dir = config["SETTINGS"].get("mp3_dir", self.mp3_dir).strip()
            self.model_path = config["SETTINGS"].get("model_path", self.model_path).strip()
            print(f"[Config] Настройки: MP3_DIR={self.mp3_dir}, MODEL_PATH={self.model_path}")

        # 2. Читаем настройки колонок
        self.speakers.clear()
        if "SPEAKERS" in config:
            for name, value in config["SPEAKERS"].items():
                try:
                    # Разделяем параметры колонки по запятой
                    mac_raw, active_vol, default_vol = value.split(",")
                    mac_raw = mac_raw.strip()
                    
                    # Генерируем мак для D-Bus (заменяем : на _)
                    mac_dbus = mac_raw.replace(":", "_")
                    
                    active_volume = int(active_vol.strip())
                    default_volume = int(default_vol.strip())

                    self.speakers[name] = SpeakerConfig(
                        name=name,
                        mac_raw=mac_raw,
                        mac_dbus=mac_dbus,
                        active_volume=active_volume,
                        default_volume=default_volume
                    )
                    print(f"[Config] Колонка '{name}': RAW={mac_raw}, Vol={active_volume}/{default_volume}")
                except Exception as e:
                    print(f"[Config] Ошибка парсинга колонки '{name}': {e}")

    def get_speaker(self, name: str) -> SpeakerConfig:
        """Возвращает конфигурацию конкретной колонки."""
        return self.speakers.get(name)

# Экспортируем глобальный синглтон-менеджер
config_manager = ConfigManager()

