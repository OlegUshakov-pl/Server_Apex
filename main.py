import asyncio
import html
import json
import os
import re
import signal
import socket
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = BASE_DIR / "snaps.db"

# Время запуска сервера (обновляется при старте приложения, см. lifespan)
STARTED_AT = datetime.now(timezone.utc)
# Сколько слепков показывать на странице статуса (остальные — только счётчиком)
STATUS_LIMIT = 200
# Порт сервера (должен совпадать с --port в start.bat)
SERVER_PORT = 8000


@asynccontextmanager
async def lifespan(_: FastAPI):
    global STARTED_AT
    STARTED_AT = datetime.now(timezone.utc)
    init_db()
    yield


app = FastAPI(title="Apex snapshots server", lifespan=lifespan)

# CORS для браузерного расширения (Edge): fetch к localhost из расширения
# требует разрешающих заголовков. Сервер локальный, поэтому разрешено всё.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def _fts_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for token in re.split(r"\s+", (query or "").strip()):
        # Убираем кавычки и спецсимволы FTS5, оставляем буквы/цифры
        cleaned = token.replace('"', " ").replace("'", " ").strip()
        cleaned = re.sub(r"[()*^:;+\-]", " ", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) >= 2:
            tokens.append(cleaned)
    # Если запрос состоял только из коротких токенов (напр. "s"),
    # оставляем их как есть, иначе поиск вернул бы всё/ничего
    if not tokens:
        single = (query or "").strip().replace('"', "").strip()
        if single:
            tokens = [single]
    return tokens


