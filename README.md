# FastAPI Сервер для хранения слепков (Snapshots)

## Описание

Серверный компонент системы, который принимает и хранит данные "слепков" от расширения браузера. Каждый слепок содержит информацию о странице, изображение-превью, бинарные данные и метаданные от AI.

## Установка

### Требования

- Python 3.8+
- pip

### Установка зависимостей

```bash
pip install fastapi uvicorn pydantic
```

### Запуск сервера

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Или просто:

```bash
python main.py
```

Сервер будет доступен по адресу `http://localhost:8000`

## API

### GET /

Проверка работы сервера.

**Ответ:**
```json
{
  "message": "Server is running. Use /api/add-snap endpoint."
}
```

### POST /api/add-snap

Сохраняет новый слепок на сервере.

**Запрос:**
```json
{
  "source_url": "https://example.com",
  "thumbnail_base64": "data:image/png;base64,iVBOR...",
  "binary_data": "{\"type\": \"text\", \"content\": \"Привет\"}",
  "metadata_ai": {
    "model_version": "v1.0",
    "confidence": 0.95,
    "tags": ["news", "article"]
  }
}
```

**Успешный ответ:**
```json
{
  "status": "success",
  "snap_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Слепок успешно сохранен на сервере."
}
```

**Ошибка:**
```json
{
  "status": "error",
  "message": "Ошибка сохранения: ..."
}
```

## Структура данных

Каждый слепок сохраняется в отдельный JSON-файл с именем `uuid.json` в папке `uploads/`.

**Структура файла:**
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "url": "https://example.com",
  "thumbnail": "data:image/png;base64,...",
  "binary_data": "...",
  "metadata": {
    "model_version": "v1.0",
    "confidence": 0.95,
    "tags": ["news", "article"]
  }
}
```

## Структура проекта

```
server_project/
├── main.py          # Основной файл приложения FastAPI
├── uploads/         # Папка для хранения слепков (создаётся автоматически)
└── README.md        # Документация
```

## Настройка

### Порт сервера

Измените порт в запуске:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

### Папка для хранения

По умолчанию используется `uploads/`. Измените переменную `UPLOAD_DIR` в `main.py`:
```python
UPLOAD_DIR = "my_snapshots"  # вместо "uploads"
```

## Лицензия

MIT License
