# /opt/bt-player/main.py
import os
import importlib
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Импортируем синглтоны конфигурации и ядра
from config_manager import config_manager
from core import core_engine

def load_dynamic_endpoints(app_instance: FastAPI):
    """Сканирует папку endpoints и динамически подключает роутеры плагинов."""
    endpoints_dir = os.path.join(os.path.dirname(__file__), "endpoints")
    if not os.path.exists(endpoints_dir):
        os.makedirs(endpoints_dir)

    for file in os.listdir(endpoints_dir):
        if file.endswith(".py") and file != "__init__.py":
            module_name = f"endpoints.{file[:-3]}"
            try:
                module = importlib.import_module(module_name)
                # Подключаем роутер, если он объявлен в файле-плагине
                if hasattr(module, "router"):
                    app_instance.include_router(module.router)
                    print(f"[Engine] Успешно загружен плагин: {module_name}")
            except Exception as e:
                print(f"[Engine] Ошибка при загрузке плагина {module_name}: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Engine] Старт инициализации приложения...")
    
    # 1. Загружаем карту колонок из конфигурационного файла
    config_manager.load_config()
    
    # 2. Запускаем фоновый воркер обработки очереди звука
    await core_engine.start()
    
    # 3. Динамически загружаем плагины СТРОГО внутри lifespan активного процесса
    # Это предотвращает двойной импорт при использовании uvicorn reload=True
    load_dynamic_endpoints(app)
    
    yield
    print("[Engine] Остановка приложения. Освобождение ресурсов...")

# Создаем приложение FastAPI с поддержкой lifespan
app = FastAPI(title="Plugin-Based Smart Notifier", lifespan=lifespan)

if __name__ == "__main__":
    import uvicorn
    # reload=True безопасно отслеживает изменения в папке endpoints/
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

