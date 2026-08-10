"""Qtine compatibility entry point for CurrentCortex.

This adapter deliberately reuses the AstrBot command implementation instead of
maintaining two copies of the feature logic.  Qtine responses are serialized as
OneBot v11 CQ strings, which are passed through unchanged by Qtine's adapter.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import html
import importlib.util
import logging
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any, Iterable

from qtine.plugins.base import BasePlugin


PLUGIN_DIR = Path(__file__).resolve().parent
SOURCE_DIR = PLUGIN_DIR / "source"
DATA_DIR = PLUGIN_DIR / "data"
LOGGER = logging.getLogger(__name__)

COMMANDS = {
    "/hitokoto": ["/一言"],
    "/weather": ["/天气"],
    "/femboy": ["/男娘"],
    "/music": ["/音乐"],
    "/pixiv": ["/图片"],
    "/jm": ["/漫画"],
    "/jmcommend": ["/漫画推荐"],
    "/解析": [],
    "/xhs": ["/小红书"],
    "/bilibili": ["/B站", "/b站"],
    "/douyin": ["/抖音"],
    "/dglab": ["/电击"],
    "/apitest": ["/连通测试", "/接口测试"],
}

CONFIGS = (
    ("default_r18", "默认 R18 等级（0=全年龄，1=R18，2=混合）", 0, "number"),
    ("default_num", "默认图片数量（1-20）", 1, "number"),
    ("default_size", "默认图片尺寸", "regular", "text"),
    ("image_proxy", "图片代理域名", "pixiv.bileizhen.top", "text"),
    ("exclude_ai", "默认排除 AI 作品", False, "boolean"),
    ("request_timeout", "API 请求超时（秒）", 15, "number"),
    ("leiz_api_key", "LeiZ API 统一密钥（x-api-key）", "", "password"),
    ("dglab_server_url", "DG-LAB Socket V2 服务器地址", "", "text"),
    ("dglab_heartbeat_interval", "DG-LAB 心跳间隔（秒）", 60, "number"),
    ("dglab_auto_connect", "自动连接 DG-LAB", False, "boolean"),
    ("dglab_webui_enabled", "启用 CCDG WebUI", False, "boolean"),
    ("dglab_webui_host", "CCDG WebUI 绑定地址", "127.0.0.1", "text"),
    ("dglab_webui_port", "CCDG WebUI 端口", 9178, "number"),
)


def cq_escape(value: Any) -> str:
    """Escape a CQ parameter without modifying ordinary message text."""
    return html.escape(str(value), quote=False).replace(",", "&#44;").replace("[", "&#91;").replace("]", "&#93;")


def cq_source(value: str) -> str:
    """Return a OneBot-compatible URL or absolute ``file://`` source."""
    if value.startswith(("http://", "https://", "file://", "base64://")):
        return value
    return "file://" + os.path.abspath(value)


def cq_image(value: str) -> str:
    return f"[CQ:image,file={cq_escape(cq_source(value))}]"


def cq_record(value: str) -> str:
    return f"[CQ:record,file={cq_escape(cq_source(value))}]"


def cq_file(name: str, value: str) -> str:
    return f"[CQ:file,file={cq_escape(cq_source(value))},name={cq_escape(name)}]"


class _Result:
    def __init__(self, kind: str, value: Any = None):
        self.kind = kind
        self.value = value


class _QtineEvent:
    """Minimal AstrBot event surface consumed by the existing handlers."""

    def __init__(self, content: str, sender_id: str, sender_name: str):
        self.message_str = content
        self._sender_id = sender_id
        self._sender_name = sender_name

    def get_sender_id(self) -> str:
        return self._sender_id

    def get_sender_name(self) -> str:
        return self._sender_name

    def plain_result(self, text: str) -> _Result:
        return _Result("plain", text)

    def image_result(self, source: str) -> _Result:
        return _Result("image", source)

    def chain_result(self, components: Iterable[Any]) -> _Result:
        return _Result("chain", list(components))


