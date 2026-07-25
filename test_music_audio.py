"""网易云音乐音频临时文件与转码回归测试。

运行方式：python3 test_music_audio.py
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

from aiohttp import web


class MockLogger:
    def __init__(self):
        self.messages = []

    def _add(self, level, message, *args, **kwargs):
        self.messages.append((level, str(message)))

    def info(self, message, *args, **kwargs):
        self._add("info", message, *args, **kwargs)

    def debug(self, message, *args, **kwargs):
        self._add("debug", message, *args, **kwargs)

    def warning(self, message, *args, **kwargs):
        self._add("warning", message, *args, **kwargs)

    def error(self, message, *args, **kwargs):
        self._add("error", message, *args, **kwargs)


logger = MockLogger()
astrbot = types.ModuleType("astrbot")
astrbot_api = types.ModuleType("astrbot.api")
astrbot_api.logger = logger
astrbot_api.AstrBotConfig = dict
astrbot_event = types.ModuleType("astrbot.api.event")
astrbot_event.filter = types.SimpleNamespace(command=lambda *args, **kwargs: lambda f: f)
astrbot_event.AstrMessageEvent = object
astrbot_event.MessageEventResult = object
astrbot_star = types.ModuleType("astrbot.api.star")
astrbot_star.Context = object
astrbot_star.Star = object
astrbot_star.register = lambda *args, **kwargs: lambda cls: cls
astrbot_components = types.ModuleType("astrbot.api.message_components")
astrbot_components.Record = type(
    "Record", (), {"fromFileSystem": staticmethod(lambda path: {"file": path})}
)
astrbot_components.File = type(
    "File", (), {"__init__": lambda self, name, file: setattr(self, "name", name) or setattr(self, "file", file)}
)

sys.modules.update(
    {
        "astrbot": astrbot,
        "astrbot.api": astrbot_api,
        "astrbot.api.event": astrbot_event,
        "astrbot.api.star": astrbot_star,
        "astrbot.api.message_components": astrbot_components,
    }
)

plugin_parent = str(Path(__file__).resolve().parent.parent)
if plugin_parent not in sys.path:
    sys.path.insert(0, plugin_parent)

# 音频测试不需要加载 DG-LAB / 媒体解析的可选依赖，预先替换相对导入模块。
for module_name, attributes in {
    "dglab_device_store": {"DeviceStore": object},
    "dglab_connection_pool": {"DeviceConnectionPool": object},
    "dglab_commands": {"DGLabCommandHandler": object},
    "dglab_webui": {"DGLabWebUI": object},
    "dglab_user_store": {"UserStore": object},
    "dglab_permission_store": {"PermissionStore": object},
    "media_parser": {
        "MediaParserManager": object,
        "MediaParserError": Exception,
        "URLExtractor": object,
    },
}.items():
    module = types.ModuleType(f"astrbot_plugin_pixiv.{module_name}")
    for name, value in attributes.items():
        setattr(module, name, value)
    sys.modules[module.__name__] = module

from astrbot_plugin_pixiv import main


class TestPlugin:
    _compress_for_voice = main.CurrentCortexPlugin._compress_for_voice
    _download_source_audio_to_temp = main.CurrentCortexPlugin._download_source_audio_to_temp
    _download_audio_to_temp = main.CurrentCortexPlugin._download_audio_to_temp
    _audio_extension = staticmethod(main.CurrentCortexPlugin._audio_extension)
    _build_audio_filename = classmethod(main.CurrentCortexPlugin._build_audio_filename.__func__)
    _cleanup_old_audio_files = staticmethod(main.CurrentCortexPlugin._cleanup_old_audio_files)
    _remove_file = staticmethod(main.CurrentCortexPlugin._remove_file)
    _parse_play_song_params = main.CurrentCortexPlugin._parse_play_song_params
    _leiz_api_key = "test-key"


def run(coro):
    return asyncio.run(coro)


def create_sine_mp3(path: Path):
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.2",
            "-codec:a", "libmp3lame", "-b:a", "128k", str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_real_mp3_transcodes_to_distinct_path(temp_dir: Path):
    source = temp_dir / "Amore_source.mp3"
    create_sine_mp3(source)

    result = run(TestPlugin()._compress_for_voice(str(source), str(temp_dir), "Amore"))

    assert result is not None
    output = Path(result)
    assert output.exists()
    assert output != source
    assert output.name.endswith("_voice.mp3")
    assert not source.exists()
    output.unlink()


def test_same_song_requests_get_unique_paths():
    paths = [
        os.path.join(tempfile.gettempdir(), f"Amore_{main.uuid.uuid4().hex[:12]}_source.mp3")
        for _ in range(2)
    ]
    assert paths[0] != paths[1]


def test_ffmpeg_failure_logs_stderr_and_removes_output(temp_dir: Path):
    source = temp_dir / "invalid_source.mp3"
    source.write_text("not audio", encoding="utf-8")

    logger.messages.clear()
    result = run(TestPlugin()._compress_for_voice(str(source), str(temp_dir), "invalid"))

    assert result is None
    warnings = [message for level, message in logger.messages if level == "warning"]
    assert any("退出码" in message for message in warnings)
    assert any("Invalid" in message or "invalid" in message for message in warnings)
    assert not list(temp_dir.glob("*_voice.mp3"))


def test_missing_ffmpeg_returns_none(temp_dir: Path):
    source = temp_dir / "source.mp3"
    source.write_bytes(b"audio")

    with patch.object(main.shutil, "which", return_value=None):
        result = run(TestPlugin()._compress_for_voice(str(source), str(temp_dir), "song"))

    assert result is None


async def test_raw_download_preserves_bytes(temp_dir: Path):
    payload = b"original-audio-bytes-without-transcoding"

    async def audio_handler(request):
        assert request.headers["x-api-key"] == "test-key"
        return web.Response(body=payload, content_type="audio/mpeg")

    app = web.Application()
    app.router.add_get("/audio", audio_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        with patch.object(main.tempfile, "gettempdir", return_value=str(temp_dir)):
            result = await TestPlugin()._download_source_audio_to_temp(
                f"http://127.0.0.1:{port}/audio", "Amore", "flac"
            )
        assert result is not None
        output = Path(result)
        assert output.suffix == ".flac"
        assert output.name.endswith("_source.flac")
        assert output.read_bytes() == payload
        assert TestPlugin()._build_audio_filename("Amore", result) == "Amore.flac"
        output.unlink()
    finally:
        await runner.cleanup()


async def test_voice_download_falls_back_to_source(temp_dir: Path):
    payload = b"source-audio-for-fallback"

    async def audio_handler(request):
        return web.Response(body=payload, content_type="audio/mpeg")

    app = web.Application()
    app.router.add_get("/audio.mp3", audio_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        with (
            patch.object(main.tempfile, "gettempdir", return_value=str(temp_dir)),
            patch.object(TestPlugin, "_compress_for_voice", return_value=None),
        ):
            result = await TestPlugin()._download_audio_to_temp(
                f"http://127.0.0.1:{port}/audio.mp3", "Fallback Song"
            )
        assert result is not None
        output = Path(result)
        assert output.name.endswith("_source.mp3")
        assert output.exists()
        assert output.read_bytes() == payload
        output.unlink()
    finally:
        await runner.cleanup()


def test_file_command_parsing_and_extension():
    match = main.re.match(r"^(file|文件)\s+(.+)$", "文件 Amore", main.re.IGNORECASE)
    assert match is not None
    assert match.group(2) == "Amore"
    assert TestPlugin()._audio_extension("", "https://cdn.example/song.ogg?token=x") == ".ogg"
    assert TestPlugin()._audio_extension("flac", "https://cdn.example/song") == ".flac"


def test_play_song_command_parsing():
    plugin = TestPlugin()
    # /点歌 <歌曲名>：等效于 /音乐 直接 <歌曲名>
    assert plugin._parse_play_song_params("点歌 孤勇者") == "孤勇者"
    assert plugin._parse_play_song_params("/点歌 孤勇者") == "孤勇者"
    assert plugin._parse_play_song_params("/点歌  周杰伦 晴天") == "周杰伦 晴天"
    # help / 空参数应返回 None
    assert plugin._parse_play_song_params("点歌 help") is None
    assert plugin._parse_play_song_params("点歌") is None
    # 不应误吞 /音乐 命令的参数
    assert plugin._parse_play_song_params("音乐 孤勇者") == "音乐 孤勇者"


def main_test():
    temp_dir = Path(tempfile.mkdtemp(prefix="astrbot_music_test_"))
    try:
        test_real_mp3_transcodes_to_distinct_path(temp_dir)
        test_same_song_requests_get_unique_paths()
        test_ffmpeg_failure_logs_stderr_and_removes_output(temp_dir)
        test_missing_ffmpeg_returns_none(temp_dir)
        run(test_raw_download_preserves_bytes(temp_dir))
        run(test_voice_download_falls_back_to_source(temp_dir))
        test_file_command_parsing_and_extension()
        test_play_song_command_parsing()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("✅ 音乐音频回归测试通过（8 项）")


if __name__ == "__main__":
    main_test()
