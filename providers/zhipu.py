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


class ZhipuProvider(BaseProvider):
    name = "zhipu"

    def __init__(self, request_json, config: dict[str, Any]):
        super().__init__(request_json)
        self.api_key = str(config.get("api_key", "")).strip()
        self.api_base = str(config.get("api_base", "https://open.bigmodel.cn/api/paas/v4")).strip().rstrip("/")
        self.video_model = str(config.get("video_model", "CogVideoX-Flash")).strip()
        self.image_model = str(config.get("image_model", "glm-image")).strip()
        self.video_with_audio = bool(config.get("video_with_audio", True))

    def supports_mode(self, mode: str) -> bool:
        return mode in {"text2image", "text2video", "image2video"}

    def validate(self, kind: str, mode: str) -> str | None:
        if not self.supports_mode(mode):
            return f"供应商 {self.name} 不支持模式: {mode}"
        if not self.api_key:
            return "未配置 zhipu_api_key。"
        return None

    async def submit(self, req: GenerationRequest) -> GenerationResult:
        if req.kind == "image":
            payload = {
                "model": self.image_model,
                "prompt": req.prompt,
                "size": req.size,
            }
            data = await self.request_json(
                "POST",
                f"{self.api_base}/images/generations",
                self.api_key,
                payload=payload,
            )
            outputs: list[GenerationOutput] = []
            for item in data.get("data") or []:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    outputs.append(GenerationOutput(output_type="image", url=url, metadata={"provider": self.name}))
            if not outputs:
                raise RuntimeError("接口未返回图片 URL")
            return GenerationResult(
                provider=self.name,
                kind=req.kind,
                mode=req.mode,
                status="success",
                outputs=outputs,
            )

        payload: dict[str, Any] = {
            "model": self.video_model,
            "prompt": req.prompt,
            "with_audio": bool(req.options.get("with_audio", self.video_with_audio)),
        }
        if req.mode == "image2video":
            if not req.image_b64:
                raise RuntimeError("图生视频需要图片数据")
            payload["image_url"] = req.image_b64

        data = await self.request_json(
            "POST",
            f"{self.api_base}/videos/generations",
            self.api_key,
            payload=payload,
        )
        task_id = str(data.get("id", "")).strip()
        if not task_id:
            raise RuntimeError("未返回任务 ID")
        return GenerationResult(
            provider=self.name,
            kind=req.kind,
            mode=req.mode,
            status="pending",
            task_id=task_id,
        )

    async def query_video(self, task_id: str) -> GenerationResult:
        data = await self.request_json(
            "GET",
            f"{self.api_base}/async-result/{task_id}",
            self.api_key,
        )
        status = self._map_status(str(data.get("task_status") or data.get("status") or "running"))
        video_url = self._extract_video_url(data.get("video_result", data))
        reason = self._extract_fail_reason(data)
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
            metadata={"raw_status": str(data.get("task_status") or data.get("status") or "")},
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
                url = ZhipuProvider._extract_video_url(value)
                if url:
                    return url
        if isinstance(data, dict):
            for key in ("url", "video_url", "download_url"):
                value = data.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
            for value in data.values():
                url = ZhipuProvider._extract_video_url(value)
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
