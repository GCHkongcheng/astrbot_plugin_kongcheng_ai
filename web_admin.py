from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from astrbot.api import logger

try:
    import hypercorn.asyncio
    from hypercorn.config import Config
    from quart import Quart, jsonify, request, send_file

    WEB_ADMIN_AVAILABLE = True
except ImportError:
    WEB_ADMIN_AVAILABLE = False


class KongchengWebAdmin:
    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.app: Quart | None = None
        self._server_task: asyncio.Task | None = None
        self._shutdown_event: asyncio.Event | None = None
        self.host = "127.0.0.1"
        self.port = 8765
        self.base_url = "http://127.0.0.1:8765"

        if WEB_ADMIN_AVAILABLE:
            self._create_app()

    @property
    def running(self) -> bool:
        return bool(self._server_task and not self._server_task.done())

    def _create_app(self) -> None:
        if not WEB_ADMIN_AVAILABLE:
            return

        app = Quart(__name__)

        @app.get("/")
        async def index():
            page = Path(__file__).resolve().parent / "admin" / "index.html"
            if page.exists():
                return await send_file(str(page))
            return "Kongcheng AI WebUI not found", 404

        @app.get("/api/ping")
        async def ping():
            return jsonify({"ok": True})

        @app.get("/api/state")
        async def api_state():
            try:
                state = await self.plugin.get_webui_state()
                return jsonify({"ok": True, "data": state})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 500

        @app.post("/api/runtime-config")
        async def api_runtime_config():
            try:
                payload = await request.get_json(force=True) or {}
                state = await self.plugin.apply_webui_runtime_config(payload)
                return jsonify({"ok": True, "data": state})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @app.post("/api/persist-config")
        async def api_persist_config():
            try:
                payload = await request.get_json(force=True) or {}
                state = await self.plugin.persist_webui_config(payload)
                return jsonify({"ok": True, "data": state})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @app.post("/api/test/image")
        async def api_test_image():
            try:
                payload = await request.get_json(force=True) or {}
                prompt = str(payload.get("prompt", "")).strip()
                size = str(payload.get("size", "1024x1024")).strip()
                if not prompt:
                    return jsonify({"ok": False, "error": "prompt 不能为空"}), 400
                data = await self.plugin.webui_test_image(prompt=prompt, size=size)
                return jsonify({"ok": True, "data": data})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @app.post("/api/test/video")
        async def api_test_video():
            try:
                payload = await request.get_json(force=True) or {}
                prompt = str(payload.get("prompt", "")).strip()
                if not prompt:
                    return jsonify({"ok": False, "error": "prompt 不能为空"}), 400
                data = await self.plugin.webui_test_video(prompt=prompt)
                return jsonify({"ok": True, "data": data})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        @app.post("/api/test/video-query")
        async def api_test_video_query():
            try:
                payload = await request.get_json(force=True) or {}
                task_id = str(payload.get("task_id", "")).strip()
                if not task_id:
                    return jsonify({"ok": False, "error": "task_id 不能为空"}), 400
                data = await self.plugin.webui_query_video(task_id=task_id)
                return jsonify({"ok": True, "data": data})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 400

        self.app = app

    async def start(self) -> None:
        if not WEB_ADMIN_AVAILABLE:
            raise RuntimeError("Quart/Hypercorn 不可用")
        if self.running:
            return

        self.host = self.plugin.webui_host
        self.port = self.plugin.webui_port
        self.base_url = f"http://{self.host}:{self.port}"

        cfg = Config()
        cfg.bind = [f"{self.host}:{self.port}"]
        cfg.use_reloader = False
        cfg.accesslog = None
        cfg.errorlog = None

        self._shutdown_event = asyncio.Event()
        self._server_task = asyncio.create_task(
            hypercorn.asyncio.serve(
                self.app,
                cfg,
                shutdown_trigger=self._shutdown_event.wait,
            )
        )

        await asyncio.sleep(0.2)
        if self._server_task.done():
            exc = self._server_task.exception()
            if exc:
                raise RuntimeError(str(exc))
        logger.info(f"kc webui started at {self.base_url}")

    async def stop(self) -> None:
        if not self.running:
            return

        if self._shutdown_event:
            self._shutdown_event.set()

        if self._server_task:
            try:
                await asyncio.wait_for(self._server_task, timeout=5)
            except asyncio.TimeoutError:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task

        self._server_task = None
        self._shutdown_event = None
        logger.info("kc webui stopped")
