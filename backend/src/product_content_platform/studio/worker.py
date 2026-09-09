from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .azure import AzureServiceError, AzureServices
from .creations import Creations
from .execution import package_job, package_review
from .quality import Review
from .quality_tasks import QualityChecks
from .workspace import StudioWorkspace

log = logging.getLogger("uvicorn.error")


class WorkspaceLease:
    """One automatic executor per workspace, including across server processes."""

    def __init__(self, root: Path):
        directory = root / "run"
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / "azure-worker.lock").open("a+b")
        try:
            if self.file.seek(0, 2) == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            import os
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("此工作区已有自动执行器或服务，请先停止原服务。") from None

    def close(self):
        self.file.close()


class StudioWorker:
    def __init__(self, workspace: StudioWorkspace, creations: Creations, quality: QualityChecks, services: AzureServices):
        self.workspace, self.creations, self.quality, self.services = workspace, creations, quality, services
        self.stop_event = threading.Event()
        self.check_event = threading.Event()
        self.check_event.set()
        self.state = "checking"
        self.error = ""
        self.review_error = ""
        self.threads = [threading.Thread(target=self._images, name="studio-images", daemon=True)]
        if services.planning_available:
            self.threads.append(threading.Thread(target=self._reviews, name="studio-reviews", daemon=True))

    @property
    def available(self) -> bool:
        return self.state == "ready" and self.threads[0].is_alive() and not self.stop_event.is_set()

    def start(self):
        for thread in self.threads:
            thread.start()

    def stop(self):
        self.stop_event.set()
        # Let an accepted external call persist its result before releasing the workspace lease.
        for thread in self.threads:
            thread.join()

    def recheck(self):
        self.check_event.set()

    def _images(self):
        try:
            self._recover_saved_results()
        except Exception:
            self.error = "已收到的图片恢复失败，请检查工作区文件权限和剩余磁盘空间。"
            log.error(self.error)
        while not self.stop_event.is_set():
            try:
                if self.check_event.is_set():
                    self.check_event.clear()
                    self.state = "checking"
                    self.services.check()
                    self.state, self.error = "ready", ""
                if self.state == "ready":
                    job = self.creations.claim(mode="codex")
                    if job:
                        self._run_image(job)
                        continue
            except AzureServiceError as error:
                self.state, self.error = "error", str(error)
                log.warning(self.error)
            except Exception:
                self.state, self.error = "error", "自动执行器异常，请检查工作区文件权限和磁盘空间后重新检测。"
                log.error(self.error)
            self.stop_event.wait(.5)

    def _run_image(self, job: dict):
        try:
            directory = self.workspace.settings.data_root / "production" / job["id"]
            output = self.services.generate(package_job(job, self.workspace), directory)
            receipt = directory / "asset.json"
            if receipt.is_file():
                asset_id = json.loads(receipt.read_text(encoding="utf-8"))["asset_id"]
            else:
                asset = self.workspace.upload_image("generated.png", "style", output["path"].read_bytes())
                asset_id = asset["id"]
                temporary = directory / "asset.tmp"
                temporary.write_text(json.dumps({"asset_id": asset_id}), encoding="utf-8")
                temporary.replace(receipt)
            version = self.creations.complete(job["id"], asset_id=asset_id, provenance=output["provenance"], review=Review(
                status="checking" if self.services.planning_available else "unavailable", source="azure-openai",
                note="图片已保存，正在进行独立质检。" if self.services.planning_available else "图片已保存；尚未配置质检模型。",
            ))
            if self.services.planning_available:
                self.quality.request(version["id"])
            self.error = ""
            log.info("Azure image saved: job=%s version=%s", job["id"], version["id"])
        except AzureServiceError as error:
            self._fail_running(job["id"], str(error), error.outcome_known)
            if error.blocks_service:
                self.state, self.error = "error", str(error)
            log.warning("Azure image job=%s: %s", job["id"], error)
        except Exception:
            message = "任务处理未完成，已收到的响应会保存在本地；请检查磁盘和工作区权限后重启服务，系统不会重复提交不明结果。"
            self._fail_running(job["id"], message, False)
            self.state, self.error = "error", message
            log.error("Azure image persistence failed: job=%s", job["id"])

    def _fail_running(self, identifier: str, message: str, outcome_known: bool):
        with self.workspace._connect() as db:
            row = db.execute("SELECT status FROM studio_jobs WHERE id=?", (identifier,)).fetchone()
        if row and row["status"] == "running":
            self.creations.fail(identifier, message=message, outcome_known=outcome_known)

    def _recover_saved_results(self):
        with self.workspace._connect() as db:
            rows = db.execute("""SELECT j.* FROM studio_jobs j JOIN studio_operations o ON j.operation_id=o.id
                WHERE j.status='unknown' AND o.mode='codex'""").fetchall()
            jobs = []
            for row in rows:
                if (self.workspace.settings.data_root / "production" / row["id"] / "response.json").is_file():
                    job = dict(row)
                    job["operation"] = self.creations._operation(db, row["operation_id"])
                    if row["source_version_id"]:
                        job["source_version"] = self.creations._version(db, row["source_version_id"])
                    jobs.append(job)
        for job in jobs:
            self._run_image(job)
        if self.services.planning_available:
            # Covers a crash between completing a version and enqueueing its read-only review.
            with self.workspace._connect() as db:
                versions = db.execute("""SELECT v.id FROM studio_versions v
                    WHERE json_extract(v.review, '$.status')='checking'
                    AND json_extract(v.provenance, '$.provider')='azure-openai'
                    AND NOT EXISTS (SELECT 1 FROM studio_review_tasks r WHERE r.version_id=v.id)""").fetchall()
            for version in versions:
                self.quality.request(version["id"])

    def _reviews(self):
        while not self.stop_event.is_set():
            task = None
            try:
                task = self.quality.claim()
                if task:
                    self.quality.complete(task["id"], self.services.review(package_review(task, self.workspace)))
                    self.review_error = ""
                    continue
            except Exception:
                self.review_error = "Azure 质检暂未完成，已有图片可查看和下载；请检查文案模型的连接与权限。"
                if task:
                    try:
                        self.quality.fail(task["id"], message=self.review_error)
                    except Exception:
                        log.error("Review task persistence failed: task=%s", task["id"])
                log.warning(self.review_error)
            self.stop_event.wait(2)