def _install_astrbot_compatibility() -> None:
    """Provide the small AstrBot API subset used by the shared implementation."""
    # Qtine reloads execute this module again while the shim from the previous
    # import remains in sys.modules. ``find_spec`` raises ValueError for such a
    # manually-created module because it intentionally has no ModuleSpec.
    if "astrbot" in sys.modules:
        return
    if importlib.util.find_spec("astrbot") is not None:
        return
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = LOGGER
    api.AstrBotConfig = dict
    event = types.ModuleType("astrbot.api.event")
    event.filter = types.SimpleNamespace(command=lambda *args, **kwargs: lambda func: func)
    event.AstrMessageEvent = _QtineEvent
    event.MessageEventResult = _Result
    star = types.ModuleType("astrbot.api.star")

    class _Star:
        def __init__(self, context: Any = None):
            self.context = context

    star.Context = object
    star.Star = _Star
    star.register = lambda *args, **kwargs: lambda cls: cls
    components = types.ModuleType("astrbot.api.message_components")

    class _File:
        def __init__(self, name: str, file: str):
            self.name, self.file = name, file

    class _Record:
        @staticmethod
        def fromFileSystem(path: str) -> Any:
            return types.SimpleNamespace(file=path, _qtine_kind="record")

    class _Plain:
        def __init__(self, text: str):
            self.text = text

    class _Image:
        def __init__(self, file: str):
            self.file = file

    components.File = _File
    components.Record = _Record
    components.Plain = _Plain
    components.Image = _Image
    components.Node = lambda *args, **kwargs: types.SimpleNamespace(*args, **kwargs)
    components.Nodes = lambda *args, **kwargs: types.SimpleNamespace(*args, **kwargs)
    sys.modules.update({
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event,
        "astrbot.api.star": star,
        "astrbot.api.message_components": components,
    })


def _load_shared_plugin() -> type:
    _install_astrbot_compatibility()
    package_name = "currentcortex_qtine_shared"
    package = types.ModuleType(package_name)
    package.__path__ = [str(SOURCE_DIR)]
    sys.modules.setdefault(package_name, package)
    module_name = f"{package_name}.main"
    if module_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(module_name, SOURCE_DIR / "main.py")
        if not spec or not spec.loader:
            raise RuntimeError("无法加载 CurrentCortex 共享命令实现")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return sys.modules[module_name].CurrentCortexPlugin


class _AsyncRunner:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="currentcortex-qtine")
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coroutine: Any) -> Any:
        future: concurrent.futures.Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result()

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


def _result_to_cq(result: Any) -> str:
    if isinstance(result, _Result):
        if result.kind == "plain":
            return str(result.value)
        if result.kind == "image":
            return cq_image(str(result.value))
        if result.kind == "chain":
            return "".join(_component_to_cq(component) for component in result.value)
    return str(result)


def _component_to_cq(component: Any) -> str:
    if hasattr(component, "name") and hasattr(component, "file"):
        return cq_file(component.name, component.file)
    if getattr(component, "_qtine_kind", None) == "record":
        return cq_record(component.file)
    if hasattr(component, "nodes"):
        # Qtine has no forward-message action. Flatten AstrBot forward nodes into
        # one OneBot message while preserving the existing ten-image limit.
        return "".join(_component_to_cq(node) for node in component.nodes)
    if hasattr(component, "content"):
        return "".join(_component_to_cq(item) for item in component.content)
    if hasattr(component, "text"):
        return str(component.text)
    if hasattr(component, "file"):
        return cq_image(component.file)
    return ""


