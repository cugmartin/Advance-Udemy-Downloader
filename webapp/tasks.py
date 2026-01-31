import asyncio
from collections import deque
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .history import HistoryItem, HistoryStore


class TaskStatus(str):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadTask:
    id: str
    course_url: str
    created_at: datetime
    status: str = TaskStatus.QUEUED
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    command: List[str] = field(default_factory=list)
    workdir: Optional[Path] = None
    log_buffer: List[str] = field(default_factory=list)
    subscribers: List[asyncio.Queue] = field(default_factory=list)
    process: Optional[subprocess.Popen] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    loop: Optional[asyncio.AbstractEventLoop] = None
    is_drm: Optional[bool] = None

    def _trim_buffer(self) -> None:
        if len(self.log_buffer) > 1000:
            self.log_buffer = self.log_buffer[-1000:]

    def broadcast(self, line: Optional[str]) -> None:
        with self._lock:
            if line is not None:
                self.log_buffer.append(line)
                self._trim_buffer()
            subscribers = list(self.subscribers)
            loop = self.loop
        if not loop:
            return
        for queue in subscribers:
            asyncio.run_coroutine_threadsafe(queue.put(line), loop)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            loop = self.loop
            buffered = list(self.log_buffer)
            self.subscribers.append(queue)
        if loop:
            for line in buffered:
                asyncio.run_coroutine_threadsafe(queue.put(line), loop)
            if self.finished_at is not None:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self.subscribers:
                self.subscribers.remove(queue)


class TaskManager:
    def __init__(self, history_store: HistoryStore, base_dir: Path):
        self.history_store = history_store
        self.base_dir = base_dir
        self._tasks: Dict[str, DownloadTask] = {}
        self._lock = threading.Lock()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def _cleanup_logs(self) -> None:
        try:
            logs_dir = Path(self.base_dir) / "logs"
            if not logs_dir.exists():
                return

            keep_suffixes = set()

            try:
                for item in self.history_store.list_items():
                    task_id = (item or {}).get("task_id")
                    if isinstance(task_id, str) and len(task_id) >= 6:
                        keep_suffixes.add(task_id[-6:].upper())
            except Exception:
                pass

            with self._lock:
                active_tasks = list(self._tasks.values())
            for t in active_tasks:
                if t and isinstance(t.id, str) and len(t.id) >= 6 and t.status in (
                    TaskStatus.QUEUED,
                    TaskStatus.RUNNING,
                ):
                    keep_suffixes.add(t.id[-6:].upper())

            if not keep_suffixes:
                return

            for p in logs_dir.glob("*.log"):
                stem = p.stem
                if "_" not in stem:
                    continue
                suffix = stem.rsplit("_", 1)[-1].upper()
                if len(suffix) != 6:
                    continue
                if not suffix.isalnum():
                    continue
                if suffix not in keep_suffixes:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            return

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def list_tasks(self) -> List[DownloadTask]:
        with self._lock:
            return list(self._tasks.values())

    def get_task(self, task_id: str) -> DownloadTask:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(task_id)
            return task

    def create_task(self, course_url: str, command: List[str], *, is_drm: Optional[bool] = None) -> DownloadTask:
        if not self.loop:
            raise RuntimeError("TaskManager loop is not configured")
        task_id = uuid.uuid4().hex
        task = DownloadTask(
            id=task_id,
            course_url=course_url,
            command=command,
            created_at=datetime.utcnow(),
            workdir=self.base_dir,
            loop=self.loop,
            is_drm=is_drm,
        )
        with self._lock:
            self._tasks[task_id] = task
        return task

    def _record_history(self, task: DownloadTask, status: str, message: str) -> None:
        item = HistoryItem(
            task_id=task.id,
            course_url=task.course_url,
            started_at=(task.started_at.isoformat() if task.started_at else ""),
            finished_at=(task.finished_at.isoformat() if task.finished_at else datetime.utcnow().isoformat()),
            status=status,
            message=message,
            is_drm=task.is_drm,
        )
        self.history_store.add(item)

    def run_task(self, task: DownloadTask) -> None:
        def _emit(line: Optional[str]) -> None:
            task.broadcast(line)

        log_file = None
        log_fp = None
        try:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            env = os.environ.copy()
            env["TASK_ID_SUFFIX"] = task.id[-6:].upper()
            tail_lines = deque(maxlen=200)
            _emit(f"[system] Command: {' '.join(task.command)}")

            logs_dir = Path(task.workdir or self.base_dir) / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / f"{time.strftime('%m-%d_%H-%M-%S')}_{env['TASK_ID_SUFFIX']}.log"
            log_fp = open(log_file, "a", encoding="utf-8", errors="replace")
            _emit(f"[system] Log file: {log_file}")

            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

            process = subprocess.Popen(
                task.command,
                cwd=str(task.workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creationflags,
            )
            task.process = process
            _emit(f"[system] Spawned process PID {process.pid}")

            assert process.stdout is not None
            for line in process.stdout:
                line_clean = line.rstrip()
                tail_lines.append(line_clean)
                if log_fp is not None:
                    try:
                        log_fp.write(line)
                        log_fp.flush()
                    except Exception:
                        pass
                _emit(line_clean)

            ret_code = process.wait()
            task.finished_at = datetime.utcnow()
            if ret_code == 0:
                task.status = TaskStatus.SUCCESS
                _emit(f"[system] Process completed with exit code 0")
            else:
                task.status = TaskStatus.FAILED
                _emit(f"[system] Process exited with code {ret_code}")
            history_message = f"Exit code {ret_code}"
            if ret_code != 0 and tail_lines:
                tail = "\n".join(tail_lines).strip()
                if len(tail) > 8000:
                    tail = tail[-8000:]
                history_message = f"Exit code {ret_code}\n\n{tail}"
            self._record_history(task, task.status, history_message)
            self._cleanup_logs()
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.finished_at = datetime.utcnow()
            _emit(f"[system] Task failed: {exc}")
            self._record_history(task, task.status, str(exc))
            self._cleanup_logs()
        finally:
            if log_fp is not None:
                try:
                    log_fp.close()
                except Exception:
                    pass
            _emit(None)

    def start_task(self, task: DownloadTask) -> None:
        thread = threading.Thread(target=self.run_task, args=(task,), daemon=True)
        thread.start()
