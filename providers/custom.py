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


def _normalize_path(path: str, default_path: str) -> str:
    value = str(path or default_path).strip()
    if not value.startswith("/"):
        value = "/" + value
    return value


def _deep_get(data: Any, path: str) -> Any:
    current = data
    for key in (path or "").split("."):
        if not key:
            continue
        if isinstance(current, list):
            if key.isdigit():
                idx = int(key)
                if 0 <= idx < len(current):
                    current = current[idx]
                    continue
            return None
        if isinstance(current, dict):
            current = current.get(key)
            continue
        return None
    return current


def _parse_path_list(raw: Any, fallback: list[str]) -> list[str]:
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
        return values or fallback
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",") if part.strip()]
        return values or fallback
    return fallback


def _first_non_empty(data: Any, paths: list[str]) -> Any:
    for path in paths:
        value = _deep_get(data, path)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, (dict, list)) and value:
            return value
    return None


def _find_first_url(data: Any) -> str:
    if isinstance(data, str) and data.startswith(("http://", "https://")):
        return data
    if isinstance(data, list):
        for item in data:
            found = _find_first_url(item)
            if found:
                return found
    if isinstance(data, dict):
        for key in ("url", "video_url", "download_url"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        for value in data.values():
            found = _find_first_url(value)
            if found:
                return found
    return ""


def _map_status(raw_status: str) -> str:
    value = (raw_status or "").strip().lower()
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


class CustomImageProvider(BaseProvider):
    def __init__(self, request_json, name: str, config: dict[str, Any]):
        super().__init__(request_json)
        self.name = name
        self.api_key = str(config.get("api_key", "")).strip()
        self.api_base = str(config.get("api_base", "")).strip().rstrip("/")
        self.generate_path = _normalize_path(str(config.get("generate_path", "/images/generations")), "/images/generations")
        self.model = str(config.get("model", "")).strip()
        self.prompt_field = str(config.get("prompt_field", "prompt")).strip() or "prompt"
        self.size_field = str(config.get("size_field", "size")).strip() or "size"
        self.model_field = str(config.get("model_field", "model")).strip() or "model"
        self.response_data_path = str(config.get("response_data_path", "data")).strip() or "data"
        self.response_url_field = str(config.get("response_url_field", "url")).strip() or "url"

    def supports_mode(self, mode: str) -> bool:
        return mode == "text2image"

    def validate(self, kind: str, mode: str) -> str | None:
        if kind != "image":
            return f"供应商 {self.name} 暂不支持 {kind}"
        if not self.supports_mode(mode):
            return f"供应商 {self.name} 不支持模式: {mode}"
        if not self.api_key:
            return f"未配置 {self.name} 的 api_key。"
        if not self.api_base:
            return f"未配置 {self.name} 的 api_base。"
        return None

    async def submit(self, req: GenerationRequest) -> GenerationResult:
        payload: dict[str, Any] = {
            self.prompt_field: req.prompt,
            self.size_field: req.size,
        }
        if self.model:
            payload[self.model_field] = self.model

        data = await self.request_json(
            "POST",
            f"{self.api_base}{self.generate_path}",
            self.api_key,
            payload=payload,
        )

        outputs: list[GenerationOutput] = []
        data_node = _deep_get(data, self.response_data_path)
        if isinstance(data_node, list):
            for item in data_node:
                if not isinstance(item, dict):
                    continue
                url = item.get(self.response_url_field)
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    outputs.append(GenerationOutput(output_type="image", url=url, metadata={"provider": self.name}))
        elif isinstance(data_node, dict):
            url = data_node.get(self.response_url_field)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                outputs.append(GenerationOutput(output_type="image", url=url, metadata={"provider": self.name}))

        if not outputs:
            fallback_url = _find_first_url(data)
            if fallback_url:
                outputs.append(GenerationOutput(output_type="image", url=fallback_url, metadata={"provider": self.name}))

        if not outputs:
            raise RuntimeError("接口未返回图片 URL")

        return GenerationResult(
            provider=self.name,
            kind="image",
            mode=req.mode,
            status="success",
            outputs=outputs,
        )


class CustomVideoProvider(BaseProvider):
    def __init__(self, request_json, name: str, config: dict[str, Any]):
        super().__init__(request_json)
        self.name = name
        self.api_key = str(config.get("api_key", "")).strip()
        self.api_base = str(config.get("api_base", "")).strip().rstrip("/")
        self.submit_path = _normalize_path(str(config.get("submit_path", "/generate")), "/generate")
        self.query_path = _normalize_path(str(config.get("query_path", "/status")), "/status")
        self.submit_method = str(config.get("submit_method", "POST")).strip().upper() or "POST"
        self.query_method = str(config.get("query_method", "GET")).strip().upper() or "GET"

        self.model = str(config.get("model", "")).strip()
        self.prompt_field = str(config.get("prompt_field", "prompt")).strip() or "prompt"
        self.model_field = str(config.get("model_field", "model")).strip() or "model"
        self.support_i2v = bool(config.get("support_i2v", False))
        self.i2v_input_type = str(config.get("i2v_input_type", "url")).strip().lower() or "url"
        self.i2v_field = str(config.get("i2v_field", "image_url")).strip() or "image_url"
        self.query_task_param = str(config.get("query_task_param", "task_id")).strip() or "task_id"
        self.query_in_body = bool(config.get("query_in_body", False))
        self.extra_payload = config.get("extra_payload", {}) if isinstance(config.get("extra_payload", {}), dict) else {}

        self.task_id_paths = _parse_path_list(config.get("task_id_paths"), ["data.task_id", "task_id", "id"])
        self.status_paths = _parse_path_list(config.get("status_paths"), ["data.status", "status", "task_status"])
        self.video_url_paths = _parse_path_list(
            config.get("video_url_paths"),
            ["data.video_url", "video_url", "data.url", "url", "video_result", "data.response"],
        )
        self.fail_reason_paths = _parse_path_list(
            config.get("fail_reason_paths"),
            ["data.error.message", "error", "message", "msg", "reason", "fail_reason", "error_message"],
        )

    def supports_mode(self, mode: str) -> bool:
        if mode == "text2video":
            return True
        if mode == "image2video" and self.support_i2v:
            return True
        return False

    def validate(self, kind: str, mode: str) -> str | None:
        if kind != "video":
            return f"供应商 {self.name} 暂不支持 {kind}"
        if not self.supports_mode(mode):
            return f"供应商 {self.name} 不支持模式: {mode}"
        if not self.api_key:
            return f"未配置 {self.name} 的 api_key。"
        if not self.api_base:
            return f"未配置 {self.name} 的 api_base。"
        return None

    async def submit(self, req: GenerationRequest) -> GenerationResult:
        payload: dict[str, Any] = dict(self.extra_payload)
        payload[self.prompt_field] = req.prompt
        if self.model:
            payload[self.model_field] = self.model

        if req.mode == "image2video":
            if not self.support_i2v:
                raise RuntimeError(f"供应商 {self.name} 未开启图生视频")
            if self.i2v_input_type == "b64":
                if not req.image_b64:
                    raise RuntimeError("图生视频需要 base64 图片")
                payload[self.i2v_field] = req.image_b64
            else:
                if not req.image_url:
                    raise RuntimeError("图生视频需要可访问图片 URL")
                payload[self.i2v_field] = req.image_url

        data = await self.request_json(
            self.submit_method,
            f"{self.api_base}{self.submit_path}",
            self.api_key,
            payload=payload,
        )
        task_id = _first_non_empty(data, self.task_id_paths)
        if not isinstance(task_id, str) or not task_id:
            task_id = str(task_id or "").strip()
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
        payload = {self.query_task_param: task_id} if self.query_in_body else None
        params = None if self.query_in_body else {self.query_task_param: task_id}
        data = await self.request_json(
            self.query_method,
            f"{self.api_base}{self.query_path}",
            self.api_key,
            payload=payload,
            params=params,
        )

        raw_status = str(_first_non_empty(data, self.status_paths) or "running")
        mapped_status = _map_status(raw_status)

        url_node = _first_non_empty(data, self.video_url_paths)
        video_url = _find_first_url(url_node)
        if not video_url:
            video_url = _find_first_url(data)

        fail_reason = _first_non_empty(data, self.fail_reason_paths)
        if not isinstance(fail_reason, str):
            fail_reason = str(fail_reason or "").strip()

        outputs: list[GenerationOutput] = []
        if video_url:
            outputs.append(GenerationOutput(output_type="video", url=video_url, metadata={"provider": self.name}))

        return GenerationResult(
            provider=self.name,
            kind="video",
            mode="text2video",
            status=mapped_status,
            task_id=task_id,
            outputs=outputs,
            fail_reason=fail_reason,
            metadata={"raw_status": raw_status},
        )
