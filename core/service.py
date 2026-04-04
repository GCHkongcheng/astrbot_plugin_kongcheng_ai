from __future__ import annotations

from typing import Awaitable, Callable

try:
    from .router import ProviderRouter
    from .schema import GenerationRequest, GenerationResult
except ImportError:
    from core.router import ProviderRouter
    from core.schema import GenerationRequest, GenerationResult

SaveTaskProviderFn = Callable[[str, str], Awaitable[None]]
LoadTaskProviderFn = Callable[[str], Awaitable[str]]


class GenerationService:
    def __init__(
        self,
        router: ProviderRouter,
        save_task_provider: SaveTaskProviderFn,
        load_task_provider: LoadTaskProviderFn,
    ):
        self.router = router
        self.save_task_provider = save_task_provider
        self.load_task_provider = load_task_provider

    async def create(self, req: GenerationRequest) -> GenerationResult:
        error = self.router.validate_request(req)
        if error:
            raise RuntimeError(error)
        provider = self.router.get_provider(req.provider)
        result = await provider.submit(req)
        if result.kind == "video" and result.task_id:
            await self.save_task_provider(result.task_id, result.provider)
        return result

    async def query_video(self, task_id: str, provider: str = "") -> GenerationResult:
        resolved_provider = provider or await self.load_task_provider(task_id)
        req = GenerationRequest(
            provider=resolved_provider,
            kind="video",
            mode="text2video",
        )
        error = self.router.validate_request(req)
        if error:
            raise RuntimeError(error)
        provider_obj = self.router.get_provider(resolved_provider)
        return await provider_obj.query_video(task_id)
