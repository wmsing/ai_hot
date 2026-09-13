"""Admin job 互斥测试。"""

from __future__ import annotations

import threading
import time

from src.admin.services.jobs import (
    HotTopicsBusyError,
    create_job,
    get_job,
    hot_topics_llm_busy,
    job_should_stop,
    request_job_cancel,
    run_hot_topics_llm_job,
)


def test_hot_topics_llm_jobs_are_exclusive() -> None:
    gate = threading.Event()

    def _slow() -> dict[str, object]:
        gate.wait(timeout=2.0)
        return {"ok": True}

    job_a = create_job("translate")
    job_b = create_job("adhd")
    run_hot_topics_llm_job(job_a, _slow)
    deadline = time.time() + 2.0
    while time.time() < deadline and not hot_topics_llm_busy():
        time.sleep(0.01)
    assert hot_topics_llm_busy() is True
    try:
        run_hot_topics_llm_job(job_b, lambda: {"ok": True})
        raise AssertionError("expected HotTopicsBusyError")
    except HotTopicsBusyError:
        pass
    gate.set()
    deadline = time.time() + 2.0
    while time.time() < deadline and hot_topics_llm_busy():
        time.sleep(0.01)
    assert hot_topics_llm_busy() is False


def test_request_job_cancel_marks_cancelled_status() -> None:
    gate = threading.Event()
    done = threading.Event()

    def _slow() -> dict[str, object]:
        gate.wait(timeout=2.0)
        return {"changed": 1}

    job = create_job("adhd")
    run_hot_topics_llm_job(job, _slow)
    deadline = time.time() + 2.0
    while time.time() < deadline and not hot_topics_llm_busy():
        time.sleep(0.01)
    assert request_job_cancel(job.id) is True
    assert job_should_stop(job.id) is True
    gate.set()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        current = get_job(job.id)
        if current is not None and current.status != "running":
            break
        time.sleep(0.01)
    finished = get_job(job.id)
    assert finished is not None
    assert finished.status == "cancelled"
