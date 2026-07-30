"""按会话（群聊）的插件开关状态存储。

存储后端为 JSON 文件（data/currentcortex_group_switch.json），用 threading.Lock
保护读写，与插件内 CrossGroupMemoryStore / DeviceStore 等持久化风格一致，完全自
包含、不依赖 AstrBot 核心数据库。

语义为「黑名单」：未被显式记录的会话视为启用（默认启用），只有被显式禁用的会话
（set_disabled）才会被守卫处理器拦截。这样既能精准关闭个别群，又不会影响老群或
新群。
"""

import json
import os
import threading
from typing import List

from astrbot.api import logger


class GroupSwitchStore:
    """按 unified_msg_origin 记录「是否被禁用」的持久化存储。

    Args:
        data_dir: 数据目录（通常为 "data"）。
    """

    def __init__(self, data_dir: str = "data") -> None:
        self._data_dir = data_dir
        self._file_path = os.path.join(
            data_dir, "currentcortex_group_switch.json"
        )
        self._lock = threading.Lock()
        # 被禁用的会话集合（unified_msg_origin）
        self._disabled: set[str] = set()
        self._ensure_data_dir()
        self._load()

    def _ensure_data_dir(self) -> None:
        os.makedirs(self._data_dir, exist_ok=True)

    def _load(self) -> None:
        """从 JSON 文件加载被禁用的会话集合。"""
        if not os.path.exists(self._file_path):
            return
        try:
            with open(self._file_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                disabled = data.get("disabled", [])
                if isinstance(disabled, list):
                    self._disabled = {
                        str(x) for x in disabled if isinstance(x, str)
                    }
            logger.info(
                f"[GroupSwitch] 已加载 {len(self._disabled)} 个被禁用的会话"
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[GroupSwitch] 加载开关状态失败: {e}")

    def _save(self) -> None:
        """将内存镜像刷盘（调用方需持有锁）。"""
        data = {"disabled": sorted(self._disabled)}
        tmp_path = self._file_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._file_path)
        except OSError as e:
            logger.warning(f"[GroupSwitch] 保存开关状态失败: {e}")

    def is_enabled(self, umo: str) -> bool:
        """该会话是否启用（未被显式禁用即视为启用）。"""
        with self._lock:
            return umo not in self._disabled

    def set_disabled(self, umo: str) -> None:
        """显式禁用某会话。"""
        with self._lock:
            self._disabled.add(umo)
            self._save()

    def set_enabled(self, umo: str) -> bool:
        """重新启用某会话。

        Returns:
            是否实际发生了状态变更（即之前确实是禁用状态）。
        """
        with self._lock:
            if umo in self._disabled:
                self._disabled.discard(umo)
                self._save()
                return True
            return False

    def list_disabled(self) -> List[str]:
        """返回所有被禁用的会话列表（排序后）。"""
        with self._lock:
            return sorted(self._disabled)
