from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

try:
    from .core.router import ProviderRouter
    from .core.schema import GenerationRequest
    from .core.service import GenerationService
except ImportError:
    from core.router import ProviderRouter
    from core.schema import GenerationRequest
    from core.service import GenerationService

IMAGE_SIZE_RE = re.compile(r"^\d{2,5}x\d{2,5}$", re.IGNORECASE)
TASK_PROVIDER_KV_PREFIX = "kc_video_task_provider:"


@register(
    "astrbot_plugin_kongcheng_ai",
    "GCHkongcheng",
    "多供应商 AI 生图/视频插件",
    "1.3.0",
)
class KongchengAIVideoPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self._http_session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()
        self._user_last_ts: dict[str, float] = {}
        self._reload_config()

    async def initialize(self):
        if self.save_video_local:
            self.video_cache_dir.mkdir(parents=True, exist_ok=True)
        if self.save_image_local:
            self.image_cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("astrbot_plugin_kongcheng_ai initialized")

    async def terminate(self):
        async with self._session_lock:
            if self._http_session and not self._http_session.closed:
                await self._http_session.close()
            self._http_session = None

    def _reload_config(self) -> None:
        legacy_api_key = str(self.config.get("api_key", "")).strip()
        legacy_api_base = str(self.config.get("api_base", "https://open.bigmodel.cn/api/paas/v4")).strip()
        legacy_video_model = str(self.config.get("model", "CogVideoX-Flash")).strip()
        legacy_image_model = str(self.config.get("image_model", "glm-image")).strip()

        zhipu_api_base = self._normalize_zhipu_api_base(
            str(self.config.get("zhipu_api_base", legacy_api_base)).strip()
        )

        self.normalized_config: dict[str, Any] = {
            "default_video_provider": str(self.config.get("default_video_provider", "zhipu")).strip(),
            "default_image_provider": str(self.config.get("default_image_provider", "zhipu")).strip(),
            "zhipu_api_key": str(self.config.get("zhipu_api_key", legacy_api_key)).strip(),
            "zhipu_api_base": zhipu_api_base,
            "zhipu_video_model": str(self.config.get("zhipu_video_model", legacy_video_model)).strip(),
            "zhipu_image_model": str(self.config.get("zhipu_image_model", legacy_image_model)).strip(),
            "zhipu_video_with_audio": bool(self.config.get("zhipu_video_with_audio", True)),
            "seedance_api_key": str(self.config.get("seedance_api_key", "")).strip(),
            "seedance_api_base": str(self.config.get("seedance_api_base", "https://seedanceapi.org/v1")).strip().rstrip("/"),
            "seedance_video_model": str(self.config.get("seedance_video_model", "")).strip(),
            "seedance_resolution": str(self.config.get("seedance_resolution", "1080p")).strip(),
            "seedance_duration": int(self.config.get("seedance_duration", 5)),
            "seedance_aspect_ratio": str(self.config.get("seedance_aspect_ratio", "16:9")).strip(),
            "seedance_generate_audio": bool(self.config.get("seedance_generate_audio", True)),
            "seedance_fixed_lens": bool(self.config.get("seedance_fixed_lens", False)),
            "seedance_generate_path": str(self.config.get("seedance_generate_path", "/generate")).strip(),
            "seedance_status_path": str(self.config.get("seedance_status_path", "/status")).strip(),
            "openai_image_api_key": str(self.config.get("openai_image_api_key", "")).strip(),
            "openai_image_api_base": str(self.config.get("openai_image_api_base", "")).strip().rstrip("/"),
            "openai_image_generate_path": str(self.config.get("openai_image_generate_path", "/images/generations")).strip(),
            "openai_image_edit_path": str(self.config.get("openai_image_edit_path", "")).strip(),
            "openai_image_model": str(self.config.get("openai_image_model", "gpt-image-1")).strip(),
        }

        self.default_image_size = str(self.config.get("default_image_size", "1024x1024")).strip()
        self.default_i2v_prompt = str(self.config.get("default_i2v_prompt", self.config.get("default_image_prompt", "让画面自然地动起来"))).strip()
        self.default_i2i_prompt = str(self.config.get("default_i2i_prompt", "保持主体结构，优化细节和质感")).strip()
        self.request_timeout_seconds = max(10, int(self.config.get("request_timeout_seconds", 90)))
        self.download_timeout_seconds = max(10, int(self.config.get("download_timeout_seconds", 120)))
        self.request_retry_count = max(0, int(self.config.get("request_retry_count", 1)))
        self.min_request_interval_seconds = max(0.0, float(self.config.get("min_request_interval_seconds", 3)))
        self.max_image_size_mb = max(1, int(self.config.get("max_image_size_mb", 10)))
        self.max_video_size_mb = max(10, int(self.config.get("max_video_size_mb", 100)))
        self.max_cache_files = max(1, int(self.config.get("max_cache_files", 20)))
        self.return_video_url = bool(self.config.get("return_video_url", True))
        self.return_image_url = bool(self.config.get("return_image_url", True))
        self.attach_video_result = bool(self.config.get("attach_video_result", True))
        self.attach_image_result = bool(self.config.get("attach_image_result", True))
        self.save_video_local = bool(self.config.get("save_video_local", False))
        self.save_image_local = bool(self.config.get("save_image_local", False))

        data_root = Path(get_astrbot_data_path())
        self.video_cache_dir = data_root / "video_cache" / "astrbot_plugin_kongcheng_ai"
        self.image_cache_dir = data_root / "image_cache" / "astrbot_plugin_kongcheng_ai"

        self.router = ProviderRouter(self._request_json, self.normalized_config)
        self.service = GenerationService(self.router, self._save_task_provider, self._load_task_provider)

    @staticmethod
    def _normalize_zhipu_api_base(raw_base: str) -> str:
        base = (raw_base or "").strip().rstrip("/")
        if not base:
            return "https://open.bigmodel.cn/api/paas/v4"
        if "/api/paas/v4" not in base:
            base = f"{base}/api/paas/v4"
        for suffix in ("/videos/generations", "/images/generations", "/async-result"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base.rstrip("/")

    @staticmethod
    def _extract_command_body(event: AstrMessageEvent, command_name: str) -> str:
        text = (event.message_str or "").strip()
        for prefix in (f"/{command_name}", command_name):
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text

    @staticmethod
    def _safe_task_id(raw_id: str) -> str:
        safe = "".join(ch for ch in raw_id if ch.isalnum() or ch in {"-", "_"})
        return safe[:48] or "task"

    @staticmethod
    def _sanitize_error(err: str) -> str:
        msg = (err or "").strip()
        msg = re.sub(r"(?i)(api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+", r"\1=***", msg)
        msg = re.sub(r"(?i)bearer\s+[A-Za-z0-9\-._]+", "Bearer ***", msg)
        return msg[:180] + ("..." if len(msg) > 180 else "")

    def _check_rate_limit(self, user_id: str) -> float:
        now = time.time()
        prev = self._user_last_ts.get(user_id)
        self._user_last_ts[user_id] = now
        if prev is None:
            return 0.0
        delta = now - prev
        if delta >= self.min_request_interval_seconds:
            return 0.0
        return self.min_request_interval_seconds - delta

    async def _ensure_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
            return self._http_session

    async def _request_json(
        self,
        method: str,
        url: str,
        api_key: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self._ensure_session()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        attempts = self.request_retry_count + 1
        last_error: Exception | None = None
        for idx in range(attempts):
            try:
                async with session.request(
                    method.upper(),
                    url,
                    headers=headers,
                    json=payload,
                    params=params,
                    timeout=timeout,
                ) as resp:
                    raw = await resp.text()
                    try:
                        data = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        data = {}

                    if resp.status >= 500 and idx < attempts - 1:
                        await asyncio.sleep(0.3 * (idx + 1))
                        continue
                    if resp.status >= 400:
                        raise RuntimeError(f"HTTP {resp.status}: {raw[:200]}")
                    if not isinstance(data, dict):
                        raise RuntimeError("接口返回格式异常")
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
                last_error = exc
                if idx >= attempts - 1:
                    break
                await asyncio.sleep(0.3 * (idx + 1))

        raise RuntimeError(str(last_error) if last_error else "请求失败")

    async def _extract_image_inputs(self, event: AstrMessageEvent) -> tuple[str, str]:
        for seg in event.get_messages():
            if seg.__class__.__name__.lower() != "image":
                continue
            source = getattr(seg, "url", None) or getattr(seg, "file", None) or getattr(seg, "path", None)
            if not isinstance(source, str) or not source:
                continue
            image_url = source if source.startswith(("http://", "https://")) else ""
            data = await self._download_binary(source, self.max_image_size_mb * 1024 * 1024)
            image_b64 = base64.b64encode(data).decode("utf-8")
            return image_b64, image_url
        raise ValueError("消息中没有检测到图片")

    async def _download_binary(self, source: str, max_bytes: int) -> bytes:
        if source.startswith(("http://", "https://")):
            session = await self._ensure_session()
            async with session.get(source, timeout=aiohttp.ClientTimeout(total=self.download_timeout_seconds)) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}")
                data = await resp.read()
        else:
            data = await asyncio.to_thread(Path(source).read_bytes)

        if not data:
            raise RuntimeError("下载内容为空")
        if len(data) > max_bytes:
            raise RuntimeError(f"文件过大（>{max_bytes // 1024 // 1024}MB）")
        return data

    async def _trim_cache_dir(self, cache_dir: Path) -> None:
        files = await asyncio.to_thread(
            lambda: sorted(
                [item for item in cache_dir.glob("*") if item.is_file()],
                key=lambda item: item.stat().st_mtime,
            )
        )
        overflow = max(0, len(files) - self.max_cache_files)
        for path in files[:overflow]:
            try:
                await asyncio.to_thread(path.unlink)
            except Exception:
                pass

    async def _save_remote_to_cache(
        self,
        url: str,
        cache_dir: Path,
        prefix: str,
        max_bytes: int,
    ) -> Path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        data = await self._download_binary(url, max_bytes=max_bytes)
        ext = Path(urlparse(url).path).suffix or ".bin"
        if len(ext) > 8:
            ext = ".bin"
        target = cache_dir / f"{self._safe_task_id(prefix)}_{int(time.time())}{ext}"
        await asyncio.to_thread(target.write_bytes, data)
        await self._trim_cache_dir(cache_dir)
        return target

    async def _save_task_provider(self, task_id: str, provider: str) -> None:
        try:
            await self.put_kv_data(f"{TASK_PROVIDER_KV_PREFIX}{task_id}", provider)
        except Exception:
            pass

    async def _load_task_provider(self, task_id: str) -> str:
        try:
            value = await self.get_kv_data(
                f"{TASK_PROVIDER_KV_PREFIX}{task_id}",
                self.normalized_config["default_video_provider"],
            )
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            pass
        return self.normalized_config["default_video_provider"]

    @staticmethod
    def _split_prompt_and_size(text: str, default_size: str) -> tuple[str, str]:
        raw = (text or "").strip()
        if not raw:
            return "", default_size
        first, *rest = raw.split(maxsplit=1)
        if IMAGE_SIZE_RE.match(first):
            return (rest[0].strip() if rest else "", first.lower())
        return raw, default_size

    @filter.command("kc生图")
    async def create_image(self, event: AstrMessageEvent):
        self._reload_config()
        provider, body = self.router.parse_image_provider(self._extract_command_body(event, "kc生图"))
        prompt, size = self._split_prompt_and_size(body, self.default_image_size)
        if not prompt:
            yield event.plain_result("用法：/kc生图 [zhipu|openai] [1024x1024] <提示词>")
            return
        if not IMAGE_SIZE_RE.match(size):
            yield event.plain_result("尺寸格式错误，示例：1024x1024")
            return

        wait = self._check_rate_limit(str(event.get_sender_id()))
        if wait > 0:
            yield event.plain_result(f"请求过快，请在 {wait:.1f} 秒后再试。")
            return

        request = GenerationRequest(
            provider=provider,
            kind="image",
            mode="text2image",
            prompt=prompt,
            size=size,
        )
        try:
            result = await self.service.create(request)
        except Exception as exc:
            yield event.plain_result(f"生图失败：{self._sanitize_error(str(exc))}")
            return

        urls = [item.url for item in result.outputs if item.output_type == "image" and item.url]
        lines = [f"生图完成，供应商：{result.provider}，共 {len(urls)} 张"]
        if self.return_image_url:
            lines.extend([f"{idx}. {url}" for idx, url in enumerate(urls, 1)])

        if self.save_image_local:
            for idx, url in enumerate(urls, 1):
                try:
                    local = await self._save_remote_to_cache(
                        url=url,
                        cache_dir=self.image_cache_dir,
                        prefix=f"{event.message_obj.message_id or event.get_sender_id()}_{idx}",
                        max_bytes=self.max_image_size_mb * 1024 * 1024,
                    )
                    lines.append(f"缓存{idx}: {local}")
                except Exception as exc:
                    lines.append(f"缓存{idx}失败: {self._sanitize_error(str(exc))}")

        chain: list[Any] = [Comp.Plain("\n".join(lines))]
        if self.attach_image_result:
            for url in urls:
                chain.append(Comp.Image.fromURL(url))
        yield event.chain_result(chain)

    @filter.command("kc图生图")
    async def create_i2i(self, event: AstrMessageEvent):
        self._reload_config()
        provider, body = self.router.parse_image_provider(self._extract_command_body(event, "kc图生图"))
        prompt, size = self._split_prompt_and_size(body, self.default_image_size)
        prompt = prompt or self.default_i2i_prompt
        if not IMAGE_SIZE_RE.match(size):
            yield event.plain_result("尺寸格式错误，示例：1024x1024")
            return

        wait = self._check_rate_limit(str(event.get_sender_id()))
        if wait > 0:
            yield event.plain_result(f"请求过快，请在 {wait:.1f} 秒后再试。")
            return

        try:
            image_b64, image_url = await self._extract_image_inputs(event)
            request = GenerationRequest(
                provider=provider,
                kind="image",
                mode="image2image",
                prompt=prompt,
                size=size,
                image_b64=image_b64,
                image_url=image_url,
            )
            result = await self.service.create(request)
        except Exception as exc:
            yield event.plain_result(f"图生图失败：{self._sanitize_error(str(exc))}")
            return

        urls = [item.url for item in result.outputs if item.output_type == "image" and item.url]
        lines = [f"图生图完成，供应商：{result.provider}，共 {len(urls)} 张"]
        if self.return_image_url:
            lines.extend([f"{idx}. {url}" for idx, url in enumerate(urls, 1)])

        chain: list[Any] = [Comp.Plain("\n".join(lines))]
        if self.attach_image_result:
            for url in urls:
                chain.append(Comp.Image.fromURL(url))
        yield event.chain_result(chain)

    @filter.command("kc视频")
    async def create_video(self, event: AstrMessageEvent):
        self._reload_config()
        provider, prompt = self.router.parse_video_provider(self._extract_command_body(event, "kc视频"))
        if not prompt:
            yield event.plain_result("用法：/kc视频 [zhipu|seedance] <提示词>")
            return

        wait = self._check_rate_limit(str(event.get_sender_id()))
        if wait > 0:
            yield event.plain_result(f"请求过快，请在 {wait:.1f} 秒后再试。")
            return

        request = GenerationRequest(
            provider=provider,
            kind="video",
            mode="text2video",
            prompt=prompt,
        )
        try:
            result = await self.service.create(request)
        except Exception as exc:
            yield event.plain_result(f"提交失败：{self._sanitize_error(str(exc))}")
            return

        yield event.plain_result(
            f"任务已提交。\n"
            f"- provider: {result.provider}\n"
            f"- task_id: {result.task_id}\n"
            f"- 查询: /kc视频查询 {result.task_id}"
        )

    @filter.command("kc图生视频")
    async def create_i2v(self, event: AstrMessageEvent):
        self._reload_config()
        provider, prompt = self.router.parse_video_provider(self._extract_command_body(event, "kc图生视频"))
        prompt = prompt or self.default_i2v_prompt

        wait = self._check_rate_limit(str(event.get_sender_id()))
        if wait > 0:
            yield event.plain_result(f"请求过快，请在 {wait:.1f} 秒后再试。")
            return

        try:
            image_b64, image_url = await self._extract_image_inputs(event)
            request = GenerationRequest(
                provider=provider,
                kind="video",
                mode="image2video",
                prompt=prompt,
                image_b64=image_b64,
                image_url=image_url,
            )
            result = await self.service.create(request)
        except Exception as exc:
            yield event.plain_result(f"提交失败：{self._sanitize_error(str(exc))}")
            return

        yield event.plain_result(
            f"图生视频任务已提交。\n"
            f"- provider: {result.provider}\n"
            f"- task_id: {result.task_id}\n"
            f"- 查询: /kc视频查询 {result.provider} {result.task_id}"
        )

    @filter.command("kc视频查询")
    async def query_video(self, event: AstrMessageEvent):
        self._reload_config()
        raw = self._extract_command_body(event, "kc视频查询")
        provider, rest = self.router.parse_video_provider(raw, allow_empty_default=True)
        task_id = rest.split()[0] if provider else (raw.split()[0] if raw else "")

        if not task_id:
            yield event.plain_result("用法：/kc视频查询 [zhipu|seedance] <task_id>")
            return

        try:
            result = await self.service.query_video(task_id=task_id, provider=provider)
        except Exception as exc:
            yield event.plain_result(f"查询失败：{self._sanitize_error(str(exc))}")
            return

        if result.status in {"pending", "running"}:
            yield event.plain_result(f"任务状态：处理中\n供应商：{result.provider}\n请稍后重试。")
            return

        if result.status in {"failed", "timeout"}:
            reason = result.fail_reason or "无详细错误信息"
            yield event.plain_result(
                f"任务状态：失败\n供应商：{result.provider}\n原因：{self._sanitize_error(reason)}"
            )
            return

        if result.status == "success":
            video_url = result.first_url("video")
            lines = ["任务状态：完成", f"供应商：{result.provider}"]
            if self.return_video_url and video_url:
                lines.append(f"视频地址：{video_url}")
            if self.save_video_local and video_url:
                try:
                    local = await self._save_remote_to_cache(
                        url=video_url,
                        cache_dir=self.video_cache_dir,
                        prefix=task_id,
                        max_bytes=self.max_video_size_mb * 1024 * 1024,
                    )
                    lines.append(f"本地缓存：{local}")
                except Exception as exc:
                    lines.append(f"本地缓存失败：{self._sanitize_error(str(exc))}")

            chain: list[Any] = [Comp.Plain("\n".join(lines))]
            if self.attach_video_result and video_url:
                chain.append(Comp.Video.fromURL(video_url))
            yield event.chain_result(chain)
            return

        raw_status = result.metadata.get("raw_status", "")
        yield event.plain_result(
            f"任务状态：{result.status or 'unknown'}\n"
            f"供应商：{result.provider}\n"
            f"原始状态：{raw_status}"
        )

    @filter.command("kc视频帮助")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "命令：\n"
            "1. /kc生图 [zhipu|openai] [尺寸] 提示词\n"
            "2. /kc图生图 [zhipu|openai] [尺寸] [提示词] + 图片\n"
            "3. /kc视频 [zhipu|seedance] 提示词\n"
            "4. /kc图生视频 [zhipu|seedance] [提示词] + 图片\n"
            "5. /kc视频查询 [zhipu|seedance] task_id\n"
            "6. /kc供应商\n\n"
            "示例：\n"
            "- /kc视频 seedance 一艘飞船穿越云层\n"
            "- /kc图生视频 doubao 让人物微笑并挥手\n"
            "- /kc生图 openai 1024x1024 一只机械猫"
        )

    @filter.command("kc供应商")
    async def list_providers(self, event: AstrMessageEvent):
        self._reload_config()
        enabled = self.router.enabled_providers()
        text = (
            f"默认视频供应商: {self.router.default_video_provider}\n"
            f"默认生图供应商: {self.router.default_image_provider}\n"
            f"可用视频供应商: {', '.join(enabled['video']) if enabled['video'] else '无'}\n"
            f"可用生图供应商: {', '.join(enabled['image']) if enabled['image'] else '无'}"
        )
        yield event.plain_result(text)
