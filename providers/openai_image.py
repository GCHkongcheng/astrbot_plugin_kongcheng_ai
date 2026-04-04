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


class OpenAIImageProvider(BaseProvider):
    name = "openai_image"

    def __init__(self, request_json, config: dict[str, Any]):
        super().__init__(request_json)
        self.api_key = str(config.get("api_key", "")).strip()
        self.api_base = str(config.get("api_base", "")).strip().rstrip("/")
        self.generate_path = str(config.get("generate_path", "/images/generations")).strip()
        self.edit_path = str(config.get("edit_path", "")).strip()
        self.image_model = str(config.get("image_model", "gpt-image-1")).strip()
        if self.generate_path and not self.generate_path.startswith("/"):
            self.generate_path = "/" + self.generate_path
        if self.edit_path and not self.edit_path.startswith("/"):
            self.edit_path = "/" + self.edit_path

    def supports_mode(self, mode: str) -> bool:
        if mode == "text2image":
            return True
        if mode == "image2image" and self.edit_path:
            return True
        return False

    def validate(self, kind: str, mode: str) -> str | None:
        if kind != "image":
            return f"供应商 {self.name} 暂不支持 {kind}"
        if not self.supports_mode(mode):
            return f"供应商 {self.name} 不支持模式: {mode}"
        if not self.api_key:
            return "未配置 openai_image_api_key。"
        if not self.api_base:
            return "未配置 openai_image_api_base。"
        return None

    async def submit(self, req: GenerationRequest) -> GenerationResult:
        if req.mode == "image2image":
            raise RuntimeError("当前 openai_image 图生图尚未启用（请配置支持图生图的 provider 或扩展 edit 接口）")

        payload = {
            "model": self.image_model,
            "prompt": req.prompt,
            "size": req.size,
        }
        data = await self.request_json(
            "POST",
            f"{self.api_base}{self.generate_path}",
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
