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
        """Запуск фонового обработчика очереди."""
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
                
                # Переменная в ОЗУ для хранения финального MP3-потока
                audio_bytes_data = None

                # 2. Подготовка аудиоресурса ПОЛНОСТЬЮ В ОЗУ
                if task.task_type == "tts":
                    def generate_in_ram_tts():
                        nonlocal audio_bytes_data
                        try:
                            # Шаг А: Запускаем Piper. Дефис "-" принуждает его писать WAV в stdout
                            piper_cmd = [config_manager.piper_binary, "--model", config_manager.model_path, "--output_file", "-"]
                            piper_proc = subprocess.Popen(piper_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                            
                            # Передаем текст в Piper на stdin и забираем WAV-байты из stdout в ОЗУ
                            wav_bytes, _ = piper_proc.communicate(input=task.payload.encode('utf-8'))

                            if not wav_bytes:
                                return

                            # Шаг Б: Запускаем Lame. Первым дефисом указываем stdin, вторым — вывод MP3 в stdout
                            lame_cmd = ["lame", "--silent", "-", "-"]
                            lame_proc = subprocess.Popen(lame_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                            
                            # Передаем WAV-байты в Lame и получаем MP3-поток в оперативную память
                            audio_bytes_data, _ = lame_proc.communicate(input=wav_bytes)
                        except Exception as ex:
                            print(f"[Core] Ошибка конвейера Piper/Lame в ОЗУ: {ex}")

                    await asyncio.to_thread(generate_in_ram_tts)

                    if not audio_bytes_data or len(audio_bytes_data) == 0:
                        print("[Core] Ошибка: Не удалось сгенерировать MP3 поток в ОЗУ. Пропуск.")
                        continue

                elif task.task_type == "file":
                    target_file_path = os.path.join(config_manager.mp3_dir, f"{task.payload}.mp3")
                    if not os.path.exists(target_file_path):
                        print(f"[Core] Ошибка: Файл '{target_file_path}' отсутствует на диске. Пропуск.")
                        continue
                    
                    # Читаем существующий MP3 файл напрямую в оперативную память
                    def read_file_to_ram():
                        with open(target_file_path, "rb") as f:
                            return f.read()
                    audio_bytes_data = await asyncio.to_thread(read_file_to_ram)

                # 3. Подключение к Bluetooth
                connected = await asyncio.to_thread(utils.manage_bluetooth, "connect", cfg.mac_raw)
                if not connected:
                    print(f"[Core] Пропуск задачи: Не удалось подключиться к {cfg.mac_raw}")
                    continue

                # Даем Bluetooth-чипу Allwinner время зарегистрировать аудио-транспорт в системе
                await asyncio.sleep(2.0)

                # 4. Управление громкостью ДО воспроизведения
                if manage_volume:
                    await asyncio.to_thread(utils.set_dbus_volume, cfg.active_volume, cfg.mac_dbus)
                    await asyncio.sleep(0.5)
                else:
                    print(f"[Core] Громкость в конфиге 0. Воспроизведение на текущих настройках устройства.")

                # 5. Воспроизведение звука из ОЗУ через конвейер mpg123 с вашими флагами стабильности
                try:
                    def stream_audio_to_speaker():
                        # Сохраняем ваши флаги "-o alsa" и профиль A2DP, заменяя файл на дефис "-" (stdin)
                        play_cmd = [
                            "mpg123", 
                            "-o", "alsa",  
                            "-a", f"bluealsa:DEV={cfg.mac_raw},PROFILE=a2dp",
                            "-"
                        ]
                        print(f"[Core] Запуск mpg123 для воспроизведения потока из ОЗУ...")
                        proc = subprocess.Popen(play_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        
                        # Вкачиваем MP3-байты из ОЗУ прямо в поток воспроизведения
                        _, stderr_data = proc.communicate(input=audio_bytes_data)
                        
                        if proc.returncode != 0:
                            error_msg = stderr_data.decode().strip() if stderr_data else "Неизвестная ошибка"
                            print(f"[Core] Ошибка mpg123 при воспроизведении из ОЗУ: {error_msg}")

                    await asyncio.to_thread(stream_audio_to_speaker)
                except Exception as e:
                    print(f"[Core] Ошибка при проигрывании из ОЗУ: {e}")
                finally:
                    # 6. Финальный блок: возврат громкости по умолчанию и отключение колонки
                    if manage_volume:
                        await asyncio.to_thread(utils.set_dbus_volume, cfg.default_volume, cfg.mac_dbus)
                        await asyncio.sleep(0.5)
                    
                    await asyncio.to_thread(utils.manage_bluetooth, "disconnect", cfg.mac_raw)
                    
                    # Явно освобождаем занятую память для сборщика мусора Python
                    audio_bytes_data = None
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

