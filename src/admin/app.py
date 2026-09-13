"""FastAPI Admin Portal。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.admin.schemas import (
    AdhdDigestRequest,
    AdhdHotTopicRequest,
    AdhdHotTopicsAllRequest,
    AudioFileOut,
    DigestDayOut,
    DigestItemCreate,
    DigestItemUpdate,
    HotTopicCreate,
    HotTopicUpdate,
    JobOut,
    MergedDigestItemOut,
    PublishRequest,
    TranslateHotTopicTitlesRequest,
    UrlBody,
)
from src.admin.services.adhd import (
    generate_all_hot_topic_adhd,
    generate_digest_adhd,
    generate_hot_topic_adhd,
    run_site_build,
)
from src.admin.services.audio import (
    AudioFileInfo,
    resolve_item_audio,
    resolve_play_path,
)
from src.admin.services.jobs import (
    HotTopicsBusyError,
    create_job,
    get_job,
    hot_topics_llm_busy,
    job_should_stop,
    request_job_cancel,
    run_hot_topics_llm_job,
    run_job,
)
from src.admin.services.publish import publish_push, publish_status
from src.admin.services.translate import translate_all_hot_topic_titles
from src.admin.stores import digest as digest_store
from src.admin.stores import hot_topics as hot_topics_store
from src.config import load_app_config
from src.models import HotTopicSnapshot

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _hot_topics_path() -> Path:
    return Path(load_app_config().paths.hot_topics_path)


def _digests_dir() -> Path:
    return Path(load_app_config().paths.content_digests_dir)


def _audio_out(info: AudioFileInfo) -> AudioFileOut:
    return AudioFileOut(
        content_path=info.content_path,
        out_path=info.out_path,
        play_url=info.play_url,
        exists=info.exists,
    )


def _merged_out(
    item: digest_store.MergedDigestItem,
    *,
    day: date,
) -> MergedDigestItemOut:
    config = load_app_config()
    audio = resolve_item_audio(config.paths, day=day, index=item.index)
    return MergedDigestItemOut(
        index=item.index,
        title_en=item.title_en,
        title_zh=item.title_zh,
        url=item.url,
        source=item.source,
        published=item.published,
        score_line=item.score_line,
        summary_en=item.summary_en,
        summary_zh=item.summary_zh,
        speak_en=item.speak_en,
        speak_zh=item.speak_zh,
        tag=item.tag,
        image_url=item.image_url,
        has_adhd=digest_store.has_adhd_summary(item.summary_en)
        or digest_store.has_adhd_summary(item.summary_zh),
        audio_en=_audio_out(audio["en"]),
        audio_zh=_audio_out(audio["zh"]),
    )


def create_app() -> FastAPI:
    app = FastAPI(title="AI Hot Admin", version="0.1.0")

    @app.get("/api/meta")
    def meta() -> dict[str, object]:
        config = load_app_config()
        return {
            "hot_topics_path": config.paths.hot_topics_path,
            "content_digests_dir": config.paths.content_digests_dir,
            "site_output_dir": config.paths.site_output_dir,
            "hot_topics_llm_busy": hot_topics_llm_busy(),
        }

    @app.get("/api/hot-topics")
    def get_hot_topics() -> HotTopicSnapshot:
        return hot_topics_store.load_snapshot(_hot_topics_path())

    @app.post("/api/hot-topics")
    def post_hot_topic(body: HotTopicCreate) -> HotTopicSnapshot:
        try:
            return hot_topics_store.add_item(_hot_topics_path(), body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/hot-topics/items")
    def put_hot_topic(body: HotTopicUpdate) -> HotTopicSnapshot:
        updates = body.model_dump(exclude={"url"}, exclude_none=True)
        try:
            return hot_topics_store.update_item(
                _hot_topics_path(),
                body.url,
                updates=updates,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/hot-topics/items")
    def delete_hot_topic(body: UrlBody) -> HotTopicSnapshot:
        try:
            return hot_topics_store.delete_item(_hot_topics_path(), body.url)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/hot-topics/translate-titles", response_model=JobOut)
    def hot_topic_translate_titles(body: TranslateHotTopicTitlesRequest) -> JobOut:
        config = load_app_config()
        job = create_job("hot_topic_translate_titles")

        def _run() -> dict[str, object]:
            return translate_all_hot_topic_titles(
                config,
                urls=body.urls,
                force=body.force,
                llm_flag=body.llm,
                should_stop=lambda: job_should_stop(job.id),
            )

        try:
            run_hot_topics_llm_job(job, _run)
        except HotTopicsBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.post("/api/hot-topics/items/adhd-all", response_model=JobOut)
    def hot_topic_adhd_all(body: AdhdHotTopicsAllRequest) -> JobOut:
        config = load_app_config()
        job = create_job("hot_topic_adhd_all")

        def _run() -> dict[str, object]:
            return generate_all_hot_topic_adhd(
                config,
                force=body.force,
                llm_flag=body.llm,
                lang=body.lang,
                should_stop=lambda: job_should_stop(job.id),
            )

        try:
            run_hot_topics_llm_job(job, _run)
        except HotTopicsBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.post("/api/hot-topics/items/adhd", response_model=JobOut)
    def hot_topic_adhd(body: AdhdHotTopicRequest) -> JobOut:
        config = load_app_config()
        job = create_job("hot_topic_adhd")

        def _run() -> dict[str, object]:
            return generate_hot_topic_adhd(
                config,
                url=body.url,
                force=body.force,
                llm_flag=body.llm,
                lang=body.lang,
                should_stop=lambda: job_should_stop(job.id),
            )

        try:
            run_hot_topics_llm_job(job, _run)
        except HotTopicsBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.get("/api/digests/days")
    def digest_days() -> list[str]:
        return [d.isoformat() for d in digest_store.list_days(_digests_dir())]

    @app.get("/api/digests/{day}", response_model=DigestDayOut)
    def digest_day(day: str) -> DigestDayOut:
        try:
            view = digest_store.get_day(_digests_dir(), date.fromisoformat(day))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        day_value = date.fromisoformat(day)
        return DigestDayOut(
            day=view.day.isoformat(),
            generated_at=view.generated_at,
            items=[_merged_out(item, day=day_value) for item in view.items],
        )

    @app.post("/api/digests/{day}/items", response_model=MergedDigestItemOut)
    def post_digest_item(day: str, body: DigestItemCreate) -> MergedDigestItemOut:
        day_value = date.fromisoformat(day)
        item = digest_store.add_item(
            _digests_dir(),
            day_value,
            **body.model_dump(),
        )
        return _merged_out(item, day=day_value)

    @app.put("/api/digests/{day}/items/{index}", response_model=MergedDigestItemOut)
    def put_digest_item(
        day: str,
        index: int,
        body: DigestItemUpdate,
    ) -> MergedDigestItemOut:
        day_value = date.fromisoformat(day)
        try:
            item = digest_store.update_item(
                _digests_dir(),
                day_value,
                index,
                **body.model_dump(exclude_none=True),
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _merged_out(item, day=day_value)

    @app.delete("/api/digests/{day}/items/{index}")
    def delete_digest_item(day: str, index: int) -> dict[str, bool]:
        try:
            digest_store.delete_item(_digests_dir(), date.fromisoformat(day), index)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/digests/{day}/items/{index}/adhd", response_model=JobOut)
    def digest_adhd(day: str, index: int, body: AdhdDigestRequest) -> JobOut:
        config = load_app_config()
        try:
            url = digest_store.item_url(_digests_dir(), date.fromisoformat(day), index)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        job = create_job("digest_adhd")

        def _run() -> dict[str, object]:
            return generate_digest_adhd(
                config,
                day=date.fromisoformat(day),
                url=url,
                llm_flag=body.llm,
            )

        run_job(job, _run)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.get("/api/publish/status")
    def get_publish_status() -> dict[str, object]:
        try:
            return publish_status()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/publish", response_model=JobOut)
    def publish_content(body: PublishRequest) -> JobOut:
        job = create_job("publish")

        def _run() -> dict[str, object]:
            return publish_push(message=body.message)

        run_job(job, _run)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.post("/api/build", response_model=JobOut)
    def build_site() -> JobOut:
        job = create_job("build")
        run_job(job, run_site_build)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.get("/api/audio/{day}/{index}/{lang}")
    def play_audio(day: str, index: int, lang: str) -> FileResponse:
        if lang not in {"en", "zh"}:
            raise HTTPException(status_code=400, detail="lang must be en or zh")
        config = load_app_config()
        path = resolve_play_path(
            config,
            day=date.fromisoformat(day),
            index=index,
            lang=lang,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="mp3 not found")
        return FileResponse(path, media_type="audio/mpeg")

    @app.get("/api/jobs/{job_id}", response_model=JobOut)
    def job_status(job_id: str) -> JobOut:
        job = get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobOut)
    def cancel_job(job_id: str) -> JobOut:
        job = get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if not request_job_cancel(job_id):
            raise HTTPException(status_code=409, detail="job cannot be cancelled")
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message="cancelling",
            result=job.result,
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    return app
