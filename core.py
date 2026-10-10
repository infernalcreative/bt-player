import asyncio
import os
import subprocess
from dataclasses import dataclass
from config_manager import config_manager, SpeakerConfig
import utils

@dataclass
class AudioTask:
    task_type: str        # "tts" или "file"
    speaker_name: str     # "mini", "neo" и т.д.
    payload: str          # Текст для TTS или имя MP3-файла (без пути и расширения)

class CoreEngine:
    def __init__(self, max_queue_size: int = 20):
        self._queue = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task = None

    async def start(self):
        """Запуск фонового обработчика."""
        if self._worker_task is not None:
            return
        self._worker_task = asyncio.create_task(self._worker_loop())
        print("[Core] Фоновое ядро очереди запущено.")

    async def _worker_loop(self):
        while True:
            task: AudioTask = await self._queue.get()
            try:
                # 1. Получаем конфигурацию колонки
                cfg: SpeakerConfig = config_manager.get_speaker(task.speaker_name)
                if not cfg:
                    print(f"[Core] Ошибка: Колонка '{task.speaker_name}' не найдена в speakers.conf")
                    continue

                print(f"[Core] Обработка задачи [{task.task_type}] для колонки '{task.speaker_name}'")
                manage_volume = cfg.active_volume > 0 and cfg.default_volume > 0
                target_file_path = None

                # 2. Подготовка аудиоресурса (сборка путей в /tmp или mp3_dir)
                if task.task_type == "tts":
                    timestamp = asyncio.get_event_loop().time()
                    temp_wav = f"/tmp/tts_{timestamp}.wav"
                    target_file_path = f"/tmp/tts_{timestamp}.mp3"

                    # Генерация через системный CLI Piper + конвертация Lame (Ваша изначальная логика)
                    def generate_cli_tts():
                        # ПУТЬ ТЕПЕРЬ БЕРЕТСЯ ИЗ config_manager.piper_binary
                        cmd = [config_manager.piper_binary, "--model", config_manager.model_path, "--output_file", temp_wav]
                        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        proc.communicate(input=task.payload.encode('utf-8'))
                        
                        # Кодируем полученный WAV в рабочий MP3 через lame
                        if os.path.exists(temp_wav):
                            subprocess.run(["lame", "--silent", temp_wav, target_file_path], check=False)
                            try:
                                os.remove(temp_wav)  # Сразу удаляем WAV из памяти/диска
                            except:
                                pass

                    await asyncio.to_thread(generate_cli_tts)

                    # Проверяем, создался ли MP3 файл
                    if not os.path.exists(target_file_path) or os.path.getsize(target_file_path) == 0:
                        print("[Core] Ошибка: Не удалось сгенерировать MP3 файл через Piper/Lame. Пропуск.")
                        continue

                elif task.task_type == "file":
                    target_file_path = os.path.join(config_manager.mp3_dir, f"{task.payload}.mp3")
                    if not os.path.exists(target_file_path):
                        print(f"[Core] Ошибка: Файл '{target_file_path}' отсутствует на диске. Пропуск.")
                        continue

                # 3. Подключение к Bluetooth
                connected = await asyncio.to_thread(utils.manage_bluetooth, "connect", cfg.mac_raw)
                if not connected:
                    print(f"[Core] Пропуск задачи: Не удалось подключиться к {cfg.mac_raw}")
                    if task.task_type == "tts" and os.path.exists(target_file_path):
                        try: os.remove(target_file_path)
                        except: pass
                    continue

                # Даем Bluetooth-чипу время зарегистрировать аудио-транспорт в системе
                await asyncio.sleep(2.0)

                # 4. Управление громкостью ДО воспроизведения
                if manage_volume:
                    await asyncio.to_thread(utils.set_dbus_volume, cfg.active_volume, cfg.mac_dbus)
                    await asyncio.sleep(0.5)
                else:
                    print(f"[Core] Громкость в конфиге 0. Воспроизведение на текущих настройках устройства.")

                # 5. Воспроизведение звука через mpg123
                try:
                    await asyncio.to_thread(utils.play_audio, cfg.mac_raw, target_file_path)
                except Exception as e:
                    print(f"[Core] Ошибка при проигрывании: {e}")
                finally:
                    # 6. Финальный блок: возврат громкости, отключение и очистка
                    if manage_volume:
                        await asyncio.to_thread(utils.set_dbus_volume, cfg.default_volume, cfg.mac_dbus)
                        await asyncio.sleep(0.5)
                    
                    await asyncio.to_thread(utils.manage_bluetooth, "disconnect", cfg.mac_raw)
                    
                    # Удаляем временный MP3 из папки /tmp
                    if task.task_type == "tts" and os.path.exists(target_file_path):
                        try:
                            os.remove(target_file_path)
                        except:
                            pass
                    print(f"[Core] Сессия воспроизведения для '{task.speaker_name}' успешно закрыта.")

            except Exception as e:
                print(f"[Core] Критическая ошибка в цикле воркера: {e}")
            finally:
                self._queue.task_done()

    def add_task(self, task_type: str, speaker_name: str, payload: str) -> bool:
        if not config_manager.get_speaker(speaker_name):
            return False
        try:
            task = AudioTask(task_type=task_type, speaker_name=speaker_name, payload=payload)
            self._queue.put_nowait(task)
            return True
        except asyncio.QueueFull:
            return False

# Инициализируем синглтон ядра
core_engine = CoreEngine(max_queue_size=20)

