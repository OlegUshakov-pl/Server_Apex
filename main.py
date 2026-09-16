import json
import os
import uuid
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# Папка для хранения слепков
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Модель данных, которую присылает расширение (как мы обсуждали ранее)
class SnapData(BaseModel):
    source_url: str       # URL страницы
    thumbnail_base64: str # Фото в формате Base64
    binary_data: str      # Бинарные данные (текст или JSON)
    metadata_ai: dict     # Метаданные от AI

# Путь: http://localhost:8000/api/add-snap
@app.post("/api/add-snap")
async def add_snap(snap: SnapData):

    # 1. Создаем уникальное имя файла (UUID)
    file_id = str(uuid.uuid4())

    # 2. Формируем структуру данных для сохранения
    snap_content = {
        "id": file_id,
        "url": snap.source_url,
        "thumbnail": snap.thumbnail_base64,
        "binary_data": snap.binary_data,
        "metadata": snap.metadata_ai
    }

    # 3. Сохраняем файл в папку uploads
    filename = f"{file_id}.json"
    filepath = os.path.join(UPLOAD_DIR, filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snap_content, f, indent=4)

        # 4. Возвращаем ответ расширению
        return {
            "status": "success",
            "snap_id": file_id,
            "message": "Слепок успешно сохранен на сервере."
        }

    except OSError as e:
        return {"status": "error", "message": f"Ошибка сохранения: {e}"}

# Путь для проверки: http://localhost:8000/
@app.get("/")
async def root():
    return {"message": "Server is running. Use /api/add-snap endpoint."}
