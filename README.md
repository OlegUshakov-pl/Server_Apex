
# FastAPI Сервер для хранения слепков (Snapshots)

## Описание

Серверный компонент системы, который принимает и хранит данные "слепков" от приложения ApexShot (FastAPI):
- **ApexShot**: кнопка «Послать» на странице Search (`POST /api/snapshots/{id}/send`) отправляет JSON слепка на `POST /api/add-snapshot` (Server URL задаётся в ApexShot → Settings → Server URL, например `http://localhost:8000/api/add-snapshot`)
- **Совместимость**: эндпоинты `/api/add-snap` (веб-страницы) и `/api/add-folder-snap` (папки) оставлены для обратной совместимости

## Установка

### Требования

- Python 3.14+
- pip
- SQLite с FTS5 (входит в стандартную сборку Python)

### Установка зависимостей

```bash
pip install -r requirements.txt
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
  "message": "Server is running.",
  "endpoints": {
    "/api/add-snap": "Сохраняет слепок веб-страницы",
    "/api/add-folder-snap": "Сохраняет слепок локальной папки",
    "/api/add-snapshot": "Сохраняет произвольный слепок (ApexShot)",
    "/api/search?q=...": "FTS5-поиск по слепкам",
    "/api/snaps/{snap_id}": "Получить слепок по id"
  }
}
```

### POST /api/add-snap

Сохраняет новый слепок **веб-страницы**.

**Запрос (веб-страница):**
```json
{
  "source_url": "https://example.com/page",
  "thumbnail_base64": "data:image/png;base64,iVBOR...",
  "binary_data": "{\"type\": \"text\", \"content\": \"Привет\"}",
  "metadata_ai": {
    "tags": ["news", "article"],
    "sentiment": 0.8,
    "summary": "Краткое описание...",
    "category": "tech"
  }
}
```

**Успешный ответ:**
```json
{
  "status": "success",
  "snap_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Веб-слепок успешно сохранен на сервере."
}
```

### POST /api/add-folder-snap

Сохраняет новый слепок **локальной папки**.

**Запрос (папка):**
```json
{
  "source_url": "file:///C:/Users/You/Documents/my-folder",
  "thumbnail_base64": "",
  "binary_data": "0101...",
  "metadata_ai": {
    "tags": ["folder", "documents"],
    "sentiment": 0.5,
    "summary": "Папка с документами",
    "category": "other",
    "files": [
      "report.pdf",
      "notes.txt",
      "budget.xlsx"
    ]
  }
}
```

**Успешный ответ:**
```json
{
  "status": "success",
  "snap_id": "b2c3d4e5-f6g7-8901-bcde-fg2345678901",
  "message": "Слепок папки успешно сохранен на сервере."
}
```

## Структура данных

Каждый слепок сохраняется в отдельный JSON-файл с именем `uuid.json` в папке `uploads/`
и дублируется в SQLite (`snaps.db`): таблица `snaps` + FTS5-индекс `snaps_fts` по полям
`snap_id, url, search_text`.

### Веб-страница:
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "type": "web",
  "url": "https://example.com/page",
  "thumbnail": "data:image/png;base64,...",
  "binary_data": "{\"type\": \"text\", ...}",
  "metadata": {
    "tags": ["news", "article"],
    "sentiment": 0.8,
    "summary": "Краткое описание...",
    "category": "tech"
  }
}
```

### Локальная папка:
```json
{
  "id": "b2c3d4e5-f6g7-8901-bcde-fg2345678901",
  "type": "folder",
  "url": "file:///C:/Users/You/Documents/my-folder",
  "thumbnail": "",
  "binary_data": "0101...",
  "metadata": {
    "tags": ["folder", "documents"],
    "sentiment": 0.5,
    "summary": "Папка с документами",
    "category": "other",
    "files": [
      "report.pdf",
      "notes.txt",
      "budget.xlsx"
    ]
  }
}
```

### POST /api/add-snapshot

Принимает произвольный JSON (сюда шлёт кнопка Send из ApexShot — поле Server URL).

**Запрос:** любой JSON-объект слепка ApexShot (`id`, `directory`, `title`, `summary`, `tags`, …).

**Успешный ответ:**
```json
{
  "status": "success",
  "snap_id": "snap-...",
  "message": "Слепок сохранен на сервере."
}
```

### GET /api/search?q=...&type=...&limit=20&offset=0

FTS5-поиск по слепкам (url + текст). Без `q` — последние слепки.

Возвращает лёгкие item'ы (`id`, `type`, `url`, `created_at`, `snippet` — первые
200 символов, без полного `metadata`), чтобы списки/расширения грузились быстро:

```json
{
  "total": 1, "limit": 20, "offset": 0,
  "items": [
    {
      "id": "snap-...",
      "type": "apex",
      "url": "C:/docs/project",
      "created_at": "2026-10-06T15:03:08Z",
      "snippet": "hello edge ..."
    }
  ]
}
```

Полный слепок — через `GET /api/snaps/{snap_id}`.

### GET /api/snaps/{snap_id}

Получить слепок из SQLite по id.

## Структура проекта

```
server_project/
├── main.py          # Основной файл приложения FastAPI + SQLite FTS5
├── snaps.db         # SQLite-база слепков (создаётся автоматически)
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

## Поддерживаемые типы слепков

| Тип | Endpoint | Пример URL |
|-----|----------|------------|
| Веб-страница | `/api/add-snap` | `https://example.com/page` |
| Локальная папка | `/api/add-folder-snap` | `file:///C:/Users/You/Documents/my-folder` |
| Произвольный (ApexShot) | `/api/add-snapshot` | `http://localhost:8000/api/add-snapshot` |