def _fts_query(query: str) -> str:
    # Поиск по ЛЮБОМУ слову (OR), а не по всем сразу (AND).
    # Раньше "CRM ERP" требовал оба слова и часто давал 0,
    # а LIKE-фолбэк искал точную фразу целиком.
    return " OR ".join(f'"{t}"' for t in _fts_tokens(query))


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
    # Компактный JSON без отступов: файлы меньше, читаются через API
    filepath.write_text(
        json.dumps(snap_content, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    with _db() as conn:
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


def delete_snap(snap_id: str) -> bool:
    """Удаляет слепок из SQLite + FTS + файл. Возвращает True если что-то было."""
    with _db() as conn:
        cur = conn.execute("DELETE FROM snaps WHERE id = ?", (snap_id,))
        gone = (cur.rowcount or 0) > 0
        try:
            if fts_available(conn):
                conn.execute("DELETE FROM snaps_fts WHERE snap_id = ?", (snap_id,))
        except sqlite3.OperationalError:
            pass
    try:
        (UPLOAD_DIR / f"{snap_id}.json").unlink(missing_ok=True)
    except OSError:
        pass
    return gone


def rebuild_fts() -> dict:
    """Пересоздаёт FTS-индекс из таблицы snaps (после ручных правок БД)."""
    with _db() as conn:
        if not fts_available(conn):
            return {"status": "fts-unavailable"}
        try:
            conn.execute("DELETE FROM snaps_fts")
        except sqlite3.OperationalError as e:
            return {"status": "error", "detail": str(e)}
        rows = conn.execute("SELECT id, url, search_text FROM snaps").fetchall()
        for r in rows:
            conn.execute(
                "INSERT INTO snaps_fts (snap_id, url, search_text) VALUES (?, ?, ?)",
                (r["id"], r["url"], r["search_text"]),
            )
        return {"status": "ok", "indexed": len(rows)}


def search_snaps(query: str = "", snap_type: str = "", limit: int = 20, offset: int = 0) -> dict:
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    query = (query or "").strip()
    with _db() as conn:
        params: list[Any] = []
        rows: list[Any] = []
        total = 0
        fts_tried = False
        if query and fts_available(conn):
            fts_tried = True
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
                fts_tried = False  # синтаксис FTS не переварил — уйдём в LIKE
            else:
                count_sql = (
                    "SELECT COUNT(*) AS c FROM snaps s JOIN snaps_fts f ON f.snap_id = s.id "
                    "WHERE snaps_fts MATCH ?" + (" AND s.type = ?" if snap_type else "")
                )
                try:
                    total = conn.execute(count_sql, params[:-2]).fetchone()["c"]
                except sqlite3.OperationalError:
                    total = 0
            # Если FTS ничего не нашёл (строгий поиск), пробуем мягкий LIKE по любым словам —
            # это и есть "поиск по смыслу/словам", а не "всё подряд"
            if fts_tried and not rows:
                fts_tried = False
        if not fts_tried:
            params = []
            clauses: list[str] = []
            if snap_type:
                clauses.append("type = ?")
                params.append(snap_type)
            if query:
                # Любое слово из query в url или search_text (case-insensitive, включая кириллицу)
                like_clauses: list[str] = []
                like_params: list[Any] = []
                for tok in _fts_tokens(query):
                    like_clauses.append("(LOWER(url) LIKE LOWER(?) ESCAPE '\\' OR LOWER(search_text) LIKE LOWER(?) ESCAPE '\\')")
                    like = f"%{tok}%"
                    like_params += [like, like]
                if like_clauses:
                    clauses.append("(" + " OR ".join(like_clauses) + ")")
                    params += like_params
                else:
                    clauses.append("(LOWER(url) LIKE LOWER(?) ESCAPE '\\' OR LOWER(search_text) LIKE LOWER(?) ESCAPE '\\')")
                    like = f"%{query}%"
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
                # Короткий фрагмент вместо полного metadata: лёгкая выдача
                # для списков/расширения, полный слепок — через /api/snaps/{id}
                "snippet": " ".join(str(r["search_text"] or "").split())[:200],
            }
            for r in rows
        ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ---------------------------------------------------------------- status
def _local_ip() -> str:
    """LAN IP-адрес этой машины (доступный с других компьютеров).

    socket.gethostbyname(socket.gethostname()) часто возвращает адрес
    виртуального адаптера (VMware/VPN), поэтому определяем IP по маршруту,
    который используется для исходящего трафика. Пакеты при этом реально
    не отправляются.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _uptime_str(since: datetime, now: datetime) -> str:
    """Uptime в удобном формате: дни/часы/минуты."""
    total = max(0, int((now - since).total_seconds()))
    days, total = divmod(total, 86400)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)
    if days:
        return f"{days}d {hours}h {minutes}min"
    if hours:
        return f"{hours}h {minutes}min"
    if minutes:
        return f"{minutes}min {seconds}s"
    return f"{seconds}s"


def _human_size(n: int | None) -> str:
    if n is None:
        return "—"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{n} B"
        size /= 1024
    return f"{n} B"


def get_status(limit: int = STATUS_LIMIT) -> dict:
    """Собирает данные для страницы /status и /api/status."""
    now = datetime.now(timezone.utc)
    server_ip = _local_ip()
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM snaps").fetchone()["c"]
        rows = conn.execute(
            "SELECT id, type, url, created_at FROM snaps"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    items = []
    for r in rows:
        path = UPLOAD_DIR / f"{r['id']}.json"
        try:
            size = path.stat().st_size if path.is_file() else None
        except OSError:
            size = None
        items.append(
            {
                "id": r["id"],
                "type": r["type"],
                "url": r["url"],
                "created_at": r["created_at"],
                "file_path": str(path),
                "file_exists": size is not None,
                "file_size": size,
            }
        )
    return {
        "status": "Running",
        "started_at": STARTED_AT.isoformat().replace("+00:00", "Z"),
        "uptime": _uptime_str(STARTED_AT, now),
        "server_ip": server_ip,
        "server_port": SERVER_PORT,
        "lan_url": f"http://{server_ip}:{SERVER_PORT}/status",
        "total": total,
        "shown": len(items),
        "items": items,
    }


def render_status_html(st: dict) -> str:
    """Simple status HTML page: plain HTML + minimal CSS, no dependencies."""
    if st["total"] > st["shown"]:
        note = f"<p>Showing first {st['shown']} of {st['total']}.</p>"
    else:
        note = ""
    rows = []
    for it in st["items"]:
        mark = "OK" if it["file_exists"] else "missing file"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(it['id']))}</code></td>"
            f"<td>{html.escape(str(it['url'] or '-'))}</td>"
            f"<td>{html.escape(str(it['type'] or ''))}</td>"
            f"<td>{html.escape(str(it['created_at']))}</td>"
            f"<td>{_human_size(it['file_size'])}</td>"
            f"<td><code>{html.escape(str(it['file_path']))}</code> ({mark})</td>"
            "</tr>"
        )
    table = (
        "<table><thead><tr>"
        "<th>Snapshot ID</th><th>Name / URL</th><th>Type</th>"
        "<th>Created at</th><th>File size</th><th>JSON file path</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else '<tr><td colspan="6">No snapshots yet.</td></tr>')
        + "</tbody></table>"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Server status — Apex snapshots</title>
<style>
body {{ font-family: sans-serif; max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #222; }}
.badge {{ display: inline-block; padding: 0.2em 0.8em; border-radius: 0; color: #fff; background: #16a34a; font-weight: bold; }}
.card {{ border: 1px solid #ddd; border-radius: 0; padding: 1em; margin-bottom: 1em; background: #fafafa; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9em; }}
th, td {{ border: 1px solid #ddd; padding: 0.4em 0.6em; text-align: left; vertical-align: top; }}
th {{ background: #f0f0f0; }}
code {{ word-break: break-all; }}
.btn {{ display: inline-block; padding: 0.5em 1em; margin-right: 0.5em; border: 1px solid #999; border-radius: 0; background: #fff; cursor: pointer; font-size: 1em; text-decoration: none; color: #222; }}
.btn.danger {{ border-color: #dc2626; color: #dc2626; }}
.btn:disabled {{ opacity: 0.5; cursor: default; }}
</style>
</head>
<body>
<h1>Server status</h1>
<div class="card">
<p>Status: <span class="badge">Running</span></p>
<p>Started at: {html.escape(st['started_at'])}</p>
<p>Uptime: {html.escape(st['uptime'])}</p>
<p>Server IP address: {html.escape(st['server_ip'])}</p>
<p>From another computer: <code>{html.escape(st['lan_url'])}</code></p>
<p>Total snapshots: {st['total']}</p>
</div>
<div class="card">
<a class="btn" href="/status">&#8635; Refresh</a>
<button class="btn" disabled title="Server is already running. Use start.bat to launch it">Start server</button>
<form method="post" action="/api/shutdown" style="display:inline" onsubmit="return confirm('Stop the server? The page will stop responding.');">
<button class="btn danger" type="submit">Stop server</button>
</form>
</div>
<h2>Snapshots</h2>
{note}
{table}
</body>
</html>"""


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
            payload.get("source_url")
            or payload.get("url")
            or payload.get("directory")
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
            save_snap, snap_type, str(source), "", "", {"apex": payload}, search_text, file_id,
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
    # Лог в консоль uvicorn: видно, что реально прислало расширение
    # (пустой q = вернётся всё; это нормально для ?q без значения)
    result = search_snaps(query=q, snap_type=type, limit=limit, offset=offset)
    print(f'SEARCH q={q!r} -> total={result.get("total")} items={len(result.get("items", []))}')
    return result


@app.delete("/api/snaps/{snap_id}")
def remove_snap(snap_id: str):
    """Удаляет слепок везде (SQLite + FTS + файл в uploads/)."""
    if not delete_snap(snap_id):
        raise HTTPException(status_code=404, detail=f"Слепок {snap_id} не найден")
    return {"status": "success", "snap_id": snap_id}


@app.post("/api/rebuild-fts")
def api_rebuild_fts():
    """Пересоздаёт FTS-индекс из таблицы snaps (после ручных правок БД)."""
    return rebuild_fts()


# Путь: http://localhost:8000/status — HTML-страница состояния сервера
@app.get("/status", response_class=HTMLResponse)
def status_page():
    return render_status_html(get_status())


# Путь: http://localhost:8000/api/status — то же самое в JSON
@app.get("/api/status")
def api_status():
    return get_status()


def _process_cmdline(pid: int) -> str:
    """Command line of another process (used to detect the uvicorn --reload supervisor)."""
    try:
        if os.name == "nt":
            out = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'"
                    " | Select-Object -ExpandProperty CommandLine)",
                ],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
            return out
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(errors="replace")
    except Exception:
        return ""


