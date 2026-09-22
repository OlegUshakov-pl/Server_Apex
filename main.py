import asyncio
import json
import os
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Папка для хранения слепков
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Модель данных веб-страницы
class WebSnapData(BaseModel):
    source_url: str       # URL страницы (http://...)
    thumbnail_base64: str # Фото в формате Base64
    binary_data: str      # Бинарные данные
    metadata_ai: dict     # Метаданные от AI

# Модель данных локальной папки
class FolderSnapData(BaseModel):
    source_url: str       # Путь к папке (file://...)
    thumbnail_base64: str = ""  # Обычно пусто для папок
    binary_data: str      # Бинарные данные (hash пути)
    metadata_ai: dict     # Метаданные от AI (список файлов)

# Путь: http://localhost:8000/api/add-snap (веб-страницы)
@app.post("/api/add-snap")
async def add_snap(snap: WebSnapData):
    """Сохраняет слепок веб-страницы"""
    try:
        # 1. Создаем уникальное имя файла (UUID)
        file_id = str(uuid.uuid4())

        # 2. Формируем структуру данных для сохранения
        snap_content = {
            "id": file_id,
            "type": "web",
            "url": snap.source_url,
            "thumbnail": snap.thumbnail_base64,
            "binary_data": snap.binary_data,
            "metadata": snap.metadata_ai
        }

        # 3. Сохраняем файл в папку uploads
        filename = f"{file_id}.json"
        filepath = os.path.join(UPLOAD_DIR, filename)

        await asyncio.to_thread(
            lambda f=filepath, d=snap_content: (
                open(f, "w", encoding="utf-8").write(json.dumps(d, indent=4))
            )
        )

        # 4. Возвращаем ответ расши-extension
        return {
            "status": "success",
            "snap_id": file_id,
            "message": "Веб-слепок успешно сохранен на сервере."
        }

    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")

# Путь: http://localhost:8000/api/add-folder-snap (локальные папки)
@app.post("/api/add-folder-snap")
async def add_folder_snap(snap: FolderSnapData):
    """Сохраняет слепок локальной папки"""
    try:
        # 1. Создаем уникальное имя файла (UUID)
        file_id = str(uuid.uuid4())

        # 2. Формиаем структура данных для сохранения
        snap_content = {
            "id": file_id,
            "type": "folder",
            "url": snap.source_url,  # Начинается с file://
            "thumbnail": snap.thumbnail_base64,
            "binary_data": snap.binary_data,
            "metadata": snap.metadata_ai
        }

        # 3. Сохраняем файл в папку uploads
        filename = f"{file_id}.json"
        filepath = os.path.join(UPLOAD_DIR, filename)

        await asyncio.to_thread(
            lambda f=filepath, d=snap_content: (
                open(f, "w", encoding="utf-8").write(json.dumps(d, indent=4))
            )
        )

        # 4. Возвращаем ответ расши-extension
        return {
            "status": "success",
            "snap_id": file_id,
            "message": "Слепок папки успешно сохранен на сервере."
        }

    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")

# Путь для проверки: http://localhost:8000/
@app.get("/")
def root():
    return {
        "message": "Server is running.",
        "endpoints": {
            "/api/add-snap": "Сохраняет слепок веб-страницы",
            "/api/add-folder-snap": "Сохраняет слепок локальной папки"
        }
    }
