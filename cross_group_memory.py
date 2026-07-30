"""跨群聊记忆 - 同一平台实例下所有群聊共享的滚动记忆。

存储后端为 JSON 文件（data/currentcortex_cross_group.json），用 threading.Lock
保护读写，与插件内 UserStore/DeviceStore 的持久化风格一致，完全自包含、不依赖
AstrBot 核心数据库。每个平台实例（platform_id）一份独立的记录列表，同平台下所有
群聊共享这份记忆，重启后保留。
"""

import json
import os
import threading
from collections import deque

from astrbot.api import logger


class CrossGroupMemoryStore:
    """按 platform_id 分桶的持久化跨群聊记忆存储。

    Args:
        data_dir: 数据目录（通常为 "data"）。
    """

    def __init__(self, data_dir: str = "data") -> None:
        self._data_dir = data_dir
        self._file_path = os.path.join(data_dir, "currentcortex_cross_group.json")
        self._lock = threading.Lock()
        # platform_id -> deque[record_line]
        self._buffers: dict[str, deque] = {}
        self._ensure_data_dir()
        self._load()

    def _ensure_data_dir(self) -> None:
        os.makedirs(self._data_dir, exist_ok=True)

    def _load(self) -> None:
        """从 JSON 文件加载历史记录到内存。"""
        if not os.path.exists(self._file_path):
            return
        try:
            with open(self._file_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(
                    "[CrossGroupMemory] 存储文件格式异常（非字典），已重置为空"
                )
                return
            for platform_id, records in data.items():
                if isinstance(records, list):
                    self._buffers[platform_id] = deque(records)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[CrossGroupMemory] 加载历史记忆失败: {e}")

    def _save(self) -> None:
        """将内存镜像刷盘（调用方需持有锁）。"""
        data = {pid: list(buf) for pid, buf in self._buffers.items()}
        tmp_path = self._file_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, self._file_path)
        except OSError as e:
            logger.warning(f"[CrossGroupMemory] 保存记忆失败: {e}")

    def record(self, platform_id: str, content: str, max_records: int) -> None:
        """追加一条记录并裁剪到 max_records，然后刷盘。

        Args:
            platform_id: 平台适配器实例 id（UMO 第一段）。
            content: 已格式化的聊天记录行。
            max_records: 每个平台保留的最大记录数。
        """
        with self._lock:
            buf = self._buffers.get(platform_id)
            if buf is None:
                buf = deque()
                self._buffers[platform_id] = buf
            buf.append(content)
            while len(buf) > max_records:
                buf.popleft()
            self._save()

    def get_recent(self, platform_id: str, limit: int) -> list:
        """返回某平台最近 limit 条记录（时间正序）。

        Args:
            platform_id: 平台适配器实例 id。
            limit: 最大返回条数。

        Returns:
            按时间正序排列的记录字符串列表。
        """
        if limit <= 0:
            return []
        with self._lock:
            buf = self._buffers.get(platform_id)
            if not buf:
                return []
            return list(buf)[-limit:]

    def clear(self, platform_id: str) -> int:
        """清空某平台的所有记录。

        Args:
            platform_id: 平台适配器实例 id。

        Returns:
            被清除的记录数。
        """
        with self._lock:
            buf = self._buffers.get(platform_id)
            cnt = len(buf) if buf else 0
            if buf is not None:
                buf.clear()
            self._save()
            return cnt
