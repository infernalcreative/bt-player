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
                "--output_raw"
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
                # 1. Получаем конфигурацию колонки
                cfg: SpeakerConfig = config_manager.get_speaker(task.speaker_name)
                if not cfg:
                    print(f"[Core] Ошибка: Колонка '{task.speaker_name}' не найдена в speakers.conf")
                    continue

                print(f"[Core] Обработка задачи [{task.task_type}] для колонки '{task.speaker_name}'")
                manage_volume = cfg.active_volume > 0 and cfg.default_volume > 0

                # ВАЖНО: Если процесс Piper упал, перезапускаем его СТРОГО с флагом --output-raw
                if task.task_type == "tts" and (not self._piper_proc or self._piper_proc.poll() is not None):
                    print("[Core] Перезапуск или инициализация процесса Piper в режиме RAW...")
                    piper_cmd = [
                        config_manager.piper_binary, 
                        "--model", config_manager.model_path, 
                        "--output-raw"  # <--- Ключевое изменение: гоним чистый PCM 16-bit mono 22050Hz
                    ]
                    env = os.environ.copy()
                    env["OMP_NUM_THREADS"] = "2"
                    env["ONNXRUNTIME_INTRA_OP_NUM_THREADS"] = "2"
                    
                    self._piper_proc = subprocess.Popen(
                        piper_cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        env=env
                    )

                # 3. Подключение к Bluetooth ДО начала генерации звука
                connected = await asyncio.to_thread(utils.manage_bluetooth, "connect", cfg.mac_raw)
                if not connected:
                    print(f"[Core] Пропуск задачи: Не удалось подключиться к {cfg.mac_raw}")
                    continue

                # Даем Bluetooth-чипу Allwinner время зарегистрировать аудио-транспорт
                await asyncio.sleep(1.2)

                # 4. Управление громкостью ДО воспроизведения
                if manage_volume:
                    await asyncio.to_thread(utils.set_dbus_volume, cfg.active_volume, cfg.mac_dbus)
                    await asyncio.sleep(0.15)

                # 5. Воспроизведение звука
                try:
                    if task.task_type == "tts":
                        def stream_tts_direct_to_aplay():
                            print(f"[Core] Стриминг TTS напрямую из Piper в aplay...")
                            # Настраиваем aplay на воспроизведение RAW PCM потока (16 бит, Little Endian, Моно, 22050 Гц)
                            play_cmd = [
                                "aplay", 
                                "-D", f"bluealsa:DEV={cfg.mac_raw},PROFILE=a2dp",
                                "-t", "raw",
                                "-f", "S16_LE",
                                "-r", "22050",
                                "-c", "1"
                            ]
                            
                            # Запускаем плеер, его stdin будет принимать данные
                            aplay_proc = subprocess.Popen(play_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                            
                            # Готовим и отправляем текст в Piper
                            clean_text = task.payload.replace("\n", " ").strip() + "\n"
                            self._piper_proc.stdin.write(clean_text.encode('utf-8'))
                            self._piper_proc.stdin.flush()
                            
                            # Читаем данные из Piper и тут же перенаправляем их в aplay
                            # Метод read1() или итерация по небольшим блокам решает проблему буферизации
                            while True:
                                # Читаем чанк данных из Piper (до 4096 байт за раз)
                                chunk = self._piper_proc.stdout.read1(4096)
                                if not chunk:
                                    break
                                
                                # Отправляем этот чанк в плеер
                                aplay_proc.stdin.write(chunk)
                                aplay_proc.stdin.flush()
                                
                                # Хак для Piper: если буфер пуст, значит фраза полностью сгенерирована и отдана
                                if len(chunk) < 4096:
                                    break

                            # Закрываем пайп плеера, чтобы он корректно завершил работу
                            if aplay_proc.stdin:
                                aplay_proc.stdin.close()
                            aplay_proc.wait()

                        await asyncio.to_thread(stream_tts_direct_to_aplay)

                    elif task.task_type == "file":
                        # Воспроизведение старых MP3 файлов (оставляем чтение в ОЗУ для mpg123)
                        target_file_path = os.path.join(config_manager.mp3_dir, f"{task.payload}.mp3")
                        if os.path.exists(target_file_path):
                            with open(target_file_path, "rb") as f:
                                audio_bytes_data = f.read()

                            def stream_mp3_to_speaker():
                                print(f"[Core] Запуск mpg123 для воспроизведения MP3 файла из ОЗУ...")
                                play_cmd = ["mpg123", "-o", "alsa", "-a", f"bluealsa:DEV={cfg.mac_raw},PROFILE=a2dp", "-"]
                                proc = subprocess.Popen(play_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                                proc.communicate(input=audio_bytes_data)

                            await asyncio.to_thread(stream_mp3_to_speaker)
                        else:
                            print(f"[Core] Ошибка: Файл '{target_file_path}' отсутствует.")

                except Exception as e:
                    print(f"[Core] Ошибка при проигрывании: {e}")
                finally:
                    # 6. Финальный блок: возврат громкости и отключение колонки
                    if manage_volume:
                        await asyncio.to_thread(utils.set_dbus_volume, cfg.default_volume, cfg.mac_dbus)
                        await asyncio.sleep(0.15)
                    
                    await asyncio.to_thread(utils.manage_bluetooth, "disconnect", cfg.mac_raw)
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

core_engine = CoreEngine(max_queue_size=20)

