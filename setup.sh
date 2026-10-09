#!/bin/bash

# Скрипт автоматического развертывания окружения для FastAPI Bluetooth Audio Player

# Выход при любой ошибке
set -e

PROJECT_DIR="/opt/bt-player"
VENV_DIR="$PROJECT_DIR/venv"

echo "================================================================="
echo "[Setup] Начало развертывания окружения аудио-хаба..."
echo "================================================================="

# 1. Проверка прав root
if [ "$EUID" -ne 0 ]; then
  echo "[Error] Пожалуйста, запустите этот скрипт от имени root (через sudo)."
  exit 1
fi

# 2. Создание каталога проекта (исправлен порядок логики)
echo "[Files] Создание директории проекта..."
mkdir -p "$PROJECT_DIR"

# 3. Обновление репозиториев и установка системных утилит
echo "[System] Обновление пакетов apt и установка зависимостей Linux..."
apt-get update

# build-essential и python3-dev необходимы на ARM64 для сборки некоторых ИИ-зависимостей
apt-get install -y \
    build-essential \
    python3-dev \
    python3-venv \
    python3-pip \
    mpg123 \
    alsa-utils \
    lame \
    wget

echo "[System] Системные утилиты Linux успешно установлены."

# 4. Переход в каталог проекта
cd "$PROJECT_DIR"

# 5. Создание или обновление виртуального окружения Python
if [ -d "$VENV_DIR" ]; then
    echo "[Venv] Обнаружено существующее виртуальное окружение. Обновление..."
else
    echo "[Venv] Создание нового виртуального окружения по пути $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# 6. Активация venv и установка Python библиотек
echo "[Python] Активация venv и обновление пакетного менеджера pip..."
source "$VENV_DIR/bin/activate"

pip install --upgrade pip

echo "[Python] Установка библиотек FastAPI, Uvicorn, Pydantic и Piper TTS..."
# На ARM64 установка piper-tts может занять пару минут из-за компиляции onnxruntime
pip install fastapi uvicorn pydantic piper-tts

echo "[Python] Все Python-пакеты успешно установлены в виртуальное окружение."

# 7. Проверка и создание необходимых каталогов данных
echo "[Files] Настройка структуры папок проекта..."
mkdir -p "$PROJECT_DIR/mp3"
mkdir -p "$PROJECT_DIR/models"
mkdir -p "$PROJECT_DIR/endpoints"

# Проверяем, на месте ли модель голоса Ирины
if [ ! -f "$PROJECT_DIR/models/voice.onnx" ]; then
    echo "[Files] Модель voice.onnx не обнаружена. Скачивание модели Ирина (medium)..."
    wget -O "$PROJECT_DIR/models/voice.onnx" https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx
    wget -O "$PROJECT_DIR/models/voice.onnx.json" https://huggingface.co/rhasspy/piper-voices/raw/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json
    echo "[Files] Модель и её конфигурационный файл успешно скачаны."
else
    echo "[Files] Файлы голосовой модели уже присутствуют в каталоге models/."
fi

# Безопасное копирование сервиса (проверяем наличие файла перед копированием)
if [ -f "bt-player.service" ]; then
    cp bt-player.service /etc/systemd/system/
elif [ ! -f "/etc/systemd/system/bt-player.service" ]; then
    echo "[Warning] Файл bt-player.service не найден в текущей директории и не установлен в систему."
fi

# 8. Завершение и перезапуск службы
echo "================================================================="
echo "[Success] Развертывание среды завершено!"
echo "================================================================="
echo "[System] Перезапуск службы bt-player.service..."

if [ -f "/etc/systemd/system/bt-player.service" ]; then
    systemctl daemon-reload
    systemctl enable bt-player.service || true
    systemctl restart bt-player.service
    echo "[System] Служба успешно перезапущена."
else
    echo "[Warning] Файл bt-player.service не зарегистрирован в systemd."
    echo "Пожалуйста, скопируйте файл сервиса в /etc/systemd/system/ и запустите вручную."
fi

echo "Скрипт завершил работу. Проверить статус логов: sudo journalctl -u bt-player.service -f"

