from __future__ import annotations

from typing import Any

try:
    from ..core.schema import GenerationOutput, GenerationRequest, GenerationResult
except ImportError:
    from core.schema import GenerationOutput, GenerationRequest, GenerationResult

try:
    from .base import BaseProvider
except ImportError:
    from providers.base import BaseProvider


class SeedanceProvider(BaseProvider):
    name = "seedance"

    def __init__(self, request_json, config: dict[str, Any]):
        super().__init__(request_json)
        self.api_key = str(config.get("api_key", "")).strip()
        self.api_base = str(config.get("api_base", "https://seedanceapi.org/v1")).strip().rstrip("/")
        self.video_model = str(config.get("video_model", "")).strip()
        self.resolution = str(config.get("resolution", "1080p")).strip()
        self.duration = int(config.get("duration", 5))
        self.aspect_ratio = str(config.get("aspect_ratio", "16:9")).strip()
        self.generate_audio = bool(config.get("generate_audio", True))
        self.fixed_lens = bool(config.get("fixed_lens", False))
        self.generate_path = str(config.get("generate_path", "/generate")).strip()
        self.status_path = str(config.get("status_path", "/status")).strip()
        if not self.generate_path.startswith("/"):
            self.generate_path = "/" + self.generate_path
        if not self.status_path.startswith("/"):
            self.status_path = "/" + self.status_path

    def supports_mode(self, mode: str) -> bool:
        return mode in {"text2video", "image2video"}

    def validate(self, kind: str, mode: str) -> str | None:
        if kind != "video":
            return f"供应商 {self.name} 暂不支持 {kind}"
        if not self.supports_mode(mode):
            return f"供应商 {self.name} 不支持模式: {mode}"
        if not self.api_key:
            return "未配置 seedance_api_key。"
        if not self.api_base:
            return "未配置 seedance_api_base。"
        return None

    async def submit(self, req: GenerationRequest) -> GenerationResult:
        payload: dict[str, Any] = {
            "prompt": req.prompt,
            "resolution": str(req.options.get("resolution", self.resolution)),
            "duration": str(req.options.get("duration", self.duration)),
            "aspect_ratio": str(req.options.get("aspect_ratio", self.aspect_ratio)),
            "generate_audio": bool(req.options.get("generate_audio", self.generate_audio)),
            "fixed_lens": bool(req.options.get("fixed_lens", self.fixed_lens)),
        }
        if self.video_model:
            payload["model"] = self.video_model
        if req.mode == "image2video":
            if not req.image_url:
                raise RuntimeError("Seedance 图生视频需要可访问图片 URL")
            payload["image_urls"] = [req.image_url]

        data = await self.request_json(
            "POST",
            f"{self.api_base}{self.generate_path}",
            self.api_key,
            payload=payload,
        )
        task_id = str((data.get("data") or {}).get("task_id", "")).strip() or str(data.get("task_id", "")).strip()
        if not task_id:
            raise RuntimeError("未返回任务 ID")
        return GenerationResult(
            provider=self.name,
            kind="video",
            mode=req.mode,
            status="pending",
            task_id=task_id,
        )

    async def query_video(self, task_id: str) -> GenerationResult:
        data = await self.request_json(
            "GET",
            f"{self.api_base}{self.status_path}",
            self.api_key,
            params={"task_id": task_id},
        )
        obj = data.get("data") if isinstance(data.get("data"), dict) else data
        raw_status = str(obj.get("status") or "running")
        status = self._map_status(raw_status)
        video_url = self._extract_video_url(obj.get("response", obj))
        reason = self._extract_fail_reason(obj)
        outputs: list[GenerationOutput] = []
        if video_url:
            outputs.append(GenerationOutput(output_type="video", url=video_url, metadata={"provider": self.name}))

        return GenerationResult(
            provider=self.name,
            kind="video",
            mode="text2video",
            status=status,
            task_id=task_id,
            outputs=outputs,
            fail_reason=reason,
            metadata={"raw_status": raw_status},
        )

    @staticmethod
    def _map_status(raw: str) -> str:
        value = (raw or "").strip().lower()
        if value in {"pending", "queued", "submitted"}:
            return "pending"
        if value in {"processing", "running", "in_progress"}:
            return "running"
        if value in {"success", "succeeded", "finished", "done", "completed"}:
            return "success"
        if value in {"timeout", "timed_out"}:
            return "timeout"
        if value in {"fail", "failed", "error", "canceled", "cancelled"}:
            return "failed"
        return "unknown"

    @staticmethod
    def _extract_video_url(data: Any) -> str:
        if isinstance(data, str) and data.startswith(("http://", "https://")):
            return data
        if isinstance(data, list):
            for value in data:
                url = SeedanceProvider._extract_video_url(value)
                if url:
                    return url
        if isinstance(data, dict):
            for key in ("url", "video_url", "download_url"):
                value = data.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
            for value in data.values():
                url = SeedanceProvider._extract_video_url(value)
                if url:
                    return url
        return ""

    @staticmethod
    def _extract_fail_reason(data: dict[str, Any]) -> str:
        for key in ("error", "message", "msg", "reason", "fail_reason", "error_message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
