"""Qtine CQ compatibility regression tests.

Run with: python3 test_qtine_compat.py
"""

import importlib.util
import sys
import types
from pathlib import Path


class BasePlugin:
    def __init__(self, bot=None):
        self.bot = bot
        self.configs = {}
        self.commands = []

    def add_config(self, key, label, default=None, **kwargs):
        self.configs[key] = default

    def get_config(self, key, default=None):
        return self.configs.get(key, default)

    def register_command(self, command, handler, aliases=None, permission="user"):
        self.commands.append((command, aliases or [], handler, permission))


qtine = types.ModuleType("qtine")
qtine_plugins = types.ModuleType("qtine.plugins")
qtine_base = types.ModuleType("qtine.plugins.base")
qtine_base.BasePlugin = BasePlugin
sys.modules.update({
    "qtine": qtine,
    "qtine.plugins": qtine_plugins,
    "qtine.plugins.base": qtine_base,
})

module_path = Path(__file__).parent / "qtine" / "main.py"
spec = importlib.util.spec_from_file_location("qtine_currentcortex", module_path)
qtine_main = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = qtine_main
spec.loader.exec_module(qtine_main)


def test_cq_serialization():
    assert qtine_main.cq_image("https://example.com/a,b.png") == "[CQ:image,file=https://example.com/a&#44;b.png]"
    assert qtine_main.cq_image("data/a.png").startswith("[CQ:image,file=file:///")
    assert "name=a&#44;b.mp3" in qtine_main.cq_file("a,b.mp3", "audio.mp3")
    assert qtine_main.cq_record("audio.mp3").startswith("[CQ:record,file=file:///")


def test_result_conversion():
    assert qtine_main._result_to_cq(qtine_main._Result("plain", "hello")) == "hello"
    assert qtine_main._result_to_cq(qtine_main._Result("image", "https://example.com/x.png")) == "[CQ:image,file=https://example.com/x.png]"
    file_component = types.SimpleNamespace(name="song.mp3", file="song.mp3")
    record_component = types.SimpleNamespace(file="voice.mp3", _qtine_kind="record")
    output = qtine_main._result_to_cq(qtine_main._Result("chain", [file_component, record_component]))
    assert output.startswith("[CQ:file,")
    assert "[CQ:record," in output

    caption_component = types.SimpleNamespace(text="👗 随机男娘图片")
    image_component = types.SimpleNamespace(file="https://example.com/femboy.webp")
    mixed_output = qtine_main._result_to_cq(
        qtine_main._Result("chain", [caption_component, image_component])
    )
    assert mixed_output == "👗 随机男娘图片[CQ:image,file=https://example.com/femboy.webp]"


def test_metadata_and_commands():
    import json

    metadata = json.loads((Path(__file__).parent / "qtine" / "data.json").read_text())
    assert metadata["name"] == "currentcortex"
    assert "/pixiv" in qtine_main.COMMANDS
    assert "/图片" in qtine_main.COMMANDS["/pixiv"]
    assert len(qtine_main.CONFIGS) == 12


if __name__ == "__main__":
    test_cq_serialization()
    test_result_conversion()
    test_metadata_and_commands()
    print("Qtine compatibility tests passed")
