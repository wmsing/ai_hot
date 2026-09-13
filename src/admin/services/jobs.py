"""内存 job 队列（本地单用户）。"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

JobStatus = Literal["pending", "running", "done", "error", "cancelled"]


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus = "pending"
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


_lock = threading.Lock()
_jobs: dict[str, Job] = {}
_hot_topics_llm_lock = threading.Lock()


class HotTopicsBusyError(RuntimeError):
    """热搜 LLM 任务已在运行（translate / ADHD 互斥）。"""


def create_job(kind: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind)
    with _lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def request_job_cancel(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.status not in {"pending", "running"}:
            return False
        job.cancel_requested = True
        return True


def job_should_stop(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        return bool(job and job.cancel_requested)


def _set_status(job: Job, status: JobStatus, message: str = "") -> None:
    job.status = status
    if message:
        job.message = message
    if status in {"done", "error", "cancelled"}:
        job.finished_at = datetime.now(timezone.utc)


def hot_topics_llm_busy() -> bool:
    return _hot_topics_llm_lock.locked()


def run_job(job: Job, fn: Callable[[], dict[str, Any]]) -> None:
    def _worker() -> None:
        with _lock:
            _set_status(job, "running")
        try:
            result = fn()
            with _lock:
                job.result = result
                _set_status(job, "done", "ok")
        except Exception as exc:
            with _lock:
                _set_status(job, "error", str(exc))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def run_hot_topics_llm_job(job: Job, fn: Callable[[], dict[str, Any]]) -> None:
    """热搜 translate / ADHD 互斥：同时只允许一个任务写 latest.json。"""
    if not _hot_topics_llm_lock.acquire(blocking=False):
        with _lock:
            _set_status(job, "error", "hot topics llm job already running")
        raise HotTopicsBusyError("hot topics llm job already running")

    def _worker() -> None:
        with _lock:
            _set_status(job, "running")
        try:
            result = fn()
            with _lock:
                job.result = result
                if job.cancel_requested:
                    _set_status(job, "cancelled", "stopped by user")
                else:
                    _set_status(job, "done", "ok")
        except Exception as exc:
            with _lock:
                _set_status(job, "error", str(exc))
        finally:
            _hot_topics_llm_lock.release()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
