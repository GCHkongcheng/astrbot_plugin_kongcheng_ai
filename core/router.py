from __future__ import annotations

from typing import Any

try:
    from .schema import GenerationRequest
except ImportError:
    from core.schema import GenerationRequest

try:
    from ..providers.base import BaseProvider
    from ..providers.openai_image import OpenAIImageProvider
    from ..providers.seedance import SeedanceProvider
    from ..providers.zhipu import ZhipuProvider
except ImportError:
    from providers.base import BaseProvider
    from providers.openai_image import OpenAIImageProvider
    from providers.seedance import SeedanceProvider
    from providers.zhipu import ZhipuProvider


class ProviderRouter:
    VIDEO_ALIAS = {
        "zhipu": "zhipu",
        "seedance": "seedance",
        "doubao": "seedance",
        "豆包": "seedance",
    }
    IMAGE_ALIAS = {
        "zhipu": "zhipu",
        "openai": "openai_image",
        "custom": "openai_image",
        "openai_image": "openai_image",
    }

    def __init__(self, request_json, config: dict[str, Any]):
        self.default_video_provider = str(config.get("default_video_provider", "zhipu")).strip()
        self.default_image_provider = str(config.get("default_image_provider", "zhipu")).strip()

        self.providers: dict[str, BaseProvider] = {
            "zhipu": ZhipuProvider(
                request_json,
                {
                    "api_key": config.get("zhipu_api_key", ""),
                    "api_base": config.get("zhipu_api_base", "https://open.bigmodel.cn/api/paas/v4"),
                    "video_model": config.get("zhipu_video_model", "CogVideoX-Flash"),
                    "image_model": config.get("zhipu_image_model", "glm-image"),
                    "video_with_audio": config.get("zhipu_video_with_audio", True),
                },
            ),
            "seedance": SeedanceProvider(
                request_json,
                {
                    "api_key": config.get("seedance_api_key", ""),
                    "api_base": config.get("seedance_api_base", "https://seedanceapi.org/v1"),
                    "video_model": config.get("seedance_video_model", ""),
                    "resolution": config.get("seedance_resolution", "1080p"),
                    "duration": config.get("seedance_duration", 5),
                    "aspect_ratio": config.get("seedance_aspect_ratio", "16:9"),
                    "generate_audio": config.get("seedance_generate_audio", True),
                    "fixed_lens": config.get("seedance_fixed_lens", False),
                    "generate_path": config.get("seedance_generate_path", "/generate"),
                    "status_path": config.get("seedance_status_path", "/status"),
                },
            ),
            "openai_image": OpenAIImageProvider(
                request_json,
                {
                    "api_key": config.get("openai_image_api_key", ""),
                    "api_base": config.get("openai_image_api_base", ""),
                    "generate_path": config.get("openai_image_generate_path", "/images/generations"),
                    "edit_path": config.get("openai_image_edit_path", ""),
                    "image_model": config.get("openai_image_model", "gpt-image-1"),
                },
            ),
        }

    @staticmethod
    def _extract_provider_and_rest(raw: str, aliases: dict[str, str], default_provider: str) -> tuple[str, str]:
        text = (raw or "").strip()
        if not text:
            return default_provider, ""
        first, *rest = text.split(maxsplit=1)
        mapped = aliases.get(first.lower()) or aliases.get(first)
        if mapped:
            return mapped, (rest[0].strip() if rest else "")
        return default_provider, text

    def parse_video_provider(self, raw: str, allow_empty_default: bool = False) -> tuple[str, str]:
        default_provider = "" if allow_empty_default else self.default_video_provider
        return self._extract_provider_and_rest(raw, self.VIDEO_ALIAS, default_provider)

    def parse_image_provider(self, raw: str) -> tuple[str, str]:
        return self._extract_provider_and_rest(raw, self.IMAGE_ALIAS, self.default_image_provider)

    def get_provider(self, provider: str) -> BaseProvider:
        obj = self.providers.get(provider)
        if obj is None:
            raise RuntimeError(f"未知供应商: {provider}")
        return obj

    def validate_request(self, req: GenerationRequest) -> str | None:
        provider = self.providers.get(req.provider)
        if provider is None:
            return f"不支持的供应商: {req.provider}"
        return provider.validate(req.kind, req.mode)

    def enabled_providers(self) -> dict[str, list[str]]:
        video: list[str] = []
        image: list[str] = []

        for name, provider in self.providers.items():
            if provider.validate("video", "text2video") is None:
                video.append("seedance(doubao)" if name == "seedance" else name)
            if provider.validate("image", "text2image") is None:
                image.append("openai" if name == "openai_image" else name)

        return {"video": video, "image": image}
