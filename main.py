import asyncio
import json
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = BASE_DIR / "snaps.db"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Apex snapshots server", lifespan=lifespan)


# ---------------------------------------------------------------- models
class WebSnapData(BaseModel):
    source_url: str       # URL страницы (http://...)
    thumbnail_base64: str = ""  # Фото в формате Base64
    binary_data: str = ""       # Бинарные данные
    metadata_ai: dict = Field(default_factory=dict)  # Метаданные от AI


class FolderSnapData(BaseModel):
    source_url: str       # Путь к папке (file://...)
    thumbnail_base64: str = ""  # Обычно пусто для папок
    binary_data: str = ""       # Бинарные данные (hash пути)
    metadata_ai: dict = Field(default_factory=dict)  # Метаданные от AI (список файлов)


# ---------------------------------------------------------------- sqlite FTS5
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snaps (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  thumbnail TEXT NOT NULL DEFAULT '',
  binary_data TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  search_text TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS snaps_fts
USING fts5(
  snap_id,
  url,
  search_text
);
"""

_fts_ok: bool | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def fts_available(conn: sqlite3.Connection | None = None) -> bool:
    global _fts_ok
    if _fts_ok is not None:
        return _fts_ok
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS tmp_fts_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS tmp_fts_probe")
        _fts_ok = True
    except sqlite3.OperationalError:
        _fts_ok = False
    finally:
        if own:
            conn.close()
    return _fts_ok


def init_db() -> None:
    with _db() as conn:
        conn.executescript(SCHEMA_SQL)


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fts_query(query: str) -> str:
    parts = []
    for token in re.split(r"\s+", (query or "").strip()):
        cleaned = token.replace('"', " ").strip()
        if cleaned:
            parts.append(f'"{cleaned}"')
    return " AND ".join(parts)


def save_snap(
    snap_type: str,
    source_url: str,
    thumbnail: str,
    binary_data: str,
    metadata: dict,
    search_text: str = "",
    file_id: str | None = None,
) -> str:
    file_id = file_id or str(uuid.uuid4())
    metadata = metadata if isinstance(metadata, dict) else {}
    if not search_text:
        search_text = " ".join(
            part for part in [
                source_url,
                binary_data if len(binary_data) < 2000 else "",
                json.dumps(metadata, ensure_ascii=False),
            ] if part
        )
    snap_content = {
        "id": file_id,
        "type": snap_type,
        "url": source_url,
        "thumbnail": thumbnail,
        "binary_data": binary_data,
        "metadata": metadata,
    }
    filepath = UPLOAD_DIR / f"{file_id}.json"
    with _db() as conn:
        filepath.write_text(json.dumps(snap_content, ensure_ascii=False, indent=4), encoding="utf-8")
        conn.execute(
            """
            INSERT OR REPLACE INTO snaps
              (id, type, url, thumbnail, binary_data, metadata_json, search_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                snap_type,
                source_url,
                thumbnail,
                binary_data,
                json.dumps(metadata, ensure_ascii=False),
                search_text,
                now_iso(),
            ),
        )
        if fts_available(conn):
            conn.execute("DELETE FROM snaps_fts WHERE snap_id = ?", (file_id,))
            conn.execute(
                "INSERT INTO snaps_fts (snap_id, url, search_text) VALUES (?, ?, ?)",
                (file_id, source_url, search_text),
            )
    return file_id


