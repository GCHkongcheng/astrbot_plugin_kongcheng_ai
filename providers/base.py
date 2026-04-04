from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

try:
    from ..core.schema import GenerationRequest, GenerationResult
except ImportError:
    from core.schema import GenerationRequest, GenerationResult

RequestJsonFn = Callable[..., Awaitable[dict[str, Any]]]


class BaseProvider(ABC):
    name: str = ""

    def __init__(self, request_json: RequestJsonFn):
        self.request_json = request_json

    @abstractmethod
    def supports_mode(self, mode: str) -> bool:
        pass

    @abstractmethod
    def validate(self, kind: str, mode: str) -> str | None:
        pass

    @abstractmethod
    async def submit(self, req: GenerationRequest) -> GenerationResult:
        pass

    async def query_video(self, task_id: str) -> GenerationResult:
        raise RuntimeError(f"provider {self.name} does not support video query")
