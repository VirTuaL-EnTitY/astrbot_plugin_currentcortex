"""JMComic 章节命令回归测试：解析、压缩、分段、续看游标。

运行方式：python3 test_jm_chapter.py
"""

import asyncio
import io
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch


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


def _make_image(file):
    return {"file": file}


# Image.fromFileSystem(path) -> dict with file path
astrbot_components.Image = type(
    "Image", (), {"fromFileSystem": staticmethod(_make_image)}
)
astrbot_components.Record = type(
    "Record", (), {"fromFileSystem": staticmethod(lambda path: {"file": path})}
)
astrbot_components.File = type(
    "File",
    (),
    {
        "__init__": lambda self, name, file: setattr(self, "name", name)
        or setattr(self, "file", file)
    },
)
astrbot_components.Plain = type(
    "Plain", (), {"__init__": lambda self, text: setattr(self, "text", text)}
)
astrbot_components.Node = type(
    "Node",
    (),
    {
        "__init__": lambda self, content, name, uin: setattr(self, "content", content)
        or setattr(self, "name", name)
        or setattr(self, "uin", uin)
    },
)
astrbot_components.Nodes = type(
    "Nodes", (), {"__init__": lambda self, nodes: setattr(self, "nodes", nodes)}
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

# JM 测试不需要加载 DG-LAB / 媒体解析的可选依赖，预先替换相对导入模块。
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


class FakeEvent:
    """轻量事件桩：记录 plain_result / chain_result 产物，维护 session_id。"""

    def __init__(self, session_id="sess-1"):
        self.session_id = session_id
        self.results = []
        # 模拟框架：记录交给框架清理的临时文件
        self.tracked_files = []

    def get_session_id(self):
        return self.session_id

    def get_sender_name(self):
        return "tester"

    def plain_result(self, text):
        self.results.append(("plain", text))
        return ("plain", text)

    def chain_result(self, chain):
        self.results.append(("chain", chain))
        return ("chain", chain)

    def track_temporary_local_file(self, path):
        self.tracked_files.append(path)
        return ("chain", chain)


class TestPlugin:
    """复用插件方法（与 test_music_audio.py 同款桩思路）。"""
    _parse_jm_params = main.CurrentCortexPlugin._parse_jm_params
    _extract_jm_images = main.CurrentCortexPlugin._extract_jm_images
    _extract_jm_image_url = staticmethod(main.CurrentCortexPlugin._extract_jm_image_url)
    _jm_image_extension = staticmethod(main.CurrentCortexPlugin._jm_image_extension)
    _prepare_image_for_forward = staticmethod(
        main.CurrentCortexPlugin._prepare_image_for_forward
    )
    _download_jm_image_to_temp = main.CurrentCortexPlugin._download_jm_image_to_temp
    _format_jm_chapter = main.CurrentCortexPlugin._format_jm_chapter
    _get_jm_session_key = main.CurrentCortexPlugin._get_jm_session_key
    _set_jm_chapter_cursor = main.CurrentCortexPlugin._set_jm_chapter_cursor
    _get_jm_chapter_cursor = main.CurrentCortexPlugin._get_jm_chapter_cursor
    _clear_jm_chapter_cursor = main.CurrentCortexPlugin._clear_jm_chapter_cursor
    _remove_file = staticmethod(main.CurrentCortexPlugin._remove_file)

    def __init__(self):
        self._jm_chapter_cursor = {}
        self._jm_page_size = 50
        self._jm_image_max_bytes = 2 * 1024 * 1024
        self._leiz_api_key = "test-key"


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. 解析器：裸 ID → chapter；con/续/继续 → continue；其余兼容
# ---------------------------------------------------------------------------

def test_parse_bare_id_is_chapter():
    plugin = TestPlugin()
    assert plugin._parse_jm_params("jm 413828") == ("chapter", {"id": "413828"})
    assert plugin._parse_jm_params("/jm 413828") == ("chapter", {"id": "413828"})
    assert plugin._parse_jm_params("/漫画 413828") == ("chapter", {"id": "413828"})


def test_parse_continue_aliases():
    plugin = TestPlugin()
    for text in ("jm con", "/jm con", "jm 续", "/jm 继续", "漫画 继续"):
        assert plugin._parse_jm_params(text) == ("continue", {}), text


def test_parse_subcommands_unchanged():
    plugin = TestPlugin()
    assert plugin._parse_jm_params("jm chapter 413828") == ("chapter", {"id": "413828"})
    assert plugin._parse_jm_params("jm 章节 413828") == ("chapter", {"id": "413828"})
    assert plugin._parse_jm_params("jm detail 413828") == ("detail", {"id": "413828"})
    assert plugin._parse_jm_params("jm search 原神") == (
        "search",
        {"query": "原神", "page": 1},
    )
    # 非数字关键词仍走搜索兜底
    assert plugin._parse_jm_params("jm 原神") == ("search", {"query": "原神", "page": 1})
    assert plugin._parse_jm_params("jm help")[0] == "help"
    assert plugin._parse_jm_params("jm")[0] == "help"


# ---------------------------------------------------------------------------
# 2. 图片提取与 URL 扩展名
# ---------------------------------------------------------------------------

def test_extract_images_and_urls():
    plugin = TestPlugin()
    data = {"images": [{"decoded_url": "http://x/1.jpg"}, {"url": "http://x/2.png"}]}
    imgs = plugin._extract_jm_images(data)
    assert len(imgs) == 2
    assert plugin._extract_jm_image_url(imgs[0]) == "http://x/1.jpg"
    assert plugin._extract_jm_image_url(imgs[1]) == "http://x/2.png"
    # 备用字段名
    assert plugin._extract_jm_images({"pages": ["a", "b"]}) == ["a", "b"]
    assert plugin._extract_jm_images({}) == []
    assert plugin._extract_jm_image_url("http://x/3") == "http://x/3"
    # 扩展名推断
    assert plugin._jm_image_extension("http://x/1.PNG?token=x") == ".png"
    assert plugin._jm_image_extension("http://x/1.webp") == ".webp"
    assert plugin._jm_image_extension("http://x/1") == ".jpg"


# ---------------------------------------------------------------------------
# 3. 转码：webp 统一转 JPEG、JPEG 合规复用、大图降质达标、损坏图不抛异常
# ---------------------------------------------------------------------------

def _make_jpeg_bytes(quality, size=(2000, 2000), noise=False):
    from PIL import Image
    import random

    if noise:
        # 类照片内容（渐变 + 少量噪点）：可被 JPEG 压缩，用于验证逐档降质逻辑
        random.seed(1)
        w, h = size
        img = Image.new("RGB", size)
        px = img.load()
        for y in range(h):
            for x in range(w):
                px[x, y] = (
                    (x * 255 // w + random.randint(-20, 20)) % 256,
                    (y * 255 // h + random.randint(-20, 20)) % 256,
                    ((x + y) * 128 // (w + h)) % 256,
                )
    else:
        img = Image.new("RGB", size, (128, 64, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _make_webp_bytes(quality=80, size=(1500, 1500)):
    from PIL import Image
    import random

    random.seed(2)
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (
                (x * 255 // w + random.randint(-10, 10)) % 256,
                (y * 255 // h + random.randint(-10, 10)) % 256,
                ((x + y) * 64 // (w + h)) % 256,
            )
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def test_small_compliant_jpeg_reused(temp_dir: Path):
    # 已是合规 JPEG 且体积达标：直接复用，不重编码
    payload = _make_jpeg_bytes(50)
    path = temp_dir / "small.jpg"
    path.write_bytes(payload)

    result = TestPlugin._prepare_image_for_forward(str(path), 2 * 1024 * 1024)
    assert result == str(path), "合规 JPEG 应直接复用"


def test_webp_converted_to_jpeg(temp_dir: Path):
    # webp 必须转 JPEG（即使体积达标）—— 这是修 retcode=1200 的核心
    payload = _make_webp_bytes(80, size=(800, 800))
    path = temp_dir / "page.webp"
    path.write_bytes(payload)
    assert os.path.getsize(path) < 2 * 1024 * 1024, "前置：webp 应未超阈值"

    result = TestPlugin._prepare_image_for_forward(str(path), 2 * 1024 * 1024)
    assert result.lower().endswith(".jpg"), f"webp 应转成 .jpg，得到 {result}"
    assert result != str(path), "webp 原文件应被替换"
    assert not path.exists(), "webp 原文件应被清理"
    # 转出的应是可被识别的 JPEG
    from PIL import Image
    with Image.open(result) as img:
        assert img.format == "JPEG"


def test_large_image_compressed_under_threshold(temp_dir: Path):
    # 构造一张略超 2MB 的类照片图（可被 JPEG 降质压到阈值内）
    payload = _make_jpeg_bytes(95, size=(2500, 2500), noise=True)
    path = temp_dir / "huge.jpg"
    path.write_bytes(payload)
    assert os.path.getsize(path) > 2 * 1024 * 1024, "前置：原图应超阈值"

    result = TestPlugin._prepare_image_for_forward(str(path), 2 * 1024 * 1024)
    assert os.path.getsize(result) <= 2 * 1024 * 1024, "压缩后应 ≤ 2MB"
    assert result.lower().endswith(".jpg")
    # 原超阈值文件应被清理
    assert not path.exists() or result != str(path)


def test_corrupt_image_returns_original(temp_dir: Path):
    path = temp_dir / "broken.webp"
    path.write_bytes(b"not an image at all")
    # max_bytes=0 强制进入转码分支；内容损坏时不应抛异常，返回原路径
    result = TestPlugin._prepare_image_for_forward(str(path), 0)
    assert result == str(path), "损坏图应返回原路径不抛异常"


# ---------------------------------------------------------------------------
# 4. 分段与续看：_format_jm_chapter 的 offset/next_offset 与游标生命周期
# ---------------------------------------------------------------------------

def test_pagination_segments_and_cursor(temp_dir: Path):
    plugin = TestPlugin()
    plugin._jm_page_size = 3  # 小页便于测试
    # 7 张图：mock 下载直接写入一个本地 jpg，跳过网络
    async def fake_download(url, idx, td):
        p = os.path.join(td, f"img_{idx}.jpg")
        Path(p).write_bytes(_make_jpeg_bytes(40, size=(50, 50)))
        return p

    images = [
        {"decoded_url": f"http://x/{i}.jpg"} for i in range(7)
    ]
    with patch.object(
        plugin, "_download_jm_image_to_temp", fake_download
    ), patch.object(
        main.tempfile, "gettempdir", return_value=str(temp_dir)
    ):
        event = FakeEvent()
        results, next_offset = run(plugin._format_jm_chapter(event, images, offset=0))
    # 本段应下发 3 张
    assert next_offset == 3
    chains = [r for r in event.results if r[0] == "chain"]
    assert len(chains) == 1
    nodes = chains[0][1][0].nodes
    # 3 张图片节点 + 1 个「继续」提示节点
    assert len(nodes) == 4
    # 关键回归保护：临时图片不能在返回前删除（否则发送阶段 Node.to_dict
    # 读不到文件，转发节点图片为空）。应交给框架 track，且文件此刻必须仍存在。
    assert len(event.tracked_files) == 3, "3 张图片应全部交给框架 track"
    for p in event.tracked_files:
        assert os.path.exists(p), f"track 的临时图片在返回后仍应存在: {p}"
    # 存游标，继续看
    plugin._set_jm_chapter_cursor(event, "413828", images, next_offset)
    cursor = plugin._get_jm_chapter_cursor(event)
    assert cursor is not None and cursor["offset"] == 3
    # 续看下一段（offset=3 → 6）
    event2 = FakeEvent(event.session_id)
    with patch.object(
        plugin, "_download_jm_image_to_temp", fake_download
    ), patch.object(
        main.tempfile, "gettempdir", return_value=str(temp_dir)
    ):
        results2, next_offset2 = run(plugin._format_jm_chapter(event2, images, offset=3))
    assert next_offset2 == 6
    # 最后一段（offset=6 → 7）不应再带「继续」提示
    event3 = FakeEvent(event.session_id)
    with patch.object(
        plugin, "_download_jm_image_to_temp", fake_download
    ), patch.object(
        main.tempfile, "gettempdir", return_value=str(temp_dir)
    ):
        results3, next_offset3 = run(plugin._format_jm_chapter(event3, images, offset=6))
    assert next_offset3 == 7
    nodes3 = [r for r in event3.results if r[0] == "chain"][0][1][0].nodes
    # 1 张图片节点，无「继续」提示节点
    assert len(nodes3) == 1
    # 清除游标
    plugin._clear_jm_chapter_cursor(event)
    assert plugin._get_jm_chapter_cursor(event) is None


def test_cursor_ttl_expiry():
    plugin = TestPlugin()
    event = FakeEvent("ttl-sess")
    plugin._set_jm_chapter_cursor(event, "123", [{"decoded_url": "u"}], 1)
    assert plugin._get_jm_chapter_cursor(event) is not None
    # 模拟过期：把时间戳倒拨到 TTL 之外
    plugin._jm_chapter_cursor["ttl-sess"]["ts"] -= main._JM_CHAPTER_CURSOR_TTL + 1
    assert plugin._get_jm_chapter_cursor(event) is None
    assert "ttl-sess" not in plugin._jm_chapter_cursor


def test_cursor_isolated_per_session():
    plugin = TestPlugin()
    e1, e2 = FakeEvent("sess-a"), FakeEvent("sess-b")
    plugin._set_jm_chapter_cursor(e1, "111", [], 5)
    plugin._set_jm_chapter_cursor(e2, "222", [], 9)
    assert plugin._get_jm_chapter_cursor(e1)["chapter_id"] == "111"
    assert plugin._get_jm_chapter_cursor(e2)["chapter_id"] == "222"
    plugin._clear_jm_chapter_cursor(e1)
    assert plugin._get_jm_chapter_cursor(e1) is None
    assert plugin._get_jm_chapter_cursor(e2) is not None  # 互不影响


def main_test():
    temp_dir = Path(tempfile.mkdtemp(prefix="astrbot_jm_test_"))
    try:
        test_parse_bare_id_is_chapter()
        test_parse_continue_aliases()
        test_parse_subcommands_unchanged()
        test_extract_images_and_urls()
        test_small_compliant_jpeg_reused(temp_dir)
        test_webp_converted_to_jpeg(temp_dir)
        test_large_image_compressed_under_threshold(temp_dir)
        test_corrupt_image_returns_original(temp_dir)
        test_pagination_segments_and_cursor(temp_dir)
        test_cursor_ttl_expiry()
        test_cursor_isolated_per_session()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("✅ JMComic 章节命令回归测试通过（11 项）")


if __name__ == "__main__":
    main_test()
