"""FastAPI Admin Portal。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.admin.schemas import (
    AdhdDigestBatchRequest,
    AdhdDigestRequest,
    AdhdHotTopicRequest,
    AdhdHotTopicsAllRequest,
    AudioFileOut,
    CopyHotTopicToDigestRequest,
    DigestDayOut,
    DigestItemCreate,
    DigestItemUpdate,
    DigestRecentOut,
    DigestSpeakRequest,
    DigestTimelineDayOut,
    HotTopicCreate,
    HotTopicUpdate,
    JobOut,
    MergedDigestItemOut,
    PublishRequest,
    PullDataRequest,
    TranslateDigestSummariesRequest,
    TranslateDigestTitlesRequest,
    TranslateHotTopicTitlesRequest,
    UrlBody,
)
from src.admin.services.adhd import (
    generate_all_hot_topic_adhd,
    generate_digest_adhd,
    generate_digest_adhd_batch,
    generate_hot_topic_adhd,
    run_site_build,
)
from src.admin.services.audio import (
    AudioFileInfo,
    resolve_item_audio,
    resolve_play_path,
)
from src.admin.services.copy_hot_to_digest import (
    build_hot_topics_url_index,
    copy_hot_topic_to_digest,
    match_hot_topic_for_digest,
)
from src.admin.services.digest_timeline import (
    RECENT_PUBLISHED_DAYS_DEFAULT,
    list_published_days,
    rows_for_published_day,
    rows_for_recent_published_days,
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
from src.admin.services.probe import run_pull_data
from src.admin.services.publish import publish_push, publish_status
from src.admin.services.speak import digest_audio_status, run_digest_speak
from src.admin.services.translate import (
    translate_all_hot_topic_titles,
    translate_digest_day_summaries,
    translate_digest_day_titles,
)
from src.admin.stores import digest as digest_store
from src.admin.stores import hot_topics as hot_topics_store
from src.config import load_app_config
from src.models import DigestItem, HotTopicSnapshot, HotTopicSnapshotItem
from src.normalize import normalize_url
from src.speak_fingerprint import speak_voice_rate

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
        sync_status=info.sync_status,
    )


def _hot_topics_index() -> dict[str, HotTopicSnapshotItem]:
    return build_hot_topics_url_index(_hot_topics_path())


def _merged_out(
    item: digest_store.MergedDigestItem,
    *,
    day: date,
    hot_topics_by_url: dict[str, HotTopicSnapshotItem] | None = None,
    archive_day: date | None = None,
    published_day: date | None = None,
) -> MergedDigestItemOut:
    config = load_app_config()
    voice_en, rate = speak_voice_rate(config, "en")
    voice_zh, _ = speak_voice_rate(config, "zh")
    en_item = DigestItem(
        index=item.index,
        title=item.title_en,
        url=item.url,
        source=item.source,
        summary=item.summary_en,
        speak_summary=item.speak_en,
    )
    zh_item = DigestItem(
        index=item.index,
        title=item.title_zh,
        url=item.url,
        source=item.source,
        summary=item.summary_zh,
        speak_summary=item.speak_zh,
    )
    audio = resolve_item_audio(
        config.paths,
        day=day,
        index=item.index,
        item_en=en_item,
        item_zh=zh_item,
        voice_en=voice_en,
        voice_zh=voice_zh,
        rate=rate,
    )
    hot_item = None
    if hot_topics_by_url is not None:
        hot_item = hot_topics_by_url.get(normalize_url(item.url))
    hot_match, can_copy = match_hot_topic_for_digest(item, hot_item)
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
        hot_topic_match=hot_match,
        can_copy_hot_adhd=can_copy,
        archive_day=(archive_day or day).isoformat(),
        published_day=published_day.isoformat() if published_day else None,
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
            "hot_page_enabled": config.site.hot_page_enabled,
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

    @app.post("/api/hot-topics/items/copy-to-digest")
    def hot_topic_copy_to_digest(
        body: CopyHotTopicToDigestRequest,
    ) -> dict[str, object]:
        config = load_app_config()
        day_value = date.fromisoformat(body.day) if body.day else None
        try:
            return copy_hot_topic_to_digest(
                config,
                day=day_value,
                url=body.url,
            )
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
                urls=body.urls,
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

    @app.get("/api/digest-timeline/days")
    def digest_timeline_days() -> list[str]:
        return [d.isoformat() for d in list_published_days(_digests_dir())]

    @app.get("/api/digest-recent", response_model=DigestRecentOut)
    def digest_recent(limit: int = RECENT_PUBLISHED_DAYS_DEFAULT) -> DigestRecentOut:
        if limit < 1 or limit > 30:
            raise HTTPException(status_code=400, detail="limit must be 1..30")
        hot_index = _hot_topics_index()
        days, rows = rows_for_recent_published_days(_digests_dir(), limit=limit)
        return DigestRecentOut(
            limit=limit,
            published_days=[d.isoformat() for d in days],
            items=[
                _merged_out(
                    row.item,
                    day=row.archive_day,
                    archive_day=row.archive_day,
                    published_day=row.published_day,
                    hot_topics_by_url=hot_index,
                )
                for row in rows
            ],
        )

    @app.get(
        "/api/digest-timeline/{published_day}",
        response_model=DigestTimelineDayOut,
    )
    def digest_timeline_day(published_day: str) -> DigestTimelineDayOut:
        day_value = date.fromisoformat(published_day)
        hot_index = _hot_topics_index()
        rows = rows_for_published_day(_digests_dir(), day_value)
        return DigestTimelineDayOut(
            published_day=published_day,
            items=[
                _merged_out(
                    row.item,
                    day=row.archive_day,
                    archive_day=row.archive_day,
                    published_day=day_value,
                    hot_topics_by_url=hot_index,
                )
                for row in rows
            ],
        )

    @app.post(
        "/api/digest-timeline/{published_day}/translate-titles",
        response_model=JobOut,
    )
    def digest_timeline_translate_titles(
        published_day: str, body: TranslateDigestTitlesRequest
    ) -> JobOut:
        config = load_app_config()
        published_value = date.fromisoformat(published_day)
        job = create_job("digest_timeline_translate_titles")

        def _run() -> dict[str, object]:
            rows = rows_for_published_day(_digests_dir(), published_value)
            index_filter = {idx for idx in (body.indices or []) if idx > 0}
            by_archive: dict[date, list[int]] = {}
            for row in rows:
                if index_filter and row.item.index not in index_filter:
                    continue
                by_archive.setdefault(row.archive_day, []).append(row.item.index)
            changed = 0
            for archive_day, indices in by_archive.items():
                result = translate_digest_day_titles(
                    config,
                    day=archive_day,
                    indices=indices,
                    force=body.force,
                    llm_flag=body.llm,
                    should_stop=lambda: job_should_stop(job.id),
                )
                changed += int(str(result["changed"]))
            return {"published_day": published_day, "changed": changed}

        run_job(job, _run)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.post(
        "/api/digest-timeline/{published_day}/translate-summaries",
        response_model=JobOut,
    )
    def digest_timeline_translate_summaries(
        published_day: str, body: TranslateDigestSummariesRequest
    ) -> JobOut:
        config = load_app_config()
        published_value = date.fromisoformat(published_day)
        job = create_job("digest_timeline_translate_summaries")

        def _run() -> dict[str, object]:
            rows = rows_for_published_day(_digests_dir(), published_value)
            by_archive: dict[date, list[int]] = {}
            for row in rows:
                by_archive.setdefault(row.archive_day, []).append(row.item.index)
            changed = 0
            for archive_day, indices in by_archive.items():
                result = translate_digest_day_summaries(
                    config,
                    day=archive_day,
                    indices=indices,
                    force=body.force,
                    llm_flag=body.llm,
                    should_stop=lambda: job_should_stop(job.id),
                )
                changed += int(str(result["changed"]))
            return {"published_day": published_day, "changed": changed}

        run_job(job, _run)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

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
            items=[
                _merged_out(item, day=day_value, hot_topics_by_url=_hot_topics_index())
                for item in view.items
            ],
        )

    @app.post("/api/digests/{day}/items", response_model=MergedDigestItemOut)
    def post_digest_item(day: str, body: DigestItemCreate) -> MergedDigestItemOut:
        day_value = date.fromisoformat(day)
        item = digest_store.add_item(
            _digests_dir(),
            day_value,
            **body.model_dump(),
        )
        return _merged_out(
            item,
            day=day_value,
            hot_topics_by_url=_hot_topics_index(),
        )

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
        return _merged_out(
            item,
            day=day_value,
            hot_topics_by_url=_hot_topics_index(),
        )

    @app.post("/api/digests/{day}/items/{index}/copy-hot-adhd")
    def digest_copy_hot_adhd(day: str, index: int) -> dict[str, object]:
        config = load_app_config()
        day_value = date.fromisoformat(day)
        try:
            url = digest_store.item_url(_digests_dir(), day_value, index)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            return copy_hot_topic_to_digest(config, day=day_value, url=url)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/digests/{day}/items/{index}")
    def delete_digest_item(day: str, index: int) -> dict[str, bool]:
        try:
            digest_store.delete_item(_digests_dir(), date.fromisoformat(day), index)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/digests/{day}/translate-titles", response_model=JobOut)
    def digest_translate_titles(day: str, body: TranslateDigestTitlesRequest) -> JobOut:
        config = load_app_config()
        day_value = date.fromisoformat(day)
        job = create_job("digest_translate_titles")

        def _run() -> dict[str, object]:
            return translate_digest_day_titles(
                config,
                day=day_value,
                indices=body.indices,
                force=body.force,
                llm_flag=body.llm,
                should_stop=lambda: job_should_stop(job.id),
            )

        run_job(job, _run)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.post("/api/digests/{day}/translate-summaries", response_model=JobOut)
    def digest_translate_summaries(
        day: str, body: TranslateDigestSummariesRequest
    ) -> JobOut:
        config = load_app_config()
        day_value = date.fromisoformat(day)
        job = create_job("digest_translate_summaries")

        def _run() -> dict[str, object]:
            return translate_digest_day_summaries(
                config,
                day=day_value,
                indices=body.indices,
                force=body.force,
                llm_flag=body.llm,
                should_stop=lambda: job_should_stop(job.id),
            )

        run_job(job, _run)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.get("/api/digests/{day}/audio-status")
    def digest_audio_status_route(day: str) -> dict[str, object]:
        config = load_app_config()
        day_value = date.fromisoformat(day)
        try:
            return digest_audio_status(config, day=day_value)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/digests/{day}/items/speak", response_model=JobOut)
    def digest_speak(day: str, body: DigestSpeakRequest) -> JobOut:
        config = load_app_config()
        day_value = date.fromisoformat(day)
        job = create_job("digest_speak")

        def _run() -> dict[str, object]:
            return run_digest_speak(
                config,
                day=day_value,
                indices=body.indices,
                urls=body.urls,
                langs=body.langs,
                force=body.force,
                should_stop=lambda: job_should_stop(job.id),
            )

        run_job(job, _run)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

    @app.post("/api/digests/{day}/items/adhd-batch", response_model=JobOut)
    def digest_adhd_batch(day: str, body: AdhdDigestBatchRequest) -> JobOut:
        config = load_app_config()
        day_value = date.fromisoformat(day)
        if not body.indices:
            raise HTTPException(status_code=400, detail="indices required")
        job = create_job("digest_adhd_batch")

        def _run() -> dict[str, object]:
            return generate_digest_adhd_batch(
                config,
                day=day_value,
                indices=body.indices,
                force=body.force,
                llm_flag=body.llm,
                should_stop=lambda: job_should_stop(job.id),
            )

        run_job(job, _run)
        return JobOut(
            id=job.id,
            kind=job.kind,
            status=job.status,
            message=job.message,
            result=job.result,
        )

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

    @app.post("/api/pull", response_model=JobOut)
    def pull_data(body: PullDataRequest) -> JobOut:
        config = load_app_config()
        job = create_job("pull")

        def _run() -> dict[str, object]:
            return run_pull_data(config, llm_flag=body.llm)

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

    def _admin_index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/")
    def admin_home() -> RedirectResponse:
        return RedirectResponse(url="/digest/", status_code=307)

    @app.get("/digest")
    @app.get("/digest/")
    @app.get("/digest/{day}")
    @app.get("/hot")
    @app.get("/recent")
    def admin_spa(day: str | None = None) -> FileResponse:
        return _admin_index()

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    return app