class CurrentCortexQtinePlugin(BasePlugin):
    name = "currentcortex"
    version = "1.4.0"
    description = "Pixiv、音乐、DG-LAB 与媒体解析综合插件（Qtine 兼容层）"
    author = "AstrBot Community"

    def __init__(self, bot: Any):
        super().__init__(bot=bot)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        for key, label, default, config_type in CONFIGS:
            self.add_config(key, label, default=default, config_type=config_type)
        self._runner = _AsyncRunner()
        self._shared = _load_shared_plugin()(None, self._config_values())
        self._configure_data_paths()
        for command, aliases in COMMANDS.items():
            self.register_command(command, self._command_handler, aliases=aliases)

    def _config_values(self) -> dict[str, Any]:
        return {key: self.get_config(key, default) for key, _, default, _ in CONFIGS}

    def _configure_data_paths(self) -> None:
        """Replace AstrBot's CWD-relative stores with Qtine package-local stores."""
        module = sys.modules[self._shared.__class__.__module__]
        values = self._config_values()
        data_dir = str(DATA_DIR)
        device_store = module.DeviceStore(data_dir=data_dir)
        pool = module.DeviceConnectionPool(
            device_store=device_store,
            max_connections=200,
            idle_timeout=300,
            operation_timeout=10.0,
        )
        self._shared._device_store = device_store
        self._shared._connection_pool = pool
        self._shared._dglab_handler = module.DGLabCommandHandler(
            connection_pool=pool,
            device_store=device_store,
            default_server_url=str(values["dglab_server_url"]).strip(),
            data_dir=data_dir,
        )
        self._shared._user_store = module.UserStore(data_dir=data_dir)
        self._shared._permission_store = module.PermissionStore(data_dir=data_dir)
        if self._shared._dglab_webui:
            self._shared._dglab_webui = module.DGLabWebUI(
                connection_pool=pool,
                device_store=device_store,
                user_store=self._shared._user_store,
                permission_store=self._shared._permission_store,
                host=str(values.get("dglab_webui_host", "127.0.0.1")).strip(),
                port=int(values["dglab_webui_port"]),
            )

    def _command_handler(self, ctx: Any, args: list[str]) -> str:
        content = ctx.message.content.strip()
        sender = getattr(ctx.message, "sender", None)
        sender_id = str(getattr(sender, "user_id", "unknown"))
        sender_name = str(getattr(sender, "nickname", "") or sender_id)
        event = _QtineEvent(content, sender_id, sender_name)
        command = content.lstrip().split(maxsplit=1)[0].lstrip("/!！")
        method_name = {
            "一言": "hitokoto_command", "天气": "weather_command", "男娘": "femboy_command",
            "音乐": "music_command", "图片": "pixiv_command", "漫画": "jm_command",
            "漫画推荐": "jmcommend_command", "解析": "media_parse_command",
            "xhs": "xhs_parse_command", "小红书": "xhs_parse_command",
            "bilibili": "bilibili_parse_command", "B站": "bilibili_parse_command", "b站": "bilibili_parse_command",
            "douyin": "douyin_parse_command", "抖音": "douyin_parse_command",
            "电击": "dglab_command", "连通测试": "apitest_command", "接口测试": "apitest_command",
        }.get(command, f"{command}_command")
        handler = getattr(self._shared, method_name, None)
        if handler is None:
            return "❌ 未找到命令处理器"

        async def collect() -> str:
            values = []
            async for result in handler(event):
                values.append(_result_to_cq(result))
            return "\n".join(value for value in values if value)

        try:
            return self._runner.run(collect())
        except Exception as exc:
            LOGGER.exception("Qtine command failed: %s", command)
            return f"❌ 命令执行失败：{exc}"

    def on_enable(self) -> None:
        async def start() -> None:
            await self._shared._connection_pool.start()
            if self._shared._dglab_webui:
                await self._shared._dglab_webui.start()
        self._runner.run(start())

    def on_disable(self) -> None:
        async def stop() -> None:
            if self._shared._dglab_webui:
                await self._shared._dglab_webui.stop()
            await self._shared._connection_pool.stop()
        self._runner.run(stop())

    def on_unload(self) -> None:
        self._runner.close()