def get_snap(snap_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM snaps WHERE id = ?", (snap_id,)).fetchone()
        return dict(row) if row else None


def search_snaps(query: str = "", snap_type: str = "", limit: int = 20, offset: int = 0) -> dict:
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    with _db() as conn:
        params: list[Any] = []
        if query.strip() and fts_available(conn):
            match = _fts_query(query)
            sql = (
                "SELECT s.* FROM snaps s JOIN snaps_fts f ON f.snap_id = s.id "
                "WHERE snaps_fts MATCH ?"
            )
            params.append(match)
            if snap_type:
                sql += " AND s.type = ?"
                params.append(snap_type)
            sql += " ORDER BY s.created_at DESC LIMIT ? OFFSET ?"
            params += [limit, offset]
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                rows = []
            count_sql = (
                "SELECT COUNT(*) AS c FROM snaps s JOIN snaps_fts f ON f.snap_id = s.id "
                "WHERE snaps_fts MATCH ?" + (" AND s.type = ?" if snap_type else "")
            )
            try:
                total = conn.execute(count_sql, params[:-2]).fetchone()["c"]
            except sqlite3.OperationalError:
                total = 0
        else:
            clauses: list[str] = []
            if snap_type:
                clauses.append("type = ?")
                params.append(snap_type)
            if query.strip():
                clauses.append("(url LIKE ? OR search_text LIKE ?)")
                like = f"%{query.strip()}%"
                params += [like, like]
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            total = conn.execute(f"SELECT COUNT(*) AS c FROM snaps {where}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM snaps {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        items = [
            {
                "id": r["id"],
                "type": r["type"],
                "url": r["url"],
                "created_at": r["created_at"],
                "metadata": json.loads(r["metadata_json"] or "{}"),
            }
            for r in rows
        ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------- endpoints
# Путь: http://localhost:8000/api/add-snap (веб-страницы)
@app.post("/api/add-snap")
async def add_snap(snap: WebSnapData):
    """Сохраняет слепок веб-страницы"""
    try:
        file_id = await asyncio.to_thread(
            save_snap,
            "web",
            snap.source_url,
            snap.thumbnail_base64,
            snap.binary_data,
            snap.metadata_ai,
        )
        return {
            "status": "success",
            "snap_id": file_id,
            "message": "Веб-слепок успешно сохранен на сервере.",
        }
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")


# Путь: http://localhost:8000/api/add-folder-snap (локальные папки)
@app.post("/api/add-folder-snap")
async def add_folder_snap(snap: FolderSnapData):
    """Сохраняет слепок локальной папки"""
    try:
        file_id = await asyncio.to_thread(
            save_snap,
            "folder",
            snap.source_url,
            snap.thumbnail_base64,
            snap.binary_data,
            snap.metadata_ai,
        )
        return {
            "status": "success",
            "snap_id": file_id,
            "message": "Слепок папки успешно сохранен на сервере.",
        }
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")


# Путь: http://localhost:8000/api/add-snapshot (произвольный JSON, напр. из ApexShot)
@app.post("/api/add-snapshot")
async def add_snapshot(payload: dict):
    """Сохраняет произвольный слепок (ApexShot Send шлёт сюда весь JSON)."""
    try:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Ожидается JSON-объект")
        source = (
            payload.get("directory")
            or payload.get("url")
            or payload.get("source_url")
            or payload.get("id")
            or ""
        )
        snap_type = str(payload.get("type") or "apex")
        file_id = str(payload.get("id") or uuid.uuid4())
        search_text = " ".join(
            part for part in [
                str(payload.get("title") or ""),
                str(payload.get("summary") or ""),
                str(payload.get("search_text") or ""),
                " ".join(str(t) for t in (payload.get("tags") or []) if isinstance(t, str)),
            ] if part
        ) or json.dumps(payload, ensure_ascii=False)[:4000]
        await asyncio.to_thread(
            save_snap, snap_type, str(source), "", json.dumps(payload, ensure_ascii=False),
            {"apex": payload}, search_text, file_id,
        )
        return {"status": "success", "snap_id": file_id, "message": "Слепок сохранен на сервере."}
    except HTTPException:
        raise
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")


@app.get("/api/snaps/{snap_id}")
def read_snap(snap_id: str):
    row = get_snap(snap_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Слепок {snap_id} не найден")
    try:
        row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
    except (json.JSONDecodeError, ValueError):
        row["metadata"] = {}
    return row


@app.get("/api/search")
def search(
    q: str = Query("", alias="q"),
    type: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return search_snaps(query=q, snap_type=type, limit=limit, offset=offset)


# Путь для проверки: http://localhost:8000/
@app.get("/")
def root():
    return {
        "message": "Server is running.",
        "endpoints": {
            "/api/add-snap": "Сохраняет слепок веб-страницы",
            "/api/add-folder-snap": "Сохраняет слепок локальной папки",
            "/api/add-snapshot": "Сохраняет произвольный слепок (ApexShot)",
            "/api/search?q=...": "FTS5-поиск по слепкам",
            "/api/snaps/{snap_id}": "Получить слепок по id",
        },
    }
