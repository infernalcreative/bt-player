# /opt/bt-player/utils.py
import subprocess
import time

def get_connected_devices() -> list:
    """Возвращает список MAC-адресов всех реально подключенных в данный момент устройств через bluetoothctl."""
    try:
        # Получаем список всех известных устройств
        cmd_list = ["bluetoothctl", "devices"]
        result = subprocess.run(cmd_list, capture_output=True, text=True, timeout=5)
        
        if result.returncode != 0 or not result.stdout:
            return []
            
        connected_macs = []
        # Вывод имеет вид: "Device 00:22:6D:F3:FD:38 VK Capsula Neo-B583"
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "Device":
                mac = parts[1]
                
                # Перепроверяем реальный статус через info, чтобы исключить отключенные устройства
                cmd_info = ["bluetoothctl", "info", mac]
                info_result = subprocess.run(cmd_info, capture_output=True, text=True, timeout=3)
                
                if "Connected: yes" in info_result.stdout:
                    connected_macs.append(mac)
                    
        return connected_macs
    except Exception as e:
        print(f"[Utils] Ошибка при проверке активных подключений через bluetoothctl: {e}")
        return []


def get_active_fd_path(mac_dbus: str, retries: int = 7, delay: float = 1.0) -> str:
    """Динамически ищет fdX путь для конкретного MAC-адреса."""
    cmd = f"busctl tree org.bluez | grep -o '/org/bluez/hci0/dev_{mac_dbus}/sep1/fd[0-9]*'"

    for attempt in range(retries):
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                fd_path = result.stdout.strip()
                if fd_path:
                    return fd_path
        except:
            pass
        time.sleep(delay)

    print(f"[Utils] ОШИБКА: Точка D-Bus для {mac_dbus} не найдена за {retries} сек.")
    return ""


def manage_bluetooth(action: str, mac_raw: str) -> bool:
    """Подключает/отключает конкретный MAC через bluetoothctl, предварительно отключая другие активные устройства."""
    if action not in ["connect", "disconnect"]:
        return False
        
    try:
        # Если запрашивается подключение, сначала проверяем и гасим другие активные соединения
        if action == "connect":
            active_devices = get_connected_devices()
            # Исключаем текущий MAC из списка на отключение (если он вдруг уже подключен)
            devices_to_disconnect = [mac for mac in active_devices if mac.lower() != mac_raw.lower()]
            
            if devices_to_disconnect:
                print(f"[Utils] Найдено активных подключений: {len(devices_to_disconnect)}. Отключаем их...")
                for old_mac in devices_to_disconnect:
                    print(f"[Utils] Принудительное отключение устройства {old_mac} перед новым соединением...")
                    subprocess.run(
                        ["bluetoothctl", "disconnect", old_mac],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=7,
                        check=False,
                    )
                time.sleep(1.5) # Пауза, чтобы стек BlueZ и чип успели полностью разорвать старые сессии

        print(f"[Utils] Выполнение bluetoothctl {action} для {mac_raw}...")
        subprocess.run(
            ["bluetoothctl", action, mac_raw],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
        time.sleep(1.0)  # Пауза стабилизации чипа связи
        return True
    except Exception as e:
        print(f"[Utils] Ошибка при выполнении manage_bluetooth ({action}) для {mac_raw}: {e}")
        return False


def set_dbus_volume(volume_value: int, mac_dbus: str) -> bool:
    """Меняет громкость конкретного устройства через его транспорт в D-Bus."""
    fd_path = get_active_fd_path(mac_dbus=mac_dbus)
    if not fd_path:
        return False

    cmd = [
        "busctl", "set-property", "org.bluez",
        fd_path, "org.bluez.MediaTransport1",
        "Volume", "q", str(volume_value),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[Utils] Громкость для {mac_dbus} успешно изменена на {volume_value}")
        return True
    except:
        return False


def play_audio(mac_raw: str, audio_file_path: str) -> bool:
    """Проигрывает MP3 файл через mpg123 с принудительным выводом на драйвер ALSA."""
    play_cmd = [
        "mpg123", 
        "-o", "alsa",  # Запрещает плееру падать в Segmentation fault
    	"-b", "1024", # Буфер
        "-a", f"bluealsa:DEV={mac_raw},PROFILE=a2dp",
        audio_file_path,
    ]
    try:
        print(f"[Utils] Запуск mpg123 для файла {audio_file_path}...")
        subprocess.run(play_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode().strip() if e.stderr else str(e)
        print(f"[Utils] Ошибка mpg123 при игре {audio_file_path}: {error_msg}")
        return False


def stop_all_mpg123():
    """Принудительно гасит фоновое радио или плеер."""
    subprocess.run(["pkill", "-9", "mpg123"], check=False)


def play_stream(mac_raw: str, audio_file_path: str):
    """Запускает проигрывание радио/потока через mpg123 в фоновом режиме (асинхронно / не блокирует FastAPI)"""
    # Гасим предыдущие процессы mpg123 перед запуском радио
    subprocess.run(["pkill", "-9", "mpg123"], check=False)

    play_cmd = [
        "mpg123",
        "-a",
        f"bluealsa:DEV={mac_raw},PROFILE=a2dp",
        audio_file_path,
    ]
    try:
        print(
            f"[Utils] Фоновый запуск потока {audio_file_path} через BlueALSA..."
        )
        subprocess.Popen(
            play_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        print(f"[Utils] Ошибка фонового запуска mpg123: {e}")
        # Заметка: Убедитесь, что HTTPException импортирован из fastapi в начале вашего основного приложения,
        # либо добавьте 'from fastapi import HTTPException' здесь, если этот метод вызывается напрямую.
        raise NameError(f"Ошибка при фоновом запуске {audio_file_path}. Подробности: {e}")