def _stop_server() -> None:
    """Stops the whole server.

    Under ``uvicorn --reload`` a plain exit only kills the worker and the
    reloader supervisor restarts it, so the supervisor process (whose command
    line contains ``--reload``) must be terminated too. Without ``--reload``
    the parent is just the console, which must NOT be touched.
    """
    try:
        ppid = os.getppid()
        if "--reload" in _process_cmdline(ppid):
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(ppid), "/T", "/F"],
                               capture_output=True, timeout=15)
            else:
                os.kill(ppid, signal.SIGTERM)
            time.sleep(2)
    except Exception:
        pass
    finally:
        os._exit(0)


STOPPED_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Server stopped — Apex snapshots</title>
<style>
body { font-family: sans-serif; max-width: 700px; margin: 2em auto; padding: 0 1em; color: #222; }
.badge { display: inline-block; padding: 0.2em 0.8em; border-radius: 0; color: #fff; background: #dc2626; font-weight: bold; }
.card { border: 1px solid #ddd; border-radius: 0; padding: 1em; margin-bottom: 1em; background: #fafafa; }
code { word-break: break-all; }
</style>
</head>
<body>
<h1>Server status</h1>
<div class="card">
<p>Status: <span class="badge">Stopped</span></p>
<p>The server has been stopped. You can close this tab.</p>
<p>To start it again, run <code>start.bat</code>.</p>
</div>
</body>
</html>"""


@app.post("/api/shutdown", response_class=HTMLResponse)
def shutdown():
    """Stops the server (button on the /status page)."""
    threading.Timer(1.0, _stop_server).start()
    return STOPPED_HTML


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
            "/status": "HTML-страница состояния сервера",
            "/api/status": "Состояние сервера в JSON",
        },
    }
