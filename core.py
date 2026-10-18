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
    payload: str          # Текст или имя MP3-файла

class CoreEngine:
    def __init__(self, max_queue_size: int = 20):
        self._queue = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task = None
        self._piper_proc = None  # Ссылка на долгоживущий процесс Piper

    async def start(self):
        """Запуск фонового обработчика очереди и инициализация Piper."""
        if self._worker_task is not None:
            return

        # Запускаем Piper один раз при старте ядра
        try:
            piper_cmd = [
                config_manager.piper_binary, 
                "--model", config_manager.model_path, 
                "--output_file", "-"
            ]
            # Задаем переменные окружения для оптимизации потоков ONNX
            env = os.environ.copy()
            env["OMP_NUM_THREADS"] = "2"
            env["ONNXRUNTIME_INTRA_OP_NUM_THREADS"] = "2"

            # Запускаем долгоживущий процесс
            self._piper_proc = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env
            )
            print("[Core] Долгоживущий процесс Piper успешно инициализирован в ОЗУ.")
        except Exception as e:
            print(f"[Core] Критическая ошибка запуска Piper: {e}")
            return

        self._worker_task = asyncio.create_task(self._worker_loop())
        print("[Core] Фоновое ядро очереди запущено.")

    def stop(self):
        """Мягкое завершение процесса Piper и фонового воркера."""
        print("[Core] Останавливаем фоновое ядро...")
        
        # 1. Отменяем асинхронный воркер очереди
        if self._worker_task:
            self._worker_task.cancel()

        # 2. Корректно завершаем процесс Piper
        if self._piper_proc:
            try:
                print("[Core] Закрываем пайпы и завершаем процесс Piper...")
                # Закрываем потоки ввода-вывода, чтобы Piper понял, что пора выходить
                if self._piper_proc.stdin:
                    self._piper_proc.stdin.close()
                if self._piper_proc.stdout:
                    self._piper_proc.stdout.close()
                
                # Посылаем сигнал SIGTERM (мягкое завершение)
                self._piper_proc.terminate()
                
                # Ждем завершения в течение 2 секунд
                self._piper_proc.wait(timeout=2.0)
                print("[Core] Процесс Piper успешно завершен.")
            except subprocess.TimeoutExpired:
                # Если процесс завис и не вышел по-хорошему, убиваем его жестко (SIGKILL)
                print("[Core] Внимание: Piper не завершился вовремя. Принудительное уничтожение (SIGKILL)...")
                self._piper_proc.kill()
                self._piper_proc.wait()
            except Exception as e:
                print(f"[Core] Ошибка при остановке Piper: {e}")
            finally:
                self._piper_proc = None


    async def _worker_loop(self):
        while True:
            task: AudioTask = await self._queue.get()
            try:
                cfg: SpeakerConfig = config_manager.get_speaker(task.speaker_name)
                if not cfg:
                    print(f"[Core] Ошибка: Колонка '{task.speaker_name}' не найдена.")
                    continue

                print(f"[Core] Обработка задачи [{task.task_type}] для колонки '{task.speaker_name}'")
                manage_volume = cfg.active_volume > 0 and cfg.default_volume > 0
                audio_bytes_data = None

                # 2. Мгновенная генерация из уже загруженной модели
                if task.task_type == "tts":
                    def generate_via_persistent_piper():
                        # Проверяем, живой ли процесс
                        if self._piper_proc.poll() is not None:
                            print("[Core] Перезапуск упавшего процесса Piper...")
                            self._piper_proc = subprocess.Popen(
                                [config_manager.piper_binary, "--model", config_manager.model_path, "--output_file", "-"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                            )

                        # Очищаем текст от переносов и обязательно добавляем ОДИН '\n' в конце.
                        # Символ '\n' сигнализирует Piper, что блок текста завершен и нужно начать синтез.
                        clean_text = task.payload.replace("\n", " ").strip() + "\n"
                        
                        # Пишем в stdin живого процесса
                        self._piper_proc.stdin.write(clean_text.encode('utf-8'))
                        self._piper_proc.stdin.flush()

                        # Читаем сырые WAV-байты. 
                        # ВАЖНО: communicate() использовать нельзя, так как он закроет процесс.
                        # Используем чтение заголовка и данных. Для стандартного Piper (22050Hz, 16bit, mono):
                        # Читаем первые 44 байта (WAV Header), чтобы узнать размер данных, либо читаем до конца фрейма.
                        # Но так как Piper выдает ровно один WAV файл на строку, мы можем прочитать данные,
                        # зная, что Piper завершает вывод определенным образом, либо считывая структуру чанков.
                        # Упрощенный стабильный вариант для Piper: он отдает весь WAV-контейнер целиком для одной строки.
                        # Чтобы не заблокироваться на read(), надежнее использовать обертку или читать заголовок:
                        
                        header = self._piper_proc.stdout.read(44)
                        if not header:
                            return None
                        
                        # Извлекаем размер данных из WAV заголовка (байты 40-44)
                        data_size = int.from_bytes(header[40:44], byteorder='little')
                        
                        # Дочитываем оставшиеся аудио-байты
                        wav_data = self._piper_proc.stdout.read(data_size)
                        return header + wav_data

                    audio_bytes_data = await asyncio.to_thread(generate_via_persistent_piper)

                    if not audio_bytes_data:
                        print("[Core] Ошибка: Не удалось получить поток от Piper.")
                        continue

                elif task.task_type == "file":
                    target_file_path = os.path.join(config_manager.mp3_dir, f"{task.payload}.mp3")
                    if not os.path.exists(target_file_path):
                        continue
                    audio_bytes_data = await asyncio.to_thread(lambda: open(target_file_path, "rb").read())

                # 3. Подключение к Bluetooth
                connected = await asyncio.to_thread(utils.manage_bluetooth, "connect", cfg.mac_raw)
                if not connected:
                    continue

                # Оптимизированная пауза для Allwinner (снизили до 1.2 сек)
                await asyncio.sleep(1.2)

                # 4. Управление громкостью (снизили паузу до 0.15 сек)
                if manage_volume:
                    await asyncio.to_thread(utils.set_dbus_volume, cfg.active_volume, cfg.mac_dbus)
                    await asyncio.sleep(0.15)

                # 5. Воспроизведение звука из ОЗУ через проверенный aplay / mpg123
                try:
                    def stream_audio_to_speaker():
                        if task.task_type == "tts":
                            play_cmd = ["aplay", "-D", f"bluealsa:DEV={cfg.mac_raw},PROFILE=a2dp", "-"]
                        else:
                            play_cmd = ["mpg123", "-o", "alsa", "-a", f"bluealsa:DEV={cfg.mac_raw},PROFILE=a2dp", "-"]
                        
                        proc = subprocess.Popen(play_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        proc.communicate(input=audio_bytes_data)

                    await asyncio.to_thread(stream_audio_to_speaker)
                except Exception as e:
                    print(f"[Core] Ошибка воспроизведения: {e}")
                finally:
                    if manage_volume:
                        await asyncio.to_thread(utils.set_dbus_volume, cfg.default_volume, cfg.mac_dbus)
                        await asyncio.sleep(0.15)
                    await asyncio.to_thread(utils.manage_bluetooth, "disconnect", cfg.mac_raw)
                    audio_bytes_data = None

            except Exception as e:
                print(f"[Core] Ошибка в цикле: {e}")
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

core_engine = CoreEngine(max_queue_size=20)

