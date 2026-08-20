"""按会话（群聊）的插件开关状态存储。

存储后端为 JSON 文件（data/currentcortex_group_switch.json），用 threading.Lock
保护读写，与插件内 CrossGroupMemoryStore / DeviceStore 等持久化风格一致，完全自
包含、不依赖 AstrBot 核心数据库。

语义为「黑名单」：未被显式记录的会话视为启用（默认启用），只有被显式禁用的会话
（set_disabled）才会被守卫处理器拦截。这样既能精准关闭个别群，又不会影响老群或
新群。

每个被禁用的会话额外记录一个可选的到期时间戳（until）：
    - until 为 None：永久禁用，需手动 /开关 on 重新启用。
    - until 为具体时间戳：到期后自动视为启用（懒惰过期，在 is_enabled /
      list_disabled 调用时惰性清理，不需要额外的定时任务或后台线程）。
"""

import json
import os
import threading
import time
from typing import List, Optional


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
        # 被禁用的会话：umo -> until（unix 时间戳；None 表示永久禁用）
        self._disabled: dict[str, Optional[float]] = {}
        self._ensure_data_dir()
        self._load()

    def _ensure_data_dir(self) -> None:
        os.makedirs(self._data_dir, exist_ok=True)

    def _load(self) -> None:
        """从 JSON 文件加载被禁用的会话集合（兼容旧版 list 格式）。"""
        if not os.path.exists(self._file_path):
            return
        try:
            with open(self._file_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                disabled = data.get("disabled", [])
                if isinstance(disabled, list):
                    # 旧版本格式：["umo1", "umo2", ...]，均视为永久禁用。
                    for x in disabled:
                        if isinstance(x, str):
                            self._disabled[x] = None
                elif isinstance(disabled, dict):
                    # 新版本格式：{"umo1": until|null, ...}
                    for umo, until in disabled.items():
                        if not isinstance(umo, str):
                            continue
                        if until is None or isinstance(until, (int, float)):
                            self._disabled[umo] = (
                                float(until) if until is not None else None
                            )
            logger.info(
                f"[GroupSwitch] 已加载 {len(self._disabled)} 个被禁用的会话"
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[GroupSwitch] 加载开关状态失败: {e}")

    def _save(self) -> None:
        """将内存镜像刷盘（调用方需持有锁）。"""
        data = {"disabled": dict(sorted(self._disabled.items()))}
        tmp_path = self._file_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._file_path)
        except OSError as e:
            logger.warning(f"[GroupSwitch] 保存开关状态失败: {e}")

    def _purge_expired_locked(self) -> bool:
        """清理已过期的禁用记录（调用方需持有锁）。

        Returns:
            是否有记录被清理（用于判断是否需要刷盘）。
        """
        now = time.time()
        expired = [
            umo
            for umo, until in self._disabled.items()
            if until is not None and until <= now
        ]
        for umo in expired:
            del self._disabled[umo]
        return bool(expired)

    def is_enabled(self, umo: str) -> bool:
        """该会话是否启用（未被显式禁用，或禁用已到期，即视为启用）。"""
        with self._lock:
            if self._purge_expired_locked():
                self._save()
            return umo not in self._disabled

    def set_disabled(self, umo: str, duration_seconds: Optional[float] = None) -> None:
        """显式禁用某会话。

        Args:
            umo: 会话标识。
            duration_seconds: 禁用时长（秒）；None 表示永久禁用，需手动重新启用。
        """
        with self._lock:
            until = time.time() + duration_seconds if duration_seconds else None
            self._disabled[umo] = until
            self._save()

    def set_enabled(self, umo: str) -> bool:
        """重新启用某会话。

        Returns:
            是否实际发生了状态变更（即之前确实是禁用状态）。
        """
        with self._lock:
            self._purge_expired_locked()
            if umo in self._disabled:
                del self._disabled[umo]
                self._save()
                return True
            return False

    def get_until(self, umo: str) -> Optional[float]:
        """返回某会话的禁用到期时间戳；未禁用或永久禁用则分别返回 None。

        调用前建议先用 is_enabled 判断，避免把「已过期」误当「永久禁用」。
        """
        with self._lock:
            self._purge_expired_locked()
            return self._disabled.get(umo)

    def list_disabled(self) -> List[str]:
        """返回所有（未过期）被禁用的会话列表（排序后）。"""
        with self._lock:
            if self._purge_expired_locked():
                self._save()
            return sorted(self._disabled.keys())

    def list_disabled_detail(self) -> List[dict]:
        """返回所有（未过期）被禁用会话的详情列表，用于可视化展示。

        Returns:
            按 umo 排序的列表，每项为
            ``{"umo": str, "until": float|None, "permanent": bool}``。
            permanent=True 表示永久禁用；否则 until 为到期 unix 时间戳。
        """
        with self._lock:
            if self._purge_expired_locked():
                self._save()
            return [
                {"umo": umo, "until": until, "permanent": until is None}
                for umo, until in sorted(self._disabled.items())
            ]
