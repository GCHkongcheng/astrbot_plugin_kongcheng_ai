from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


VIDEO_DONE_STATUSES = {"success", "succeeded", "finished", "done", "completed"}
VIDEO_FAILED_STATUSES = {"fail", "failed", "error", "canceled", "cancelled", "timeout"}
VIDEO_PENDING_STATUSES = {
    "processing",
    "pending",
    "queued",
    "running",
    "submitted",
    "in_progress",
}


@dataclass
class VideoQueryResult:
    status: str
    video_url: str
    fail_reason: str


@register(
    "astrbot_plugin_kongcheng_ai",
    "GCHkongcheng",
    "智谱 AI 视频生成插件（文生视频 / 图生视频）",
    "1.0.1",
)
class KongchengAIVideoPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self._user_last_request_ts: dict[str, float] = {}
        self._http_session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()
        self._reload_config()

    async def initialize(self):
        """插件初始化。"""
        if self.save_video_local:
            self.video_cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("astrbot_plugin_kongcheng_ai 初始化完成。")

    async def terminate(self):
        """插件卸载/停用时回收资源。"""
        async with self._session_lock:
            if self._http_session and not self._http_session.closed:
                await self._http_session.close()
            self._http_session = None
        logger.info("astrbot_plugin_kongcheng_ai 已终止。")

    def _reload_config(self) -> None:
        self.api_key = str(self.config.get("api_key", "")).strip()
        raw_api_base = str(
            self.config.get("api_base", "https://open.bigmodel.cn/api/paas/v4")
        ).strip()
        self.api_base = self._normalize_api_base(raw_api_base)
        self.model = str(self.config.get("model", "CogVideoX-Flash")).strip()
        self.default_image_prompt = str(
            self.config.get("default_image_prompt", "让画面自然地动起来")
        ).strip()
        self.save_video_local = bool(self.config.get("save_video_local", False))
        self.return_video_url = bool(self.config.get("return_video_url", True))
        self.attach_video_result = bool(self.config.get("attach_video_result", True))
        self.request_timeout_seconds = max(
            10, int(self.config.get("request_timeout_seconds", 90))
        )
        self.download_timeout_seconds = max(
            10, int(self.config.get("download_timeout_seconds", 120))
        )
        self.min_request_interval_seconds = max(
            0.0, float(self.config.get("min_request_interval_seconds", 3))
        )
        self.max_image_size_mb = max(1, int(self.config.get("max_image_size_mb", 10)))
        self.max_video_size_mb = max(10, int(self.config.get("max_video_size_mb", 100)))
        self.max_cache_files = max(1, int(self.config.get("max_cache_files", 20)))
        self.video_cache_dir = (
            Path(get_astrbot_data_path()) / "video_cache" / "astrbot_plugin_kongcheng_ai"
        )

    @staticmethod
    def _normalize_api_base(raw_base: str) -> str:
        base = (raw_base or "").strip().rstrip("/")
        if not base:
            return "https://open.bigmodel.cn/api/paas/v4"
        for suffix in ("/videos/generations", "/async-result"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        if "/api/paas/v4" not in base:
            base = f"{base}/api/paas/v4"
        return base.rstrip("/")

    @staticmethod
    def _extract_command_body(event: AstrMessageEvent, command_name: str) -> str:
        text = (event.message_str or "").strip()
        for prefix in (f"/{command_name}", command_name):
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return text

    @staticmethod
    def _safe_task_id(raw_id: str) -> str:
        safe = "".join(ch for ch in raw_id if ch.isalnum() or ch in {"-", "_"})
        return safe[:48] or "video_task"

    @staticmethod
    def _is_image_segment(seg: Any) -> bool:
        image_cls = getattr(Comp, "Image", None)
        if image_cls is not None:
            try:
                if isinstance(seg, image_cls):
                    return True
            except TypeError:
                pass
        return seg.__class__.__name__.lower() == "image"

    @staticmethod
    def _sanitize_error(raw_error: str) -> str:
        msg = (raw_error or "").strip()
        if not msg:
            return "请求失败，请稍后重试。"

        msg = re.sub(
            r"(?i)(api[_-]?key|authorization)\s*[:=]\s*([^\s,;]+)", r"\1=***", msg
        )
        msg = re.sub(r"(?i)bearer\s+[A-Za-z0-9\-._]+", "Bearer ***", msg)

        lower_msg = msg.lower()
        if "401" in lower_msg or "unauthorized" in lower_msg:
            return "认证失败，请检查 API Key 配置。"
        if "403" in lower_msg or "forbidden" in lower_msg:
            return "请求被拒绝，请确认账号权限或额度。"
        if "429" in lower_msg or "rate" in lower_msg:
            return "请求过于频繁，请稍后再试。"
        if "timeout" in lower_msg:
            return "请求超时，请稍后重试。"
        if "model" in lower_msg and "not found" in lower_msg:
            return "模型不可用，请检查模型名配置。"

        if len(msg) > 160:
            msg = msg[:160] + "..."
        return msg

    @staticmethod
    def _extract_api_error(data: Any, raw_text: str, http_status: int) -> str:
        if isinstance(data, dict):
            error_obj = data.get("error")
            if isinstance(error_obj, dict):
                message = str(error_obj.get("message", "")).strip()
                if message:
                    return f"HTTP {http_status}: {message}"
            if isinstance(error_obj, str) and error_obj.strip():
                return f"HTTP {http_status}: {error_obj.strip()}"
            for key in ("message", "msg", "detail"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return f"HTTP {http_status}: {value.strip()}"
        fallback = (raw_text or "").strip()
        if fallback:
            return f"HTTP {http_status}: {fallback[:200]}"
        return f"HTTP {http_status}: 请求失败"

    def _check_rate_limit(self, user_id: str) -> float:
        now_ts = time.time()
        last_ts = self._user_last_request_ts.get(user_id)
        if last_ts is None:
            self._user_last_request_ts[user_id] = now_ts
            return 0.0
        elapsed = now_ts - last_ts
        if elapsed >= self.min_request_interval_seconds:
            self._user_last_request_ts[user_id] = now_ts
            return 0.0
        return self.min_request_interval_seconds - elapsed

    async def _ensure_http_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._http_session is None or self._http_session.closed:
                self._http_session = aiohttp.ClientSession()
            return self._http_session

    async def _download_binary(
        self, source: str, timeout_seconds: int, max_bytes: int
    ) -> bytes:
        if source.startswith(("http://", "https://")):
            session = await self._ensure_http_session()
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with session.get(source, timeout=timeout) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}")
                content = await resp.read()
                if not content:
                    raise RuntimeError("下载内容为空")
                if len(content) > max_bytes:
                    raise RuntimeError(
                        f"文件过大（>{max_bytes // 1024 // 1024}MB），已拒绝处理"
                    )
                return content

        path = Path(source)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError("图片路径不存在")
        content = await asyncio.to_thread(path.read_bytes)
        if len(content) > max_bytes:
            raise RuntimeError(f"文件过大（>{max_bytes // 1024 // 1024}MB）")
        return content

    async def _extract_first_image_base64(self, event: AstrMessageEvent) -> str:
        for seg in event.get_messages():
            if not self._is_image_segment(seg):
                continue
            source = (
                getattr(seg, "url", None)
                or getattr(seg, "file", None)
                or getattr(seg, "path", None)
            )
            if not source:
                continue
            image_bytes = await self._download_binary(
                source=source,
                timeout_seconds=self.request_timeout_seconds,
                max_bytes=self.max_image_size_mb * 1024 * 1024,
            )
            return base64.b64encode(image_bytes).decode("utf-8")
        raise ValueError("消息中没有检测到图片")

    async def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        session = await self._ensure_http_session()
        timeout = aiohttp.ClientTimeout(total=timeout_seconds or self.request_timeout_seconds)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with session.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=payload,
            timeout=timeout,
        ) as resp:
            raw_text = await resp.text()
            data: Any
            try:
                data = json.loads(raw_text) if raw_text else {}
            except json.JSONDecodeError:
                data = {}
            if resp.status >= 400:
                raise RuntimeError(self._extract_api_error(data, raw_text, resp.status))
            if not isinstance(data, dict):
                raise RuntimeError("接口返回格式异常")
            return data

    async def _submit_video_generation(self, prompt: str, image_b64: str | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "with_audio": True,
        }
        if image_b64:
            payload["image_url"] = image_b64

        url = f"{self.api_base}/videos/generations"
        data = await self._request_json("POST", url, payload=payload)
        task_id = str(data.get("id", "")).strip()
        if not task_id:
            raise RuntimeError("提交成功但未返回任务 ID")
        return task_id

    @staticmethod
    def _extract_video_url(data: Any) -> str:
        if isinstance(data, str) and data.startswith(("http://", "https://")):
            return data
        if isinstance(data, dict):
            for key in ("url", "video_url", "download_url"):
                candidate = data.get(key)
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    return candidate
            for value in data.values():
                url = KongchengAIVideoPlugin._extract_video_url(value)
                if url:
                    return url
        if isinstance(data, list):
            for item in data:
                url = KongchengAIVideoPlugin._extract_video_url(item)
                if url:
                    return url
        return ""

    @staticmethod
    def _extract_fail_reason(data: dict[str, Any]) -> str:
        for key in ("error", "message", "msg", "reason", "fail_reason"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested_msg = value.get("message")
                if isinstance(nested_msg, str) and nested_msg.strip():
                    return nested_msg.strip()
        return ""

    @staticmethod
    def _looks_pending(text: str) -> bool:
        lower = (text or "").lower()
        keywords = ("processing", "pending", "running", "queue", "处理中", "排队")
        return any(k in lower for k in keywords)

    async def _query_video_result(self, task_id: str) -> VideoQueryResult:
        url = f"{self.api_base}/async-result/{task_id}"
        data = await self._request_json("GET", url)

        raw_status = str(data.get("task_status") or data.get("status") or "").strip().lower()
        video_url = self._extract_video_url(data.get("video_result", data))
        fail_reason = self._extract_fail_reason(data)

        if not raw_status:
            if video_url:
                raw_status = "success"
            elif self._looks_pending(fail_reason):
                raw_status = "processing"
                fail_reason = ""
            else:
                raw_status = "processing"

        return VideoQueryResult(status=raw_status, video_url=video_url, fail_reason=fail_reason)

    async def _download_video_to_cache(self, video_url: str, task_id: str) -> Path:
        self.video_cache_dir.mkdir(parents=True, exist_ok=True)
        video_bytes = await self._download_binary(
            source=video_url,
            timeout_seconds=self.download_timeout_seconds,
            max_bytes=self.max_video_size_mb * 1024 * 1024,
        )
        filename = f"{self._safe_task_id(task_id)}_{int(time.time())}.mp4"
        target = self.video_cache_dir / filename
        await asyncio.to_thread(target.write_bytes, video_bytes)
        await self._trim_video_cache()
        return target

    async def _trim_video_cache(self) -> None:
        files = await asyncio.to_thread(
            lambda: sorted(
                [p for p in self.video_cache_dir.glob("*") if p.is_file()],
                key=lambda p: p.stat().st_mtime,
            )
        )
        overflow = max(0, len(files) - self.max_cache_files)
        for path in files[:overflow]:
            try:
                await asyncio.to_thread(path.unlink)
            except Exception as exc:
                logger.warning(f"清理缓存文件失败: {path} -> {exc}")

    @staticmethod
    def _status_text(status: str) -> str:
        mapping = {
            "processing": "处理中",
            "pending": "排队中",
            "queued": "排队中",
            "running": "处理中",
            "submitted": "已提交",
            "success": "已完成",
            "succeeded": "已完成",
            "finished": "已完成",
            "done": "已完成",
            "completed": "已完成",
            "fail": "失败",
            "failed": "失败",
            "error": "失败",
            "canceled": "已取消",
            "cancelled": "已取消",
            "timeout": "超时",
        }
        return mapping.get(status, f"未知状态({status})")

    @filter.command("kc视频")
    async def create_text_video(self, event: AstrMessageEvent):
        """文生视频：/kc视频 <提示词>"""
        self._reload_config()

        prompt = self._extract_command_body(event, "kc视频")
        if not prompt:
            yield event.plain_result("请提供提示词，例如：/kc视频 一只猫在雨夜霓虹街道散步")
            return
        if not self.api_key:
            yield event.plain_result("请先在插件配置中填写 `api_key`。")
            return

        wait_seconds = self._check_rate_limit(str(event.get_sender_id()))
        if wait_seconds > 0:
            yield event.plain_result(f"请求过快，请在 {wait_seconds:.1f} 秒后再试。")
            return

        try:
            task_id = await self._submit_video_generation(prompt=prompt)
            yield event.plain_result(
                "任务已提交。\n"
                f"- task_id: {task_id}\n"
                f"- 查询命令: /kc视频查询 {task_id}"
            )
        except Exception as exc:
            logger.error(f"文生视频提交失败: {exc}")
            yield event.plain_result(f"提交失败：{self._sanitize_error(str(exc))}")

    @filter.command("kc图生视频")
    async def create_image_video(self, event: AstrMessageEvent):
        """图生视频：/kc图生视频 [提示词] + 图片"""
        self._reload_config()

        prompt = self._extract_command_body(event, "kc图生视频") or self.default_image_prompt
        if not self.api_key:
            yield event.plain_result("请先在插件配置中填写 `api_key`。")
            return

        wait_seconds = self._check_rate_limit(str(event.get_sender_id()))
        if wait_seconds > 0:
            yield event.plain_result(f"请求过快，请在 {wait_seconds:.1f} 秒后再试。")
            return

        try:
            image_b64 = await self._extract_first_image_base64(event)
        except Exception as exc:
            yield event.plain_result(f"读取图片失败：{self._sanitize_error(str(exc))}")
            return

        try:
            task_id = await self._submit_video_generation(prompt=prompt, image_b64=image_b64)
            yield event.plain_result(
                "图生视频任务已提交。\n"
                f"- task_id: {task_id}\n"
                f"- 查询命令: /kc视频查询 {task_id}"
            )
        except Exception as exc:
            logger.error(f"图生视频提交失败: {exc}")
            yield event.plain_result(f"提交失败：{self._sanitize_error(str(exc))}")

    @filter.command("kc视频查询")
    async def query_video(self, event: AstrMessageEvent):
        """查询视频任务：/kc视频查询 <task_id>"""
        self._reload_config()

        raw = self._extract_command_body(event, "kc视频查询")
        task_id = raw.split()[0] if raw else ""
        if not task_id:
            yield event.plain_result("请提供 task_id，例如：/kc视频查询 1234567890")
            return
        if not self.api_key:
            yield event.plain_result("请先在插件配置中填写 `api_key`。")
            return

        try:
            result = await self._query_video_result(task_id)
        except Exception as exc:
            logger.error(f"查询视频任务失败: {exc}")
            yield event.plain_result(f"查询失败：{self._sanitize_error(str(exc))}")
            return

        status_text = self._status_text(result.status)

        if result.status in VIDEO_PENDING_STATUSES:
            yield event.plain_result(
                f"任务状态：{status_text}\n请稍后重试：/kc视频查询 {task_id}"
            )
            return

        if result.status in VIDEO_FAILED_STATUSES:
            reason = (
                self._sanitize_error(result.fail_reason)
                if result.fail_reason
                else "无详细错误信息"
            )
            yield event.plain_result(f"任务状态：{status_text}\n失败原因：{reason}")
            return

        if result.status in VIDEO_DONE_STATUSES:
            lines = [f"任务状态：{status_text}"]
            if self.return_video_url and result.video_url:
                lines.append(f"视频地址：{result.video_url}")

            if self.save_video_local and result.video_url:
                try:
                    local_path = await self._download_video_to_cache(result.video_url, task_id)
                    lines.append(f"本地缓存：{local_path}")
                except Exception as exc:
                    logger.warning(f"保存视频缓存失败: {exc}")
                    lines.append(f"本地缓存失败：{self._sanitize_error(str(exc))}")

            chain: list[Any] = [Comp.Plain("\n".join(lines))]
            if self.attach_video_result and result.video_url:
                try:
                    chain.append(Comp.Video.fromURL(url=result.video_url))
                except Exception as exc:
                    logger.warning(f"构建视频消息失败: {exc}")

            yield event.chain_result(chain)
            return

        yield event.plain_result(
            f"任务状态：{status_text}\n"
            f"如状态异常，可稍后再次查询：/kc视频查询 {task_id}"
        )

    @filter.command("kc视频帮助")
    async def video_help(self, event: AstrMessageEvent):
        """查看插件帮助。"""
        help_text = (
            "Kongcheng AI 视频插件命令：\n"
            "1. /kc视频 <提示词>\n"
            "2. /kc图生视频 [提示词] + 图片\n"
            "3. /kc视频查询 <task_id>\n\n"
            "示例：\n"
            "- /kc视频 赛博朋克城市夜景，镜头缓慢推进\n"
            "- /kc图生视频 让角色微笑并挥手（同时发送一张图片）\n"
            "- /kc视频查询 1234567890\n\n"
            "提示：\n"
            "- 接口默认 base_url 为 https://open.bigmodel.cn/api/paas/v4\n"
            "- 如果开启 save_video_local，会把视频缓存到 data/video_cache/astrbot_plugin_kongcheng_ai/\n"
            "- 该插件默认模型为 CogVideoX-Flash，可在配置中修改。"
        )
        yield event.plain_result(help_text)
