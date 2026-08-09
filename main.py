import re
import json
import random
import asyncio
import time
import shutil
import uuid
from typing import Any, Dict, List, Optional

import aiohttp

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

import os
import tempfile
import astrbot.api.message_components as Comp

from .dglab_device_store import DeviceStore
from .dglab_connection_pool import DeviceConnectionPool
from .dglab_commands import DGLabCommandHandler
from .dglab_webui import DGLabWebUI
from .dglab_user_store import UserStore
from .dglab_permission_store import PermissionStore
from .media_parser import (
    MediaParserManager,
    MediaParserError,
    URLExtractor,
)
from .cross_group_memory import CrossGroupMemoryStore
from .group_switch_store import GroupSwitchStore
from astrbot.api.provider import ProviderRequest, LLMResponse
from astrbot.core.agent.message import TextPart
from astrbot.api.platform import MessageType
from astrbot.api.event.filter import EventMessageType


API_BASE_URL = "https://api.bileizhen.top/api/pixiv"
HITOKOTO_API_URL = "https://api.bileizhen.top/api/one"
WEATHER_API_URL = "https://api.bileizhen.top/api/weather"
FEMBOY_API_URL = "https://api.bileizhen.top/api/femboy"
NETEASE_API_URL = "https://api.bileizhen.top/api/netease"
NETEASE_SEARCH_URL = "https://api.bileizhen.top/api/netease/search"
KUGOU_API_URL = "https://api.bileizhen.top/api/kugou"
KUGOU_SEARCH_URL = "https://api.bileizhen.top/api/kugou/search"
JMCOMIC_API_BASE = "https://api.bileizhen.top/api/jmcomic"
PIXIV_ARTWORK_URL = "https://www.pixiv.net/artworks/{}"

HITOKOTO_CATEGORIES = {
    "a": "动画",
    "b": "漫画",
    "c": "游戏",
    "d": "文学",
    "e": "原创",
    "f": "来自网络",
    "g": "其他",
    "h": "影视",
    "i": "诗词",
    "j": "网易云",
    "k": "哲学",
    "l": "抖机灵",
}

HELP_TEXT = """🎨 Pixiv 随机图片插件 使用说明

📌 基本命令（别名：/图片）
  /pixiv               获取一张随机全年龄图片（默认参数）
  /pixiv help          显示此帮助信息

📌 内容分级选项
  r18:0               全年龄内容（默认）
  r18:1               仅 R18 成人内容 ⚠️
  r18:2               混合模式（全年龄 + R18）🔞

📌 搜索与筛选参数（使用 key:value 格式，可组合使用）
  tag:标签名           按标签筛选图片
                       • OR 匹配：tag:萝莉|少女
                       • AND 匹配：tag:萝莉 tag:少女（多个tag参数）
  keyword:关键词       标题/作者/标签模糊搜索
  uid:作者ID           指定特定作者的 UID
  num:数量             获取图片数量（1-20，默认 1）

📌 图片设置
  size:尺寸            图片大小选项：
                       • original  - 原图（默认）
                       • regular   - 常规尺寸
                       • small     - 小图
                       • thumb     - 缩略图
                       • mini      - 迷你图
  excludeAI:true      排除 AI 生成的作品
  ratio:表达式         长宽比筛选
                       • gt1.2 = 大于 1.2
                       • lt1.8 = 小于 1.8
                       示例：ratio:gt1.2lt1.8

📌 使用示例
  基础用法：
    /pixiv                          随机全年龄图片
    /pixiv r18:1                    随机 R18 图片
    /pixiv help                     显示帮助

  高级搜索：
    /pixiv r18:1 tag:白丝 num:3     获取3张白丝R18图
    /pixiv keyword:初音ミク num:5   搜索初音未来相关图片
    /pixiv tag:萝莉 excludeAI:true  排除AI的萝莉标签图片
    /pixiv uid:123456 num:3         获取指定作者的作品

  组合筛选：
    /pixiv r18:2 tag:白丝 keyword:初音ミク num:3 size:original

⚠️ 注意事项
  • R18 内容仅限成年用户使用
  • 图片来源于 Pixiv，请遵守相关法律法规
  • 如遇问题可发送 /pixiv help 查看帮助

💡 提示：所有参数均可自由组合使用
💡 中文别名：输入 /图片 等同于 /pixiv"""

HITOKOTO_HELP_TEXT = """✨ 每日一言 使用说明

📌 基本命令（别名：/一言）
  /hitokoto             获取一条随机一言（默认全部分类）
  /hitokoto help       显示此帮助信息

📌 分类选项（使用分类代码）
  a - 动画            g - 其他
  b - 漫画            h - 影视
  c - 游戏            i - 诗词
  d - 文学            j - 网易云
  e - 原创            k - 哲学
  f - 来自网络        l - 抖机灵

📌 使用示例
  基础用法：
    /hitokoto                  随机获取一言
    /hitokoto help             显示帮助

  指定分类：
    /hitokoto a               获取动画类一言
    /hitokoto d               获取文学类一言
    /hitokoto i               获取诗词类一言

⚠️ 注意事项
  • 每次调用都会实时获取最新数据，无缓存
  • 一言内容来源于社区贡献，仅供参考
  • 如遇问题可发送 /hitokoto help 查看帮助"""

WEATHER_HELP_TEXT = """🌤️ 天气查询 使用说明

📌 基本命令（别名：/天气）
  /weather <城市名>     查询指定城市的天气
  /weather help         显示此帮助信息

📌 使用示例
  基础用法：
    /weather 广州市           查询广州市天气
    /weather 北京             查询北京市天气
    /weather 上海             查询上海市天气
    /weather help             显示帮助

📌 返回信息
  • 当前城市名称
  • 未来3天天气预报
  • 温度、天气状况、风力等信息

⚠️ 注意事项
  • 请输入正确的城市名称（支持中文）
  • 每次查询都会实时获取最新数据，无缓存
  • 数据来源于第三方API，仅供参考
  • 如遇问题可发送 /weather help 查看帮助"""


MUSIC_HELP_TEXT = """🎵 网易云音乐 使用说明

📌 基本命令（别名：/音乐）
  /music <歌曲名>       搜索并获取歌曲信息（点歌）
  /music direct <歌曲名> 仅返回语音条（别名：直接）
  /music file <歌曲名>  返回原始音乐文件（别名：文件）
  /music id:<歌曲ID>    通过歌曲ID获取详细信息（别名：编号:<ID>）
  /music search <关键词> 搜索歌曲列表（别名：搜索）
  /music help           显示此帮助信息

📌 快捷命令
  /点歌 <歌曲名>         仅返回语音条（等效于 /音乐 直接）

📌 中文用法示例
  /音乐 孤勇者              点歌
  /音乐 直接 孤勇者         仅返回语音条
  /点歌 孤勇者              仅返回语音条
  /音乐 文件 孤勇者         返回原始音乐文件
  /音乐 搜索 陈奕迅         搜索歌曲列表
  /音乐 编号:1901371647     通过ID获取歌曲

📌 使用示例
  点歌（搜索并返回第一首）：
    /music 孤勇者              搜索并获取「孤勇者」
    /music 周杰伦 晴天         搜索「周杰伦 晴天」

  仅语音条（不附带标题、封面等）：
    /music direct 孤勇者       只返回语音消息

  原始音乐文件（不转码）：
    /music file 孤勇者         返回原始音频附件

  通过ID获取：
    /music id:1901371647       获取指定ID的歌曲信息

  搜索歌曲列表：
    /music search 陈奕迅       搜索陈奕迅相关歌曲列表

📌 返回信息
  • 歌曲名称、艺术家、专辑
  • 专辑封面图片
  • 音质信息（码率、格式）
  • 播放链接
  • 语音条（自动转码为MP3格式）
  • 原始音乐文件（文件模式，不转码）

⚠️ 注意事项
  • 部分VIP歌曲可能无法获取播放链接
  • 播放链接有时效性，请及时使用
  • 原始文件受平台文件大小和格式限制
  • 数据来源于网易云音乐，仅供个人试听
  • 如遇问题可发送 /music help 查看帮助"""


FEMBOY_HELP_TEXT = """👗 男娘图片 使用说明

📌 基本命令（别名：/男娘）
  /femboy              获取一张随机男娘图片（WebP 格式）
  /femboy help         显示此帮助信息

📌 功能特点
  • 随机返回南梁（男娘）主题图片
  • 图片格式为 WebP，加载速度快
  • 显示图片来源与备注信息
  • 支持自定义 API 密钥配置

📌 使用示例
  基础用法：
    /femboy                  获取随机男娘图片
    /femboy help             显示帮助

📌 返回信息
  • 图片内容（WebP 格式）
  • 图片来源信息
  • 备注说明（如有）

⚙️ 配置要求
  ⚠️ 使用前必须配置 API 密钥：
  1. 打开插件配置面板
  2. 填写「leiz_api_key」字段（LeiZ API 统一密钥，请求头 x-api-key）
  3. 保存配置并重启插件

⚠️ 注意事项
  • 图片来源于社区上传，仅供娱乐
  • 每次调用都会实时获取随机图片
  • 需要有效的 API 密钥才能使用此功能
  • 如遇问题可发送 /femboy help 查看帮助"""

JMCOMIC_HELP_TEXT = """📚 JMComic 漫画 使用说明

📌 基本命令（别名：/漫画）
  /jm <章节ID>            获取章节图片（最简写法）
  /jm chapter <章节ID>    同上（别名：章节）
  /jm con                 继续查看上一章节的后续图片（别名：续 / 继续）
  /jm search <关键词>     搜索漫画（别名：搜索）
  /jm detail <漫画ID>     获取漫画详情（别名：详情）
  /jm help               显示此帮助信息

📌 中文用法示例
  /jm 413828                  获取章节ID为413828的图片
  /jm con                     继续查看剩余图片
  /漫画 搜索 原神            搜索「原神」相关漫画
  /漫画 详情 413828          获取漫画详情
  /漫画 章节 413828          获取章节图片

📌 搜索参数
  /jm search <关键词> [page:<页码>]
  • 关键词：搜索漫画标题、作者等
  • page：页码，默认为 1

📌 使用示例
  搜索漫画：
    /jm search 原神              搜索「原神」相关漫画
    /jm search 萝莉 page:2       搜索第2页结果

  查看详情：
    /jm detail 413828            获取漫画ID为413828的详情

  获取章节图片：
    /jm 413828                   最简写法，获取章节ID为413828的图片
    /jm chapter 413828           等价写法

📌 章节图片分段
  • 整章图片较多时，每条命令最多下发 20 张（可配置 jm_page_size）
  • 仍有剩余会提示，发送 /jm con 即可继续查看下一段
  • 图片统一转码为 JPEG（QQ 合并转发对 webp 支持不佳），超 2MB 再降质压缩

📌 返回信息
  搜索结果：
    • 漫画ID、标题、作者
    • 分类信息

  漫画详情：
    • 标题、作者、描述
    • 章节列表

  章节图片：
    • 合并转发批量发送本段全部图片

⚠️ 注意事项
  • 内容来源于第三方，请遵守相关法律法规
  • API 响应可能较慢，请耐心等待
  • 续看游标约 30 分钟有效，过期需重新 /jm <章节ID>
  • 如遇问题可发送 /jm help 查看帮助

📌 相关命令
  /jmcommend（别名：/漫画推荐）  随机推荐一部漫画"""

MEDIA_PARSER_HELP_TEXT = """🔍 媒体内容解析 使用说明

📌 支持平台
  • 小红书（xiaohongshu）— 笔记图文/视频解析
  • Bilibili（bilibili）— 视频信息及下载链接解析
  • 抖音（douyin）— 短视频解析

📌 基本命令
  /解析 <链接>           自动识别平台并解析内容（别名：/解析）
  /xhs <链接>           解析小红书内容（别名：/小红书）
  /bilibili <链接>      解析B站视频（别名：/B站）
  /douyin <链接>        解析抖音视频（别名：/抖音）
  /解析 help            显示此帮助信息

📌 支持的链接格式
  小红书：
    • https://www.xiaohongshu.com/explore/xxx
    • https://xhslink.com/xxx（短链接）

  B站：
    • https://www.bilibili.com/video/BVxxx
    • https://b23.tv/xxx（短链接）
    • https://www.bilibili.com/video/avxxx

  抖音：
    • https://www.douyin.com/video/xxx
    • https://v.douyin.com/xxx（短链接）

📌 使用示例
  /解析 https://www.xiaohongshu.com/explore/abc123
  /xhs https://xhslink.com/xxxx
  /bilibili https://www.bilibili.com/video/BV1xx411c7mD
  /douyin https://v.douyin.com/xxxx

📌 返回信息
  小红书：
    • 笔记标题、作者、点赞数
    • 无水印高清原图列表
    • 视频链接（如有）

  B站：
    • 视频标题、UP主、封面
    • 播放量、点赞、投币等数据
    • 视频下载链接（如有）

  抖音：
    • 视频标题、作者
    • 点赞、评论、分享数
    • 无水印视频链接

⚠️ 注意事项
  • 请确保链接可公开访问
  • 部分平台可能因反爬策略导致解析失败
  • 下载链接仅供个人学习使用，请遵守平台规范
  • 如遇问题可发送 /解析 help 查看帮助"""


API_TEST_HELP_TEXT = """🔍 LeiZ API 接口连通性测试 使用说明

📌 用途
  对插件依赖的全部 LeiZ 上游接口做一次真实鉴权探测，
  快速定位某个接口是否异常（而非代码问题）。

📌 用法
  /apitest                测试全部接口（别名：/连通测试、/接口测试）
  /apitest help           显示此帮助信息

📌 状态含义
  🟢 正常        接口返回成功
  🟡 HTTP 异常   收到非 200 响应（如 401 鉴权失败 / 402 配额 / 5xx）
  🔴 网络/超时   连接失败或超过配置超时未响应
  ⚫ 跳过        对应客户端未初始化（通常因未配置 API Key）

📌 说明
  • 6 个接口并行探测，总耗时取决于最慢的一个
  • 探测使用每个接口最轻量的只读请求，不消耗图片/音频下载流量
  • 单接口超时由配置项 request_timeout 控制（默认 15s）"""


class PixivAPIClient:
    def __init__(self, api_key: str = "", timeout: int = 15):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "User-Agent": "AstrBot-CurrentCortex-Plugin/1.0",
            "Accept": "application/json, image/*",
            "x-api-key": api_key,
        }

    async def fetch_images(self, **params) -> Dict[str, Any]:
        clean_params = {k: v for k, v in params.items() if v is not None}

        if "excludeAI" in clean_params:
            clean_params["excludeAI"] = bool(clean_params["excludeAI"])

        # 路由判定：只有用户显式提供「过滤参数」时才走 POST（带筛选的 JSON 接口）；
        # r18/num/size 是随机与搜索都通用、且 _build_request_params 总会填充默认值的
        # 参数，不能用于判定路由——否则纯随机请求也会被错误地强制走 POST，导致每次
        # 返回固定的同一张图（随机图固定）。
        has_filter_params = any(
            k in clean_params
            for k in (
                "tag",
                "keyword",
                "uid",
                "excludeAI",
                "aspectRatio",
                "dateAfter",
                "dateBefore",
            )
        )

        async with aiohttp.ClientSession(
            timeout=self._timeout, headers=self._headers
        ) as session:
            try:
                if has_filter_params:
                    logger.info("[Pixiv] 有过滤参数，走 POST 筛选接口")
                    resp = await self._post_request(session, clean_params)
                else:
                    logger.info("[Pixiv] 无过滤参数，走 GET 随机接口")
                    resp = await self._get_request(session, clean_params)

                async with resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        redirect_url = resp.headers.get("Location", "")
                        logger.info(f"Received redirect to: {redirect_url}")
                        return {"type": "redirect", "url": redirect_url}

                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            f"API returned status {resp.status}: {error_text[:500]}"
                        )
                        raise PixivAPIError(
                            f"API 请求失败 (HTTP {resp.status})",
                            status_code=resp.status,
                        )

                    content_type = resp.headers.get("Content-Type", "")
                    if "image" in content_type:
                        image_url = str(resp.url)
                        logger.info(f"Received direct image response: {image_url}")
                        return {"type": "redirect", "url": image_url}

                    data = await resp.json()
                    logger.debug(
                        f"API JSON response keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
                    )
                    return {"type": "json", "data": data}

            except aiohttp.ClientError as e:
                logger.error(f"Network error: {e}")
                raise PixivAPIError(f"网络请求失败: {str(e)}", status_code=0) from e
            except asyncio.TimeoutError:
                logger.error("Request timeout")
                raise PixivAPIError("API 请求超时，请稍后再试", status_code=0)

    async def _get_request(
        self, session: aiohttp.ClientSession, params: Dict[str, Any]
    ):
        logger.debug(f"GET {API_BASE_URL} params={params}")
        return await session.get(API_BASE_URL, params=params, allow_redirects=False)

    async def _post_request(
        self, session: aiohttp.ClientSession, params: Dict[str, Any]
    ):
        body = self._normalize_post_params(params)
        logger.debug(f"POST {API_BASE_URL} body={body}")
        return await session.post(
            API_BASE_URL,
            json=body,
            allow_redirects=False,
        )

    @staticmethod
    def _normalize_post_params(params: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        for k, v in params.items():
            if k == "size" and isinstance(v, str):
                body[k] = [v]
            elif k == "tag":
                # CommandParser 产出的 tag 是 list（多个 tag 参数 = AND 匹配），
                # 单个字符串则包成 list，保证上游接收到的始终是数组形式。
                body[k] = v if isinstance(v, list) else [v]
            else:
                body[k] = v
        return body


class CommandParser:
    PARAM_MAP = {
        "r18": "r18",
        "tag": "tag",
        "keyword": "keyword",
        "num": "num",
        "size": "size",
        "uid": "uid",
        "excludeai": "excludeAI",
        "exclude_ai": "excludeAI",
        "ratio": "aspectRatio",
        "date_after": "dateAfter",
        "date_before": "dateBefore",
    }

    @classmethod
    def parse(cls, raw_text: str) -> Dict[str, Any]:
        if not raw_text or not raw_text.strip():
            return {}

        text = raw_text.strip()
        params: Dict[str, Any] = {}

        key_value_pattern = re.compile(
            r"([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*([^\s]+)",
        )
        consumed_positions = []
        for match in key_value_pattern.finditer(text):
            key = match.group(1).lower()
            value = match.group(2).strip()
            mapped_key = cls.PARAM_MAP.get(key, key)

            if mapped_key == "tag":
                existing = params.get("tag", [])
                existing.append(value)
                params["tag"] = existing
            elif mapped_key in ("r18", "num"):
                try:
                    params[mapped_key] = int(value)
                except ValueError:
                    pass
            elif mapped_key == "excludeAI":
                params[mapped_key] = value.lower() in ("true", "1", "yes")
            else:
                params[mapped_key] = value
            consumed_positions.append((match.start(), match.end()))

        remaining = text
        for start, end in sorted(consumed_positions, reverse=True):
            remaining = remaining[:start] + remaining[end:]

        remaining_tokens = remaining.strip().split()
        for token in remaining_tokens:
            token_lower = token.lower()
            if token_lower == "r18":
                params.setdefault("r18", 1)
            elif token_lower == "mixed":
                params.setdefault("r18", 2)
            elif token_lower == "safe" or token_lower == "sfw":
                params.setdefault("r18", 0)

        return params


class HitokotoAPIClient:
    def __init__(self, api_key: str = "", timeout: int = 10):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "User-Agent": "AstrBot-Hitokoto-Plugin/1.0",
            "Accept": "application/json",
            "x-api-key": api_key,
        }

    async def fetch_hitokoto(
        self,
        category: Optional[str] = None,
        min_length: int = 0,
        max_length: int = 30,
    ) -> Dict[str, Any]:
        params = {
            "encode": "json",
            "min_length": min_length,
            "max_length": max_length,
        }
        if category and category.lower() in HITOKOTO_CATEGORIES:
            params["c"] = category.lower()

        logger.debug(f"Fetching hitokoto with params: {params}")

        async with aiohttp.ClientSession(
            timeout=self._timeout, headers=self._headers
        ) as session:
            try:
                async with session.get(HITOKOTO_API_URL, params=params) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            f"Hitokoto API returned status {resp.status}: {error_text[:500]}"
                        )
                        raise HitokotoAPIError(
                            f"API 请求失败 (HTTP {resp.status})",
                            status_code=resp.status,
                        )

                    data = await resp.json()
                    logger.debug(f"Hitokoto API response: {data}")

                    if not isinstance(data, dict) or "hitokoto" not in data:
                        logger.warning(f"Unexpected hitokoto response format: {data}")
                        raise HitokotoAPIError("API 返回数据格式异常")

                    return {
                        "text": data.get("hitokoto", ""),
                        "from": data.get("from", ""),
                        "type": data.get("type", ""),
                        "category_name": HITOKOTO_CATEGORIES.get(
                            data.get("type", ""), "未知"
                        ),
                    }

            except aiohttp.ClientError as e:
                logger.error(f"Hitokoto network error: {e}")
                raise HitokotoAPIError(f"网络请求失败: {str(e)}", status_code=0) from e
            except asyncio.TimeoutError:
                logger.error("Hitokoto request timeout")
                raise HitokotoAPIError("API 请求超时，请稍后再试", status_code=0)


class WeatherAPIClient:
    def __init__(self, api_key: str = "", timeout: int = 15):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "User-Agent": "AstrBot-Weather-Plugin/1.0",
            "Accept": "application/json",
            "x-api-key": api_key,
        }

    async def fetch_weather(self, city: str) -> Dict[str, Any]:
        if not city or not city.strip():
            raise WeatherAPIError("城市名称不能为空")

        params = {
            "dz": city.strip(),
            "return": "json",
        }

        logger.debug(f"Fetching weather for city: {city}")

        async with aiohttp.ClientSession(
            timeout=self._timeout, headers=self._headers
        ) as session:
            try:
                async with session.get(WEATHER_API_URL, params=params) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            f"Weather API returned status {resp.status}: {error_text[:500]}"
                        )
                        raise WeatherAPIError(
                            f"API 请求失败 (HTTP {resp.status})",
                            status_code=resp.status,
                        )

                    content_type = resp.headers.get("Content-Type", "")
                    if "json" not in content_type:
                        text_data = await resp.text()
                        logger.debug(
                            f"Weather API returned text format: {text_data[:500]}"
                        )
                        return {"type": "text", "data": text_data}

                    data = await resp.json()
                    logger.debug(f"Weather API JSON response: {data}")

                    if not isinstance(data, dict):
                        logger.warning(
                            f"Unexpected weather API response format: {type(data)}"
                        )
                        raise WeatherAPIError("API 返回数据格式异常")

                    if data.get("error"):
                        error_msg = data.get("error", "未知错误")
                        logger.error(f"Weather API returned error: {error_msg}")
                        raise WeatherAPIError(f"API 错误: {error_msg}")

                    weather_data = data.get("data", {})
                    if not weather_data:
                        logger.warning(f"Weather API returned empty data: {data}")
                        raise WeatherAPIError("API 返回数据为空")

                    if not isinstance(weather_data, dict):
                        logger.warning(
                            f"Weather API returned non-dict data: {type(weather_data).__name__}"
                        )
                        raise WeatherAPIError("API 返回数据格式异常")

                    return {
                        "type": "json",
                        "data": weather_data,
                        "city": weather_data.get("city", city),
                        "raw_response": data,
                    }

            except aiohttp.ClientError as e:
                logger.error(f"Weather network error: {e}")
                raise WeatherAPIError(f"网络请求失败: {str(e)}", status_code=0) from e
            except asyncio.TimeoutError:
                logger.error("Weather request timeout")
                raise WeatherAPIError("API 请求超时，请稍后再试", status_code=0)


class FemboyAPIClient:
    def __init__(self, api_key: str = "", timeout: int = 15):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "User-Agent": "AstrBot-Femboy-Plugin/1.0",
            "Accept": "application/json, image/*",
            "x-api-key": api_key,
        }

    async def fetch_femboy_image(self) -> Dict[str, Any]:
        logger.debug("Fetching random femboy image")

        async with aiohttp.ClientSession(
            timeout=self._timeout, headers=self._headers
        ) as session:
            try:
                async with session.get(FEMBOY_API_URL) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            f"Femboy API returned status {resp.status}: {error_text[:500]}"
                        )
                        raise FemboyAPIError(
                            f"API 请求失败 (HTTP {resp.status})",
                            status_code=resp.status,
                        )

                    content_type = resp.headers.get("Content-Type", "")

                    if "image" in content_type:
                        image_url = str(resp.url)
                        logger.info(f"Received direct image response: {image_url}")
                        return {"type": "redirect", "url": image_url}

                    data = await resp.json()
                    logger.debug(f"Femboy API JSON response: {data}")

                    if not isinstance(data, dict):
                        logger.warning(
                            f"Unexpected femboy API response format: {type(data)}"
                        )
                        raise FemboyAPIError("API 返回数据格式异常")

                    if "url" not in data:
                        logger.warning(f"Femboy API missing url field: {data}")
                        raise FemboyAPIError("API 返回数据缺少图片链接")

                    return {
                        "type": "json",
                        "data": {
                            "url": data.get("url", ""),
                            "from": data.get("from", "未知来源"),
                            "note": data.get("note", ""),
                        },
                    }

            except aiohttp.ClientError as e:
                logger.error(f"Femboy network error: {e}")
                raise FemboyAPIError(f"网络请求失败: {str(e)}", status_code=0) from e
            except asyncio.TimeoutError:
                logger.error("Femboy request timeout")
                raise FemboyAPIError("API 请求超时，请稍后再试", status_code=0)


class NeteaseAPIClient:
    def __init__(self, api_key: str = "", timeout: int = 15):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "User-Agent": "AstrBot-Music-Plugin/1.0",
            "Accept": "application/json",
            "x-api-key": api_key,
        }

    # 点歌接口偶发瞬时超时（见日志），对超时/网络错误重试以提升成功率。
    # 重试策略：共 3 次尝试（初次 + 2 次重试），指数退避（0.5s → 1s），
    # 仅对 asyncio.TimeoutError / aiohttp.ClientError 重试；HTTP 业务错误
    # （401/402/5xx 等）和 API 返回的业务错误不重试——它们重试也不会成功。
    #
    # 单次请求超时独立于全局 request_timeout 配置：实测点歌接口成功的请求
    # P95 < 1.5s，卡住的请求会耗尽任何超时上限。故把单次超时压到 6s，
    # 让重试更快触发——失败场景从 15s×3=45s 降到 6s×3≈19s，成功仍秒回。
    NETEASE_MAX_ATTEMPTS = 3
    NETEASE_RETRY_BACKOFF_BASE = 0.5  # 秒；第 n 次重试前等待 base * 2^(n-1)
    NETEASE_REQUEST_TIMEOUT = 6.0  # 秒；单次请求超时（独立于全局 request_timeout）

    async def _get_with_retry(
        self, url: str, params: Dict[str, Any], tag: str
    ) -> Dict[str, Any]:
        """带重试的 GET 请求。返回解析后的 JSON dict。

        - 仅对超时/网络错误重试（共 NETEASE_MAX_ATTEMPTS 次），指数退避。
        - HTTP 非 200 与业务错误（success=false 等）直接抛出，不消耗重试次数。
        - 单次请求使用 NETEASE_REQUEST_TIMEOUT（6s），而非全局 _timeout。
        """
        per_request_timeout = aiohttp.ClientTimeout(total=self.NETEASE_REQUEST_TIMEOUT)
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.NETEASE_MAX_ATTEMPTS + 1):
            async with aiohttp.ClientSession(
                timeout=per_request_timeout, headers=self._headers
            ) as session:
                try:
                    async with session.get(url, params=params) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            logger.error(
                                f"[Netease] {tag} API returned status {resp.status}: {error_text[:500]}"
                            )
                            raise NeteaseAPIError(
                                f"API 请求失败 (HTTP {resp.status})",
                                status_code=resp.status,
                            )
                        data = await resp.json()
                        return data  # 业务校验交由调用方完成
                except asyncio.TimeoutError:
                    last_exc = NeteaseAPIError(
                        "API 请求超时，请稍后再试", status_code=0
                    )
                    logger.warning(
                        f"[Netease] {tag} timeout (attempt {attempt}/{self.NETEASE_MAX_ATTEMPTS})"
                    )
                except aiohttp.ClientError as e:
                    last_exc = NeteaseAPIError(f"网络请求失败: {str(e)}", status_code=0)
                    logger.warning(
                        f"[Netease] {tag} network error (attempt {attempt}/{self.NETEASE_MAX_ATTEMPTS}): {e}"
                    )

            # 此处仅在网络/超时错误时到达：决定是否重试
            if attempt < self.NETEASE_MAX_ATTEMPTS:
                backoff = self.NETEASE_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.debug(f"[Netease] {tag} retrying in {backoff}s")
                await asyncio.sleep(backoff)

        # 所有尝试均失败
        assert last_exc is not None
        raise last_exc

    async def get_song(
        self, song_id: str, level: Optional[str] = None
    ) -> Dict[str, Any]:
        """通过歌曲ID获取歌曲信息和播放链接"""
        if not song_id or not song_id.strip():
            raise NeteaseAPIError("歌曲ID不能为空")

        params = {"id": song_id.strip()}
        if level:
            params["level"] = level
        logger.debug(f"[Netease] Fetching song by id: {song_id}, level: {level}")

        data = await self._get_with_retry(NETEASE_API_URL, params, "get_song")
        logger.debug(f"[Netease] Song response: {data}")

        if not isinstance(data, dict):
            raise NeteaseAPIError("API 返回数据格式异常")

        if not data.get("success"):
            msg = data.get("message", "未知错误")
            raise NeteaseAPIError(f"获取歌曲失败: {msg}")

        song_data = data.get("data", {})
        if not song_data:
            raise NeteaseAPIError("API 返回歌曲数据为空")

        if not isinstance(song_data, dict):
            raise NeteaseAPIError("API 返回歌曲数据格式异常")

        return song_data

    async def search_songs(self, query: str) -> List[Dict[str, Any]]:
        """通过关键词搜索歌曲"""
        if not query or not query.strip():
            raise NeteaseAPIError("搜索关键词不能为空")

        params = {"q": query.strip()}
        logger.debug(f"[Netease] Searching songs: {query}")

        data = await self._get_with_retry(NETEASE_SEARCH_URL, params, "search_songs")
        logger.debug(
            f"[Netease] Search response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}"
        )

        if not isinstance(data, dict):
            raise NeteaseAPIError("API 返回数据格式异常")

        if not data.get("success"):
            msg = data.get("message", "未知错误")
            raise NeteaseAPIError(f"搜索失败: {msg}")

        songs = data.get("data", [])
        if not isinstance(songs, list):
            raise NeteaseAPIError("API 返回搜索结果格式异常")

        return songs


class KugouAPIClient:
    """酷狗音乐 API 客户端。返回字段结构与 NeteaseAPIClient 对齐
   （url/level/size/type/bitrate/name/artists/album/pic），便于统一处理。"""

    def __init__(self, api_key: str = "", timeout: int = 15):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "User-Agent": "AstrBot-Music-Plugin/1.0",
            "Accept": "application/json",
            "x-api-key": api_key,
        }
        # 复用与网易云相同的重试/超时策略
        self.NETEASE_MAX_ATTEMPTS = 3
        self.NETEASE_RETRY_BACKOFF_BASE = 0.5
        self.NETEASE_REQUEST_TIMEOUT = 6.0

    async def _get_with_retry(
        self, url: str, params: Dict[str, Any], tag: str
    ) -> Dict[str, Any]:
        """带重试的 GET 请求（同 NeteaseAPIClient._get_with_retry）。"""
        per_request_timeout = aiohttp.ClientTimeout(total=self.NETEASE_REQUEST_TIMEOUT)
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.NETEASE_MAX_ATTEMPTS + 1):
            async with aiohttp.ClientSession(
                timeout=per_request_timeout, headers=self._headers
            ) as session:
                try:
                    async with session.get(url, params=params) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            logger.error(
                                f"[Kugou] {tag} API returned status {resp.status}: {error_text[:500]}"
                            )
                            raise NeteaseAPIError(
                                f"API 请求失败 (HTTP {resp.status})",
                                status_code=resp.status,
                            )
                        data = await resp.json()
                        return data
                except asyncio.TimeoutError:
                    last_exc = NeteaseAPIError("API 请求超时，请稍后再试", status_code=0)
                    logger.warning(
                        f"[Kugou] {tag} timeout (attempt {attempt}/{self.NETEASE_MAX_ATTEMPTS})"
                    )
                except aiohttp.ClientError as e:
                    last_exc = NeteaseAPIError(f"网络请求失败: {str(e)}", status_code=0)
                    logger.warning(
                        f"[Kugou] {tag} network error (attempt {attempt}/{self.NETEASE_MAX_ATTEMPTS}): {e}"
                    )

            if attempt < self.NETEASE_MAX_ATTEMPTS:
                backoff = self.NETEASE_RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

        assert last_exc is not None
        raise last_exc

    async def get_song(
        self, song_id: str = "", hash_val: str = ""
    ) -> Dict[str, Any]:
        """通过 hash 或内部 ID 获取歌曲信息和播放链接。

        酷狗优先用 hash（更稳定）；无 hash 时用 id。两者都无则报错。
        """
        params: Dict[str, Any] = {}
        if hash_val:
            params["hash"] = hash_val
        elif song_id:
            params["id"] = song_id
        else:
            raise NeteaseAPIError("歌曲 hash 或 ID 不能为空")

        logger.debug(f"[Kugou] Fetching song: id={song_id}, hash={hash_val}")
        data = await self._get_with_retry(KUGOU_API_URL, params, "get_song")

        if not isinstance(data, dict):
            raise NeteaseAPIError("API 返回数据格式异常")
        if not data.get("success"):
            msg = data.get("message", "未知错误")
            raise NeteaseAPIError(f"获取歌曲失败: {msg}")

        song_data = data.get("data", {})
        if not song_data or not isinstance(song_data, dict):
            raise NeteaseAPIError("API 返回歌曲数据为空")
        return song_data

    async def search_songs(self, query: str) -> List[Dict[str, Any]]:
        """通过关键词搜索歌曲。"""
        if not query or not query.strip():
            raise NeteaseAPIError("搜索关键词不能为空")

        params = {"q": query.strip()}
        logger.debug(f"[Kugou] Searching songs: {query}")
        data = await self._get_with_retry(KUGOU_SEARCH_URL, params, "search_songs")

        if not isinstance(data, dict):
            raise NeteaseAPIError("API 返回数据格式异常")
        if not data.get("success"):
            msg = data.get("message", "未知错误")
            raise NeteaseAPIError(f"搜索失败: {msg}")

        songs = data.get("data", [])
        if not isinstance(songs, list):
            raise NeteaseAPIError("API 返回搜索结果格式异常")
        return songs


class JMComicAPIClient:
    """JMComic 漫画 API 客户端"""

    def __init__(self, api_key: str = "", timeout: int = 30):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "x-api-key": api_key,
        }

    async def search(self, query: str, page: int = 1) -> Dict[str, Any]:
        """搜索漫画"""
        if not query or not query.strip():
            raise JMComicAPIError("搜索关键词不能为空")

        params = {"query": query.strip(), "page": page}
        logger.debug(f"[JMComic] Searching: query={query}, page={page}")

        async with aiohttp.ClientSession(
            timeout=self._timeout, headers=self._headers
        ) as session:
            try:
                async with session.get(
                    f"{JMCOMIC_API_BASE}/search", params=params
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            f"[JMComic] Search API returned status {resp.status}: {error_text[:500]}"
                        )
                        raise JMComicAPIError(
                            f"API 请求失败 (HTTP {resp.status})",
                            status_code=resp.status,
                        )

                    data = await resp.json()
                    if not isinstance(data, dict):
                        raise JMComicAPIError("API 返回数据格式异常")

                    if not data.get("success"):
                        msg = data.get("message", "未知错误")
                        raise JMComicAPIError(f"搜索失败: {msg}")

                    return data.get("data", {})

            except aiohttp.ClientError as e:
                logger.error(f"[JMComic] Search network error: {e}")
                raise JMComicAPIError(f"网络请求失败: {str(e)}", status_code=0) from e
            except asyncio.TimeoutError:
                logger.error("[JMComic] Search request timeout")
                raise JMComicAPIError("API 请求超时，请稍后再试", status_code=0)

    async def get_detail(self, comic_id: str) -> Dict[str, Any]:
        """获取漫画详情"""
        if not comic_id or not comic_id.strip():
            raise JMComicAPIError("漫画ID不能为空")

        comic_id = comic_id.strip()
        logger.debug(f"[JMComic] Fetching detail: id={comic_id}")

        async with aiohttp.ClientSession(
            timeout=self._timeout, headers=self._headers
        ) as session:
            try:
                async with session.get(f"{JMCOMIC_API_BASE}/album/{comic_id}") as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            f"[JMComic] Detail API returned status {resp.status}: {error_text[:500]}"
                        )
                        raise JMComicAPIError(
                            f"API 请求失败 (HTTP {resp.status})",
                            status_code=resp.status,
                        )

                    data = await resp.json()
                    if not isinstance(data, dict):
                        raise JMComicAPIError("API 返回数据格式异常")

                    if not data.get("success"):
                        msg = data.get("message", "未知错误")
                        raise JMComicAPIError(f"获取详情失败: {msg}")

                    return data.get("data", {})

            except aiohttp.ClientError as e:
                logger.error(f"[JMComic] Detail network error: {e}")
                raise JMComicAPIError(f"网络请求失败: {str(e)}", status_code=0) from e
            except asyncio.TimeoutError:
                logger.error("[JMComic] Detail request timeout")
                raise JMComicAPIError("API 请求超时，请稍后再试", status_code=0)

    async def get_chapter(self, chapter_id: str) -> Dict[str, Any]:
        """获取章节图片列表"""
        if not chapter_id or not chapter_id.strip():
            raise JMComicAPIError("章节ID不能为空")

        chapter_id = chapter_id.strip()
        params = {"chapter": "all"}
        logger.debug(f"[JMComic] Fetching chapter: id={chapter_id}")

        async with aiohttp.ClientSession(
            timeout=self._timeout, headers=self._headers
        ) as session:
            try:
                async with session.get(
                    f"{JMCOMIC_API_BASE}/images/{chapter_id}", params=params
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(
                            f"[JMComic] Chapter API returned status {resp.status}: {error_text[:500]}"
                        )
                        raise JMComicAPIError(
                            f"API 请求失败 (HTTP {resp.status})",
                            status_code=resp.status,
                        )

                    data = await resp.json()
                    if not isinstance(data, dict):
                        raise JMComicAPIError("API 返回数据格式异常")

                    if not data.get("success"):
                        msg = data.get("message", "未知错误")
                        raise JMComicAPIError(f"获取章节失败: {msg}")

                    return data.get("data", {})

            except aiohttp.ClientError as e:
                logger.error(f"[JMComic] Chapter network error: {e}")
                raise JMComicAPIError(f"网络请求失败: {str(e)}", status_code=0) from e
            except asyncio.TimeoutError:
                logger.error("[JMComic] Chapter request timeout")
                raise JMComicAPIError("API 请求超时，请稍后再试", status_code=0)


class NeteaseAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class HitokotoAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class WeatherAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class FemboyAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class PixivAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class JMComicAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def _format_api_key_not_configured(feature_name: str) -> str:
    """统一生成「LeiZ API Key 未配置」提示，供所有依赖 LeiZ 接口的命令复用。"""
    return (
        f"❌ {feature_name}功能未启用\n\n"
        "📝 原因：未配置 LeiZ API 统一密钥\n"
        "💡 解决方法：\n"
        "   1. 打开插件配置面板\n"
        "   2. 找到「LeiZ API 统一密钥 (leiz_api_key)」字段\n"
        "   3. 填写您的 API Key（请求头 x-api-key）\n"
        "   4. 保存配置并重启插件\n\n"
        "⚠️ 根据 LeiZ API 公告，所有接口（含免费接口）均需携带 API Key"
    )


def _remove_file_safe(file_path: str) -> None:
    """安全删除文件，忽略不存在 / 删除失败的情况（用于临时文件清理）。"""
    try:
        os.remove(file_path)
    except (FileNotFoundError, OSError):
        pass


def _track_jm_temp_file(event: AstrMessageEvent, path: str) -> None:
    """把章节临时图片交给框架，在整条流水线发送完成后统一清理。

    Comp.Image.fromFileSystem 是延迟读取的：实际的文件读取（转 base64）
    发生在发送阶段 Node.to_dict() 中，远晚于此处构建节点的时刻。因此不能
    在 _format_jm_chapter 返回前删除，否则合并转发节点内的图片将为空。

    优先使用框架的 track_temporary_local_file（发送完成后由 scheduler 统一删除）。
    若当前 AstrBot 版本未提供该 API，则不主动删除，交由系统临时目录按 TTL 清理。
    """
    tracker = getattr(event, "track_temporary_local_file", None)
    if callable(tracker):
        try:
            tracker(path)
        except Exception:
            pass


# JMComic 章节续看游标的有效期：章节图片 URL 有时效，过期则丢弃游标。
_JM_CHAPTER_CURSOR_TTL = 30 * 60


@register(
    "astrbot_plugin_currentcortex",
    "Rcst20",
    "多功能 AstrBot 插件（CurrentCortex）—— Pixiv 随机图片 ·网易云点歌 ·JMComic 漫画 ·小红书/B站/抖音媒体解析 ·每日一言 ·天气 ·男娘 ·DG-LAB（郊狼） 设备管理 ·跨群聊记忆 ·按群聊开关。基于 LeiZ API。",
    "1.5.8",
)
class CurrentCortexPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        self._default_r18 = int(config.get("default_r18", 0))
        self._default_num = max(1, min(20, int(config.get("default_num", 1))))
        self._default_size = str(config.get("default_size", "regular"))
        self._image_proxy = str(config.get("image_proxy", "pixiv.bileizhen.top"))
        self._exclude_ai = bool(config.get("exclude_ai", False))
        self._request_timeout = int(config.get("request_timeout", 15))
        # LLM 工具（function calling）总开关：装饰器在类加载时已注册工具，
        # 此开关控制工具执行时是否放行；关闭时工具返回提示而不执行。
        self._llm_tools_enable = bool(config.get("llm_tools_enable", False))
        if self._llm_tools_enable:
            logger.info("[LLMTools] 已启用 LLM 工具（图片/点歌/电击）")

        # JMComic 章节图片下发：单张压缩阈值 + 每命令分段大小
        # 单条合并转发节点过多 / payload 过大会被 QQ 服务端拒绝（retcode=1200），
        # 故 page_size 取偏保守的 20；图片统一转 JPEG 防止 webp 触发风控。
        self._jm_image_max_bytes = int(
            config.get("jm_image_max_bytes", 2 * 1024 * 1024)
        )
        self._jm_page_size = max(1, int(config.get("jm_page_size", 20)))
        # 章节续看游标：{session_id: {"chapter_id", "images", "offset", "ts"}}
        # 仅内存保存，章节 URL 有时效；超过 TTL 自动清理。
        self._jm_chapter_cursor: Dict[str, dict] = {}
        # /音乐 文件 模式：原始文件（如 flac）过大时 QQ/NapCat 端常 retcode=1200 失败，
        # 超过该阈值则转码为 128kbps MP3 再发送（需 ffmpeg）。0 = 不限制。
        self._music_file_max_bytes = max(0, int(config.get("music_file_max_bytes", 25 * 1024 * 1024)))
        # 点歌并发防护：同一会话进行中去重 + 完成后冷却，防止用户连点触发大量并发
        # 下载/转码拖垮服务器。单线程 asyncio 下 dict/set 操作原子，无需加锁。
        self._music_in_progress: set[str] = set()
        self._music_last_done: dict[str, float] = {}
        self._music_cooldown = max(0, int(config.get("music_cooldown", 3)))
        # 音源偏好：按会话(umo)记忆 auto/netease/kugou；纯内存，重启重置为默认
        self._music_default_source = str(config.get("music_default_source", "auto")).strip().lower()
        if self._music_default_source not in ("auto", "netease", "kugou"):
            self._music_default_source = "auto"
        self._music_source_pref: dict[str, str] = {}

        # LeiZ API 统一鉴权：所有接口（含免费接口）均需携带 API Key。
        # 经实测，LeiZ 服务端实际通过 x-api-key 请求头校验（而非公告中提及的
        # Authorization: Bearer）。此处统一以 x-api-key 形式下发到各客户端。
        leiz_api_key = str(config.get("leiz_api_key", "")).strip()

        # 向后兼容：若未配置 leiz_api_key 但存在旧版 femboy_api_key，则回退使用，
        # 并提示用户迁移到统一的 leiz_api_key 配置项。
        if not leiz_api_key:
            legacy_femboy_key = str(config.get("femboy_api_key", "")).strip()
            if legacy_femboy_key:
                leiz_api_key = legacy_femboy_key
                logger.warning(
                    "[LeiZ] 检测到旧版配置 femboy_api_key，已自动作为统一 API Key 使用。"
                    "建议尽快在配置面板迁移到 leiz_api_key 字段（femboy_api_key 将在后续版本移除）。"
                )

        self._leiz_api_key = leiz_api_key
        self._media_parser = MediaParserManager(timeout=self._request_timeout)

        if not leiz_api_key:
            # 未配置统一 API Key：禁用所有依赖 LeiZ 接口的客户端，相关命令会在
            # 调用时通过守卫提示用户配置。
            logger.warning(
                "⚠️ 未配置 LeiZ API 统一密钥 (leiz_api_key)，Pixiv/一言/天气/男娘/点歌/JMComic "
                "等全部 LeiZ 接口命令将不可用"
            )
            logger.warning(
                "根据 LeiZ API 公告，所有接口（含免费接口）均需携带 API Key。"
                "请在插件配置面板中填写 leiz_api_key 字段后重启插件。"
            )
            self._api_client = None
            self._hitokoto_client = None
            self._weather_client = None
            self._femboy_client = None
            self._netease_client = None
            self._kugou_client = None
            self._jmcomic_client = None
        else:
            self._api_client = PixivAPIClient(
                api_key=leiz_api_key, timeout=self._request_timeout
            )
            self._hitokoto_client = HitokotoAPIClient(
                api_key=leiz_api_key, timeout=self._request_timeout
            )
            self._weather_client = WeatherAPIClient(
                api_key=leiz_api_key, timeout=self._request_timeout
            )
            self._femboy_client = FemboyAPIClient(
                api_key=leiz_api_key, timeout=self._request_timeout
            )
            self._netease_client = NeteaseAPIClient(
                api_key=leiz_api_key, timeout=self._request_timeout
            )
            self._kugou_client = KugouAPIClient(
                api_key=leiz_api_key, timeout=self._request_timeout
            )
            self._jmcomic_client = JMComicAPIClient(
                api_key=leiz_api_key, timeout=self._request_timeout
            )
            logger.info("✅ LeiZ API 客户端初始化成功（统一 x-api-key 鉴权）")

        # 读取 DG-LAB 新独立配置项（优先），兼容旧版 JSON 字符串配置
        server_url = str(config.get("dglab_server_url", "")).strip()
        heartbeat_interval = float(config.get("dglab_heartbeat_interval", 60))
        auto_connect = bool(config.get("dglab_auto_connect", False))

        # 向后兼容：若新配置未填写但存在旧版 dglab 配置，则尝试解析
        if not server_url:
            dglab_config_raw = config.get("dglab", "")
            dglab_config = {}
            if isinstance(dglab_config_raw, dict):
                dglab_config = dglab_config_raw
            elif isinstance(dglab_config_raw, str) and dglab_config_raw.strip():
                import json as _json

                try:
                    parsed = _json.loads(dglab_config_raw)
                    if isinstance(parsed, dict):
                        dglab_config = parsed
                    else:
                        logger.warning(f"[DGLab] 配置解析结果不是字典: {type(parsed)}")
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[DGLab] 配置JSON解析失败: {e}, 原始值: {repr(dglab_config_raw[:100])}"
                    )

            fallback_server_url = dglab_config.get("server_url", "").strip()
            if fallback_server_url:
                server_url = fallback_server_url
                heartbeat_interval = float(
                    dglab_config.get("heartbeat_interval", heartbeat_interval)
                )
                auto_connect = bool(dglab_config.get("auto_connect", auto_connect))
                logger.info(
                    "[DGLab] 已从旧版 dglab JSON 配置迁移到新的独立配置项，建议更新配置面板"
                )

        self._device_store = DeviceStore(data_dir="data")
        self._connection_pool = DeviceConnectionPool(
            device_store=self._device_store,
            max_connections=200,
            idle_timeout=300,
            operation_timeout=10.0,
        )
        self._dglab_handler = DGLabCommandHandler(
            connection_pool=self._connection_pool,
            device_store=self._device_store,
            default_server_url=server_url,
        )

        self._user_store = UserStore(data_dir="data")
        self._permission_store = PermissionStore(data_dir="data")

        webui_enabled = bool(config.get("dglab_webui_enabled", False))
        webui_host = str(config.get("dglab_webui_host", "127.0.0.1")).strip()
        webui_port = int(config.get("dglab_webui_port", 9178))
        self._dglab_webui: Optional[DGLabWebUI] = None
        if webui_enabled:
            # 安全：监听 0.0.0.0 表示暴露到公网，明确告警
            if webui_host in ("0.0.0.0", "::"):
                logger.warning(
                    "[CurrentCortex] ⚠️ WebUI 监听地址为 %s，将暴露到公网！"
                    "请确保已配置反向代理与访问控制，否则任何人都能访问注册/登录等接口。",
                    webui_host,
                )
            self._dglab_webui = DGLabWebUI(
                connection_pool=self._connection_pool,
                device_store=self._device_store,
                user_store=self._user_store,
                permission_store=self._permission_store,
                host=webui_host,
                port=webui_port,
            )
        else:
            logger.info(
                "[CurrentCortex] WebUI 未启用（默认关闭）。如需启用，请在配置中开启 "
                "dglab_webui_enabled，并注意 WebUI 安全（建议仅本地或经反代+鉴权后公网访问）。"
            )

        if server_url:
            logger.info(
                f"✅ CurrentCortex 模块已初始化 (server={server_url}, auto_connect={auto_connect})"
            )
        else:
            logger.info(
                "ℹ️ CurrentCortex 模块已就绪（未配置服务器地址，用户需手动指定）"
            )

        try:
            asyncio.get_running_loop()
            asyncio.create_task(self._connection_pool.start())
            if self._dglab_webui:
                asyncio.create_task(self._dglab_webui.start())
        except RuntimeError:
            self._pool_started = False
        else:
            self._pool_started = True

        logger.info(
            f"CurrentCortexPlugin initialized: r18={self._default_r18}, num={self._default_num}, "
            f"size={self._default_size}, proxy={self._image_proxy}, excludeAI={self._exclude_ai}"
        )

        # 跨群聊记忆：同一平台实例下所有群聊共享的持久化记忆（JSON 文件存储）
        self._cross_group_enable = bool(config.get("cross_group_enable", False))
        self._cross_group_max_cnt = max(1, int(config.get("cross_group_max_cnt", 500)))
        self._cross_group_inject_cnt = max(
            0, int(config.get("cross_group_inject_cnt", 30))
        )
        self._cross_group_store: "CrossGroupMemoryStore | None" = None
        if self._cross_group_enable:
            try:
                self._cross_group_store = CrossGroupMemoryStore(data_dir="data")
                logger.info(
                    f"[CrossGroupMemory] 已启用跨群聊记忆 "
                    f"(max_cnt={self._cross_group_max_cnt}, inject_cnt={self._cross_group_inject_cnt})"
                )
            except Exception as e:
                logger.warning(f"[CrossGroupMemory] 初始化失败，已禁用: {e}")
                self._cross_group_store = None
                self._cross_group_enable = False

        # 按群聊独立开关插件：可在单个群用 /开关 命令关闭/开启本插件全部命令。
        # 存储为「黑名单」语义——默认所有会话启用，只有显式关闭的群会被守卫拦截。
        self._group_switch_enable = bool(config.get("group_switch_enable", True))
        self._group_switch_admin_only = bool(
            config.get("group_switch_admin_only", True)
        )
        self._group_switch_store: "GroupSwitchStore | None" = None
        if self._group_switch_enable:
            try:
                self._group_switch_store = GroupSwitchStore(data_dir="data")
                logger.info(
                    "[GroupSwitch] 已启用按群聊开关功能"
                    f"（admin_only={self._group_switch_admin_only}）"
                )
            except Exception as e:
                logger.warning(f"[GroupSwitch] 初始化失败，已禁用: {e}")
                self._group_switch_store = None
                self._group_switch_enable = False

        # 分段回复：把机器人回复拆成多条消息分次发送（模拟逐条回复）。
        # 通过 on_decorating_result 钩子在框架自带分段/发送前介入。
        self._reply_seg_enable = bool(config.get("reply_seg_enable", False))
        self._reply_seg_only_llm = bool(config.get("reply_seg_only_llm", True))
        self._reply_seg_mode = str(config.get("reply_seg_mode", "punct")).strip()
        self._reply_seg_symbols = str(
            config.get("reply_seg_split_symbols", "。！？!?~～…\n,，")
        )
        # 切分词（可多字符，空格分隔），如「喵 qwq owo」。在词的后面切分，词保留在段尾。
        # 默认只含多字符颜文字词；单字符词（如 w）会误切英文单词、左括号（会破坏
        # 括号配对，故默认不带，用户可按需自行增删。
        self._reply_seg_words = [
            w for w in str(
                config.get("reply_seg_split_words", "喵 qwq owo awa ovo")
            ).split() if w
        ]
        # punct 模式：短于此长度的段会被合并到前一段（纯标点段无条件合并）；
        # 设为 0 可关闭合并。用于消除逗号切出的碎片和孤立标点段。
        self._reply_seg_merge_threshold = max(0, int(config.get("reply_seg_merge_threshold", 4)))
        self._reply_seg_min_length = max(1, int(config.get("reply_seg_min_length", 15)))
        self._reply_seg_max_length = max(
            self._reply_seg_min_length + 1, int(config.get("reply_seg_max_length", 80))
        )
        # 解析延时范围 "min,max" -> (min, max)
        self._reply_seg_delay_range = self._parse_delay_range(
            str(config.get("reply_seg_delay_range", "0.8,2.5"))
        )
        # llm 模式：调用大模型做语义级分段。
        # provider_id 留空则复用当前会话的模型；建议配专用的廉价快速模型以省时省钱。
        self._reply_seg_llm_provider_id = str(
            config.get("reply_seg_llm_provider_id", "")
        ).strip()
        # llm 模式：分段密度档位（low/medium/high），决定每段目标字数区间。
        # low=每段长(~40-70字)、medium=适中(~20-45字)、high=每段短碎(~10-25字)。
        # 档位会同时影响 prompt 引导和段数上限的推算。
        self._reply_seg_llm_density = str(
            config.get("reply_seg_llm_density", "medium")
        ).strip().lower()
        if self._reply_seg_llm_density not in self._REPLY_SEG_DENSITY_PROFILES:
            self._reply_seg_llm_density = "medium"
        # llm 模式：分段数量上限。用户可显式配置；留空(0或负)则由档位自动推算。
        cfg_max_seg = int(config.get("reply_seg_llm_max_segments", 0) or 0)
        if cfg_max_seg > 0:
            self._reply_seg_llm_max_segments = cfg_max_seg
        else:
            self._reply_seg_llm_max_segments = self._REPLY_SEG_DENSITY_PROFILES[
                self._reply_seg_llm_density
            ]["max_segments"]
        # llm 模式：原文短于此长度时不调用 LLM，直接整段发送（省钱省时间）。
        self._reply_seg_llm_min_chars = max(0, int(config.get("reply_seg_llm_min_chars", 30)))
        # llm 模式：单次分段调用超时（秒）。超时则降级规则分段，避免回复过慢。
        self._reply_seg_llm_timeout = max(3, int(config.get("reply_seg_llm_timeout", 15)))
        # llm 模式：分段输出 token 上限。分段结果是 JSON 数组，输出量小，限制可加速返回。
        self._reply_seg_llm_max_tokens = max(64, int(config.get("reply_seg_llm_max_tokens", 512)))
        if self._reply_seg_enable:
            logger.info(
                f"[ReplySeg] 已启用分段回复（mode={self._reply_seg_mode}, "
                f"only_llm={self._reply_seg_only_llm}, delay={self._reply_seg_delay_range}）"
            )

    @staticmethod
    def _parse_delay_range(raw: str) -> tuple:
        """把 "min,max" 解析为 (min, max) 浮点元组，非法则回退 (0.8, 2.5)。"""
        try:
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) == 2:
                lo, hi = float(parts[0]), float(parts[1])
                if lo > hi:
                    lo, hi = hi, lo
                if lo < 0:
                    lo = 0.0
                return (lo, max(hi, lo))
        except (ValueError, IndexError):
            pass
        return (0.8, 2.5)

    @filter.event_message_type(EventMessageType.ALL, priority=10)
    async def on_message_group_switch_guard(self, event: AstrMessageEvent):
        """高优先级守卫：被关闭的群聊中，静默拦截本插件除开关命令外的所有命令。

        priority=10 高于普通命令处理器（默认 0），先于它们执行；此处若
        event.stop_event()，后续本插件命令都不会再触发。开关命令自身放行，
        因此随时可用 /开关 on 重新启用，不会出现「关闭后无法再开」的死锁。
        """
        if not self._group_switch_enable or self._group_switch_store is None:
            return
        try:
            # 仅群聊受控；私聊一律放行
            if event.get_message_type() != MessageType.GROUP_MESSAGE:
                return
            umo = event.unified_msg_origin
            if not umo or self._group_switch_store.is_enabled(umo):
                return
            # 该群已被关闭：若是开关命令则放行（保证可重新启用），否则静默拦截
            if self._is_switch_command(event.message_str):
                return
            event.stop_event()
        except Exception as e:
            logger.error(f"[GroupSwitch] 守卫处理异常（默认放行）: {e}")

    def _is_switch_command(self, message: str) -> bool:
        """判断消息是否为本插件的开关命令（含中英文与别名、带/不带前缀）。"""
        if not message:
            return False
        normalized = re.sub(r"^[/!！]\s*", "", message.strip()).strip().lower()
        return any(
            normalized == kw or normalized.startswith(kw + " ")
            for kw in ("开关", "toggle", "switch")
        )

    @filter.command("开关", alias={"toggle", "switch"}, priority=10)
    async def group_switch_command(self, event: AstrMessageEvent):
        """按群聊独立开启/关闭本插件全部命令。

        无参数=查看当前状态；on/开=启用；off/关=关闭；status/状态=查看状态。
        仅在群聊中有效；默认仅群管理员可操作。
        """
        if not self._group_switch_enable or self._group_switch_store is None:
            yield event.plain_result(
                "❌ 按群聊开关功能未启用\n"
                "💡 请在插件配置中开启 group_switch_enable 后重启插件"
            )
            return

        if event.get_message_type() != MessageType.GROUP_MESSAGE:
            yield event.plain_result("💡 该命令仅在群聊中可用")
            return

        umo = event.unified_msg_origin
        user_name = event.get_sender_name()

        # 权限校验：默认仅管理员可操作
        if self._group_switch_admin_only and not event.is_admin():
            logger.info(
                f"[GroupSwitch] 非管理员 {user_name} 尝试操作开关（已拒绝）"
            )
            yield event.plain_result(
                "❌ 仅群管理员可操作此开关\n"
                "💡 若你是群主/管理员但仍提示无权限，"
                "可在插件配置中关闭 group_switch_admin_only"
            )
            return

        message_str = event.message_str.strip()
        action = self._parse_switch_action(message_str)

        currently_enabled = self._group_switch_store.is_enabled(umo)

        if action == "status":
            state = "✅ 已启用" if currently_enabled else "⛔ 已关闭"
            yield event.plain_result(
                f"🔌 本群插件状态\n{state}\n\n"
                "💡 用法：\n"
                "  /开关 off  关闭本群全部插件命令\n"
                "  /开关 on   重新启用"
            )
            return

        if action == "off":
            if not currently_enabled:
                yield event.plain_result("ℹ️ 本群插件已经是关闭状态")
                return
            self._group_switch_store.set_disabled(umo)
            logger.info(f"[GroupSwitch] 用户 {user_name} 关闭了会话 {umo} 的插件")
            yield event.plain_result(
                "⛔ 已在本群关闭 CurrentCortex 插件全部命令\n\n"
                "💡 重新启用：发送 /开关 on\n"
                "（开关命令始终可用，不会被拦截）"
            )
            return

        if action == "on":
            if currently_enabled:
                yield event.plain_result("ℹ️ 本群插件已经是启用状态")
                return
            self._group_switch_store.set_enabled(umo)
            logger.info(f"[GroupSwitch] 用户 {user_name} 启用了会话 {umo} 的插件")
            yield event.plain_result(
                "✅ 已在本群重新启用 CurrentCortex 插件全部命令"
            )
            return

        # 未知动作：给出帮助
        state = "✅ 已启用" if currently_enabled else "⛔ 已关闭"
        yield event.plain_result(
            f"🔌 本群插件状态：{state}\n\n"
            "💡 用法：\n"
            "  /开关 off（或 关）  关闭本群全部插件命令\n"
            "  /开关 on（或 开）   重新启用\n"
            "  /开关 status（或 状态）  查看当前状态"
        )

    def _parse_switch_action(self, message: str) -> str:
        """从开关命令消息中解析动作：on / off / status / （空）。"""
        cleaned = re.sub(
            r"^[/!！]\s*(开关|toggle|switch)\s*",
            "",
            message.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(开关|toggle|switch)\s*",
            "",
            cleaned.strip(),
            flags=re.IGNORECASE,
        )
        token = cleaned.strip().lower()
        if token in ("on", "开", "enable", "启用"):
            return "on"
        if token in ("off", "关", "disable", "关闭", "禁用"):
            return "off"
        if token in ("status", "状态", "查看", "query"):
            return "status"
        return ""

    def _format_cross_group_record(self, event: AstrMessageEvent) -> str:
        """Format a group message into a single record line for cross-group memory.

        Args:
            event: The group message event.

        Returns:
            A formatted string like ``[昵称/HH:MM:SS]: 文本``.
        """
        import datetime as _dt

        nickname = event.get_sender_name() or "未知"
        time_str = _dt.datetime.now().strftime("%H:%M:%S")
        text = event.message_str or ""
        return f"[{nickname}/{time_str}]: {text}".strip()

    @filter.platform_adapter_type(filter.PlatformAdapterType.ALL)
    async def on_cross_group_message(self, event: AstrMessageEvent):
        """记录群聊消息到跨群聊记忆（同一平台实例下所有群共享）。"""
        if not self._cross_group_enable or self._cross_group_store is None:
            return
        try:
            if event.get_message_type() != MessageType.GROUP_MESSAGE:
                return
            # 跳过命令消息：斜杠命令是给机器人的指令，不应作为群聊上下文记录
            if event.get_extra("handlers_parsed_params", {}):
                return
            platform_id = event.get_platform_id()
            if not platform_id:
                return
            text = event.message_str
            if text is None:
                return
            record = self._format_cross_group_record(event)
            if not record:
                return
            self._cross_group_store.record(
                platform_id, record, self._cross_group_max_cnt
            )
        except Exception as e:
            logger.error(f"[CrossGroupMemory] 记录消息失败: {e}")

    @filter.on_llm_request()
    async def on_cross_group_llm_request(
        self, event: AstrMessageEvent, req: ProviderRequest
    ) -> None:
        """将同平台其他群的最近共享上下文注入 LLM 请求。"""
        if not self._cross_group_enable or self._cross_group_store is None:
            return
        try:
            if event.get_message_type() != MessageType.GROUP_MESSAGE:
                return
            platform_id = event.get_platform_id()
            if not platform_id:
                return
            shared = self._cross_group_store.get_recent(
                platform_id, self._cross_group_inject_cnt
            )
            if not shared:
                return
            block = (
                "<system_reminder>"
                "You are also active in other groups of the same platform. "
                "Below is recent shared context from those groups:\n"
                "--- BEGIN SHARED CONTEXT ---\n"
                + "\n".join(shared)
                + "\n--- END SHARED CONTEXT ---\n</system_reminder>"
            )
            req.extra_user_content_parts.append(TextPart(text=block))
        except Exception as e:
            logger.error(f"[CrossGroupMemory] 注入上下文失败: {e}")

    # =================================================================== #
    # LLM 工具（function calling）：把图片获取 / 点歌 / 电击控制注册为
    # 大模型可调用的工具。装饰器在类加载时注册，运行时由 _llm_tools_enable
    # 开关控制是否放行；媒体类工具直接 event.send，return str 给 LLM 总结。
    # 业务逻辑全部复用现有服务方法，零重写。
    # =================================================================== #

    def _llm_tool_guard(self) -> Optional[str]:
        """LLM 工具执行前的统一开关检查；返回提示字符串则拦截。"""
        if not self._llm_tools_enable:
            return "该工具已被管理员关闭（llm_tools_enable 未开启）"
        return None

    async def _llm_fetch_pixiv(
        self, event: AstrMessageEvent, params: Dict[str, Any]
    ) -> str:
        """图片工具共用流程：构建参数 → 请求 API → 发送图片 → 返回说明。"""
        if not self._api_client:
            return "图片功能未配置（缺少 Pixiv API Key）"
        try:
            api_params = self._prepare_api_params(params)
            result = await self._api_client.fetch_images(**api_params)
            items = await self._process_response(result, params, event)
            if not items:
                return "未获取到图片"
            sent = 0
            for item in items:
                try:
                    await event.send(item)
                    if isinstance(item, MessageEventResult) or hasattr(item, "chain"):
                        sent += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[LLMTool] 发送图片段失败: {e}")
            num = params.get("num", 1)
            return f"已{'发送图片' if sent else '尝试发送'}（请求 {num} 张）"
        except PixivAPIError as e:
            return f"获取图片失败：{e}"
        except Exception as e:  # noqa: BLE001
            logger.error(f"[LLMTool] 图片工具异常: {e}", exc_info=True)
            return f"获取图片时出错：{e}"

    @filter.llm_tool(name="get_pixiv_random")
    async def llm_tool_pixiv_random(
        self, event: AstrMessageEvent, num: int = 1, r18: int = -1
    ):
        """获取随机二次元插画图片并发送。当用户想看图、来张图、发个插画时调用。

        Args:
            num(number): 获取的图片数量，1-5，默认 1。不要超过 5 以免刷屏。
            r18(number): 内容等级。0=全年龄（默认），1=仅 R18，2=混合。不确定时用 0。
        """
        hint = self._llm_tool_guard()
        if hint:
            return hint
        n = max(1, min(5, int(num)))
        level = self._default_r18 if r18 < 0 else int(r18)
        params = {
            "r18": level, "num": n,
            "size": self._default_size, "excludeAI": self._exclude_ai,
        }
        return await self._llm_fetch_pixiv(event, params)

    @filter.llm_tool(name="search_pixiv")
    async def llm_tool_pixiv_search(
        self, event: AstrMessageEvent, keyword: str, num: int = 1, r18: int = -1
    ):
        """按关键词搜索二次元插画图片并发送。当用户指定了主题/内容时调用，如「来张猫娘」「找点原神图」。

        Args:
            keyword(string): 搜索关键词，如「猫娘」「原神」「星空」。
            num(number): 获取的图片数量，1-5，默认 1。
            r18(number): 内容等级。0=全年龄（默认），1=仅 R18，2=混合。不确定时用 0。
        """
        hint = self._llm_tool_guard()
        if hint:
            return hint
        if not keyword or not keyword.strip():
            return "请提供搜索关键词"
        n = max(1, min(5, int(num)))
        level = self._default_r18 if r18 < 0 else int(r18)
        params = {
            "r18": level, "num": n, "keyword": keyword.strip(),
            "size": self._default_size, "excludeAI": self._exclude_ai,
        }
        return await self._llm_fetch_pixiv(event, params)

    @filter.llm_tool(name="get_pixiv_by_tags")
    async def llm_tool_pixiv_tags(
        self, event: AstrMessageEvent, tags: str, num: int = 1, r18: int = -1
    ):
        """按标签（多标签 AND 匹配）获取二次元插画图片并发送。适合用户给出多个标签的精确筛选，如「银发 红瞳」。

        Args:
            tags(string): 标签列表，逗号分隔，如「银发,红瞳」「catgirl,kimono」。多标签为同时满足（AND）。
            num(number): 获取的图片数量，1-5，默认 1。
            r18(number): 内容等级。0=全年龄（默认），1=仅 R18，2=混合。不确定时用 0。
        """
        hint = self._llm_tool_guard()
        if hint:
            return hint
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        if not tag_list:
            return "请提供至少一个标签"
        n = max(1, min(5, int(num)))
        level = self._default_r18 if r18 < 0 else int(r18)
        params = {
            "r18": level, "num": n, "tag": tag_list,
            "size": self._default_size, "excludeAI": self._exclude_ai,
        }
        return await self._llm_fetch_pixiv(event, params)

    @filter.llm_tool(name="get_femboy_image")
    async def llm_tool_femboy(self, event: AstrMessageEvent):
        """获取一张随机男娘（femboy）图片并发送。当用户要求看男娘、伪娘、femboy 图片时调用。

        Args:
        """
        hint = self._llm_tool_guard()
        if hint:
            return hint
        if not self._femboy_client:
            return "男娘图片功能未配置（缺少 femboy API Key）"
        try:
            result = await self._femboy_client.fetch_femboy_image()
            items = await self._process_femboy_response(result, event)
            if not items:
                return "未获取到男娘图片"
            for item in items:
                try:
                    await event.send(item)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[LLMTool] 发送男娘图片段失败: {e}")
            return "已发送一张男娘图片"
        except FemboyAPIError as e:
            return f"获取男娘图片失败：{e}"
        except Exception as e:  # noqa: BLE001
            logger.error(f"[LLMTool] 男娘工具异常: {e}", exc_info=True)
            return f"获取男娘图片时出错：{e}"

    @filter.llm_tool(name="play_song")
    async def llm_tool_play_song(self, event: AstrMessageEvent, song_name: str):
        """根据歌曲名搜索并点歌，发送语音条。当用户想听歌、来一首、播放音乐时调用。

        Args:
            song_name(string): 歌曲名称，可包含歌手名，如「晴天」「周杰伦 晴天」。
        """
        hint = self._llm_tool_guard()
        if hint:
            return hint
        if not self._netease_client and not self._kugou_client:
            return "音乐功能未配置（缺少网易云或酷狗 API Key）"
        query = (song_name or "").strip()
        if not query:
            return "请提供歌曲名"
        slot_hint = self._acquire_music_slot(event)
        if slot_hint:
            return slot_hint
        try:
            song_data, used_source = await self._search_and_get("auto", query)
            items = await self._format_song_response(
                song_data, event, direct_mode=True
            )
            for item in items:
                try:
                    await event.send(item)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[LLMTool] 发送音乐段失败: {e}")
            src_name = {"netease": "网易云", "kugou": "酷狗"}.get(used_source, used_source)
            name = song_data.get("name", query) if isinstance(song_data, dict) else query
            return f"已点播「{name}」（音源：{src_name}）"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[LLMTool] 点歌失败: {e}")
            return f"点歌失败：{e}"
        finally:
            self._release_music_slot(event)

    async def _llm_dglab_dispatch(
        self, event: AstrMessageEvent, command: str, args: str
    ) -> str:
        """电击工具共用流程：拼接 args → 复用 _dispatch_command（含权限校验/设备解析）。"""
        hint = self._llm_tool_guard()
        if hint:
            return hint
        try:
            # 确保连接池/WebUI 已启动（与 dglab_command 一致）
            if not getattr(self, "_pool_started", False):
                await self._connection_pool.start()
                if self._dglab_webui:
                    await self._dglab_webui.start()
                self._pool_started = True
            user_id = str(event.get_sender_id())
            user_name = event.get_sender_name()
            result = await self._dglab_handler._dispatch_command(
                command, args, user_id, user_name, event
            )
            if isinstance(result, list):
                # _cmd_bind 会返回 [文本, 图片]；逐项发送
                for item in result:
                    try:
                        await event.send(item)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"[LLMTool] 发送 dglab 结果段失败: {e}")
                return "已发送设备绑定二维码及相关信息"
            return str(result) if result is not None else "操作完成"
        except Exception as e:  # noqa: BLE001
            logger.error(f"[LLMTool] 电击工具异常: {e}", exc_info=True)
            return f"操作失败：{e}"

    @filter.llm_tool(name="dglab_shock")
    async def llm_tool_dglab_shock(
        self, event: AstrMessageEvent, channel: str,
        strength: int = 20, wave: str = "pulse",
        duration: int = 5, device_index: int = 0,
    ):
        """对 DG-LAB 电击设备开始电击（发送指定强度的波形输出）。仅在用户明确要求电击/开火/放电时调用。

        Args:
            channel(string): 通道，A 或 B。
            strength(number): 强度值，0-200，默认 20。请从低值开始。
            wave(string): 波形预设名，默认 pulse。可选：breathe/pulse/wave/tap/heartbeat/needle/throb/chaos。
            duration(number): 持续秒数，默认 5。
            device_index(number): 设备序号，单设备可省略（默认）；多设备时指定，如 2。
        """
        ch = (channel or "A").strip().upper()
        parts = []
        if device_index and int(device_index) > 0:
            parts.append(str(int(device_index)))
        parts.append(ch)
        parts.append(str(max(0, min(200, int(strength)))))
        parts.append((wave or "pulse").strip().lower())
        parts.append(str(max(1, int(duration))))
        return await self._llm_dglab_dispatch(event, "shock", " ".join(parts))

    @filter.llm_tool(name="dglab_strength")
    async def llm_tool_dglab_strength(
        self, event: AstrMessageEvent, channel: str, value: int, device_index: int = 0
    ):
        """设置 DG-LAB 电击设备的通道强度（绝对值）。当用户说「强度调到X」「设为X」时调用。

        Args:
            channel(string): 通道，A 或 B。
            value(number): 目标强度值，0-200。
            device_index(number): 设备序号，单设备可省略；多设备时指定。
        """
        ch = (channel or "A").strip().upper()
        parts = []
        if device_index and int(device_index) > 0:
            parts.append(str(int(device_index)))
        parts.append(ch)
        parts.append(str(max(0, min(200, int(value)))))
        return await self._llm_dglab_dispatch(event, "strength", " ".join(parts))

    @filter.llm_tool(name="dglab_strength_adjust")
    async def llm_tool_dglab_strength_adjust(
        self, event: AstrMessageEvent, channel: str, direction: str,
        step: int = 5, device_index: int = 0,
    ):
        """增加或减少 DG-LAB 通道强度（相对调节）。当用户说「调大一点」「降低一些」时调用。

        Args:
            channel(string): 通道，A 或 B。
            direction(string): 调节方向，up=增加 / down=减少。
            step(number): 步进值，默认 5。
            device_index(number): 设备序号，单设备可省略；多设备时指定。
        """
        ch = (channel or "A").strip().upper()
        cmd = "up" if (direction or "up").strip().lower().startswith("u") else "down"
        parts = []
        if device_index and int(device_index) > 0:
            parts.append(str(int(device_index)))
        parts.append(ch)
        parts.append(str(max(1, int(step))))
        return await self._llm_dglab_dispatch(event, cmd, " ".join(parts))

    @filter.llm_tool(name="dglab_pulse")
    async def llm_tool_dglab_pulse(
        self, event: AstrMessageEvent, channel: str, wave: str,
        duration: int = 5, device_index: int = 0,
    ):
        """对 DG-LAB 通道发送波形（不改变强度，仅输出波形图案）。当用户要求特定波形/模式时调用。

        Args:
            channel(string): 通道，A 或 B。
            wave(string): 波形预设名：breathe/pulse/wave/tap/heartbeat/needle/throb/chaos。
            duration(number): 持续秒数，默认 5。
            device_index(number): 设备序号，单设备可省略；多设备时指定。
        """
        ch = (channel or "A").strip().upper()
        parts = []
        if device_index and int(device_index) > 0:
            parts.append(str(int(device_index)))
        parts.append(ch)
        parts.append((wave or "pulse").strip().lower())
        parts.append(str(max(1, int(duration))))
        return await self._llm_dglab_dispatch(event, "pulse", " ".join(parts))

    @filter.llm_tool(name="dglab_stop")
    async def llm_tool_dglab_stop(
        self, event: AstrMessageEvent, channel: str = "", device_index: int = 0
    ):
        """停止 DG-LAB 电击设备的输出。当用户要求停止/停下/关掉电击时调用。不指定通道则停止该设备全部输出。

        Args:
            channel(string): 通道，A 或 B。留空则停止该设备所有通道。
            device_index(number): 设备序号，单设备可省略；多设备时指定。
        """
        parts = []
        if device_index and int(device_index) > 0:
            parts.append(str(int(device_index)))
        ch = (channel or "").strip().upper()
        if ch in ("A", "B"):
            parts.append(ch)
        return await self._llm_dglab_dispatch(event, "stop", " ".join(parts))

    @filter.llm_tool(name="dglab_status")
    async def llm_tool_dglab_status(self, event: AstrMessageEvent):
        """查询 DG-LAB 电击设备的绑定与连接状态。当用户想了解设备情况、是否连接、当前状态时调用。

        Args:
        """
        return await self._llm_dglab_dispatch(event, "status", "")

    @filter.on_decorating_result()
    async def on_reply_seg_decorating(self, event: AstrMessageEvent):
        """分段回复：在发送前把回复文本拆成多条消息分次发送（模拟逐条回复）。

        通过 on_decorating_result 钩子介入（LLM 文本已确定、框架自带分段/发送之前）。
        处理流程：提取 Plain 文本 → 分段 → 清空框架结果 → 逐段 event.send + 延时 →
        手动写回对话历史（因为绕过了框架发送，assistant 回合需自行记录）。
        """
        if not self._reply_seg_enable:
            return
        try:
            result = event.get_result()
            if not result or not result.chain:
                return
            # 仅对 LLM 结果分段（命令结果跳过）
            if self._reply_seg_only_llm and not result.is_model_result():
                return
            raw_text = "".join(
                comp.text for comp in result.chain if isinstance(comp, Comp.Plain)
            ).strip()
            if not raw_text:
                return

            # llm 模式：先尝试大模型语义分段；太短、失败或只切出 1 段则降级规则分段。
            segments: Optional[List[str]] = None
            if self._reply_seg_mode == "llm":
                segments = await self._segment_by_llm(raw_text, event)
            if not segments:
                segments = self._segment_text(raw_text)
            if len(segments) <= 1:
                return  # 无需分段，交回框架正常发送

            full_text = "\n\n".join(segments)
            result.chain.clear()  # 阻止框架再发一次原文

            lo, hi = self._reply_seg_delay_range
            for i, seg in enumerate(segments):
                if i > 0:
                    await asyncio.sleep(random.uniform(lo, hi))
                await event.send(MessageChain().message(seg))

            # 绕过框架发送后，需手动写回对话历史
            await self._save_seg_history(event, full_text)
            logger.info(f"[ReplySeg] 分段回复完成，共 {len(segments)} 段")
        except Exception as e:
            logger.error(f"[ReplySeg] 分段异常，已跳过（回复原文）: {e}")

    # llm 模式：分段密度档位映射。每档定义「每段目标字数区间」+「默认段数上限」
    # +「prompt 引导语」。low=每段长(信息密度大)、medium=适中、high=每段短(更碎更活泼)。
    _REPLY_SEG_DENSITY_PROFILES = {
        "low": {
            "label": "低（每段较长）",
            "target_chars": (40, 70),
            "max_segments": 3,
            "guidance": "每段尽量长一些、信息量大一些，把相关内容合并成较完整的大段，少切几段。",
        },
        "medium": {
            "label": "中（适中，推荐）",
            "target_chars": (20, 45),
            "max_segments": 5,
            "guidance": "每段保持适中长度，像真人自然的逐句节奏。",
        },
        "high": {
            "label": "高（每段较短）",
            "target_chars": (10, 25),
            "max_segments": 8,
            "guidance": "每段尽量短小精悍，可以切得更细、更活泼，像刷屏式聊天。",
        },
    }

    # llm 模式：语义级分段的系统提示词模板。要求返回纯 JSON 字符串数组。
    # {max_segments}/{target_min}/{target_max}/{density_guidance} 由 _segment_by_llm 注入。
    # 精简提示词以减少输入 token、加速推理；核心约束保留，措辞压缩。
    _REPLY_SEG_LLM_SYSTEM_PROMPT = (
        "把输入文本按语义完整性拆成 2~{max_segments} 条逐条发送的消息。"
        "{density_guidance}每段约{target_min}~{target_max}字。\n"
        "要求：只在语义停顿处断开；逗号是句内停顿不要切；"
        "颜文字跟在所属句尾；原文一字不改，只切不增删。"
        "短文无法拆分时返回单段。\n"
        "只输出JSON字符串数组，无任何解释或markdown。"
        '示例：["第一段","第二段"]'
    )

    async def _segment_by_llm(
        self, text: str, event: AstrMessageEvent
    ) -> Optional[List[str]]:
        """调用大模型做语义级分段，返回段落列表；不可用/失败/校验不通过时返回 None。

        失败情形（均返回 None，由调用方降级到规则分段）：
        - 原文长度 < _reply_seg_llm_min_chars（太短不值得调用）
        - 无可用 provider（未配置且取不到当前会话模型）
        - 调用异常或超时
        - 返回内容不是合法 JSON 数组 / 解析后非字符串元素
        - 合并后总字数与原文偏差过大（>10%，判定模型改写了原文）
        """
        if len(text) < self._reply_seg_llm_min_chars:
            return None

        provider_id = self._reply_seg_llm_provider_id
        if not provider_id:
            try:
                provider_id = await self.context.get_current_chat_provider_id(
                    umo=event.unified_msg_origin
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[ReplySeg] 获取当前 provider 失败: {e}")
                provider_id = ""
        if not provider_id:
            logger.warning("[ReplySeg] llm 模式无可用 provider，降级规则分段")
            return None

        profile = self._REPLY_SEG_DENSITY_PROFILES[self._reply_seg_llm_density]
        tmin, tmax = profile["target_chars"]
        system_prompt = self._REPLY_SEG_LLM_SYSTEM_PROMPT.format(
            max_segments=self._reply_seg_llm_max_segments,
            target_min=tmin,
            target_max=tmax,
            density_guidance=profile["guidance"],
        )
        # 性能优化：限制输出 token + 只请求一次（失败即降级）+ 超时控制。
        # 分段结果是一个短 JSON 数组，不需要长输出，限制 max_tokens 能显著加速返回。
        try:
            resp: Optional[LLMResponse] = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    system_prompt=system_prompt,
                    prompt=text,
                    max_tokens=self._reply_seg_llm_max_tokens,
                    request_max_retries=1,
                ),
                timeout=self._reply_seg_llm_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"[ReplySeg] llm 分段超时（>{self._reply_seg_llm_timeout}s），降级规则分段"
            )
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ReplySeg] llm 分段调用异常，降级规则分段: {e}")
            return None
        if not resp or not resp.completion_text:
            logger.warning("[ReplySeg] llm 分段返回空，降级规则分段")
            return None

        segments = self._parse_llm_segments(resp.completion_text)
        if not segments:
            logger.warning("[ReplySeg] llm 分段结果解析失败，降级规则分段")
            return None

        # 段数超限：把超出部分合并到最后一段，避免模型切成几十段。
        segments = self._cap_llm_segments(segments, self._reply_seg_llm_max_segments)

        # 字数校验：合并后应约等于原文；偏差过大说明模型改写了内容，不可信。
        joined = "".join(segments)
        if not self._text_close_enough(joined, text):
            logger.warning(
                f"[ReplySeg] llm 分段合并后字数({len(joined)})与原文({len(text)})"
                f"偏差过大，降级规则分段"
            )
            return None
        return segments

    @staticmethod
    def _parse_llm_segments(raw: str) -> List[str]:
        """从 LLM 返回文本中解析出字符串列表。

        容错：去掉 markdown 代码块围栏（```json ... ```）、首尾多余空白；
        尝试截取首个 [ 到末尾 ] 的片段再解析；最终只保留非空字符串元素。
        """
        if not raw:
            return []
        text = raw.strip()
        # 去掉 markdown 代码块围栏
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        # 直接解析
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # 截取首个 [ 到最后一个 ] 之间再试一次
            start = text.find("[")
            end = text.rfind("]")
            if start == -1 or end == -1 or end <= start:
                return []
            try:
                data = json.loads(text[start: end + 1])
            except (json.JSONDecodeError, ValueError):
                return []
        if not isinstance(data, list):
            return []
        segments: List[str] = []
        for item in data:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    segments.append(s)
        return segments

    @staticmethod
    def _cap_llm_segments(segments: List[str], max_segments: int) -> List[str]:
        """段数超过上限时，把多出的段落合并到末段，返回裁剪后的列表。"""
        if max_segments <= 1 or len(segments) <= max_segments:
            return segments
        head = segments[:max_segments - 1]
        tail = "".join(segments[max_segments - 1:])
        head.append(tail)
        return head

    @staticmethod
    def _text_close_enough(a: str, b: str) -> bool:
        """判断两个文本字数是否足够接近（去除空白后比较，允许 10% 偏差）。"""
        ca = len(re.sub(r"\s", "", a))
        cb = len(re.sub(r"\s", "", b))
        if cb == 0:
            return ca == 0
        # 偏差比例 = |差| / max(原文, 合并)
        diff_ratio = abs(ca - cb) / max(cb, ca)
        return diff_ratio <= 0.10

    def _segment_text(self, text: str) -> List[str]:
        """按 reply_seg_mode 分派到对应分段算法，返回非空段落列表。"""
        symbols = self._reply_seg_symbols or "。！？!?~～…\n,，"
        words = self._reply_seg_words
        if self._reply_seg_mode == "length":
            return self._split_by_length(
                text, self._reply_seg_min_length, self._reply_seg_max_length,
                symbols, words,
            )
        return self._split_by_punct(
            text, symbols, words, self._reply_seg_merge_threshold,
        )

    @staticmethod
    def _build_sep_pattern(symbols: str, words: List[str]) -> Optional[re.Pattern]:
        """构建分隔符正则：单字符符号（成组 [..]+） + 多字符词（按长度降序的交替）。

        词排在前面以优先匹配更长的词（如 owo 不被 o 截断）；返回一个捕获组，
        供 re.split 在分隔符处断开并保留分隔符。
        """
        # 多字符词按长度降序，避免短词先匹配；单字符词并入字符类
        multi = sorted((w for w in words if len(w) > 1), key=len, reverse=True)
        single_words = [w for w in words if len(w) == 1]
        # 单字符：合并符号与单字符词到一个字符类
        single_chars = symbols + "".join(single_words)
        alts: List[str] = []
        if multi:
            alts.append("|".join(re.escape(w) for w in multi))
        if single_chars:
            alts.append("[" + re.escape(single_chars) + "]+")
        if not alts:
            return None
        return re.compile("(" + "|".join(alts) + ")")

    def _split_by_punct(self, text: str, symbols: str, words: List[str],
                        merge_threshold: int = 4) -> List[str]:
        """按标点/词切分：在任一切分点处断开，分隔符保留在段尾；丢弃空段。

        支持单字符符号（。！？, 等）和多字符词（喵 qwq owo 等）。切完后调用
        _merge_short_segments 把过短段和纯标点段（如孤立的「。」）并回前一段，
        消除逗号切出的碎片和孤立标点段；有效短句（如「好的。」）作为首段不受影响。
        merge_threshold <= 0 时关闭合并。
        """
        if not text:
            return []
        pattern = self._build_sep_pattern(symbols, words)
        if pattern is None:
            return [text.strip()] if text.strip() else []
        parts = pattern.split(text)
        # re.split 带捕获组会交替返回 [非分隔, 分隔, 非分隔, 分隔, ...]
        segments: List[str] = []
        i = 0
        while i < len(parts):
            chunk = parts[i]
            sep = parts[i + 1] if i + 1 < len(parts) else ""
            piece = (chunk + sep).strip()
            if piece:
                segments.append(piece)
            i += 2
        if merge_threshold > 0:
            segments = self._merge_short_segments(segments, merge_threshold)
        return segments

    @staticmethod
    def _merge_short_segments(segments: List[str], threshold: int) -> List[str]:
        """把过短段和纯标点段并回前一段，消除碎片。

        - 纯标点段（全部由常见标点/空白组成，如孤立的「。」或「，」）无条件合并；
        - 长度 < threshold 的段也合并；
        - 仅当存在前一段时才合并（首段直接保留，避免丢内容）。
        """
        if len(segments) <= 1:
            return segments
        punct_chars = set("。！？!?~～…\n,，、；;：: 　\t")
        merged: List[str] = []
        for seg in segments:
            is_punct_only = all(c in punct_chars for c in seg)
            if merged and (is_punct_only or len(seg) < threshold):
                merged[-1] += seg
            else:
                merged.append(seg)
        return merged

    @staticmethod
    def _find_cut_after(remaining: str, start: int, end: int, symbols: str,
                        words: List[str]) -> int:
        """在 remaining 的 [start, end) 范围内，找到最靠后的「切分点之后」位置。

        切分点 = 单字符符号，或多字符词的结尾。返回切分后剩余的起始索引
        （即分隔符之后的位置）；找不到返回 -1。
        """
        symset = set(symbols)
        best = -1
        # 单字符符号：在范围内扫描
        hi = min(end, len(remaining))
        for idx in range(start, hi):
            if remaining[idx] in symset:
                best = idx + 1  # 含该符号
        # 多字符词：在范围内找每个词的出现，取词结尾之后的位置
        for w in words:
            if len(w) <= 1:
                continue
            wl = len(w)
            search_from = start
            while True:
                pos = remaining.find(w, search_from, hi)
                if pos == -1:
                    break
                after = pos + wl
                if after <= hi and after > best:
                    best = after
                search_from = pos + 1
        return best

    def _split_by_length(self, text: str, min_len: int, max_len: int,
                         symbols: str, words: List[str]) -> List[str]:
        """按长度切分：段短于 max_len 直接收；超长则在 [min_len, max_len] 范围反向找
        切分点（标点或词），找不到则前向找；再找不到才硬切 max_len。末尾过短合并。"""
        segments: List[str] = []
        remaining = text.strip()
        while remaining:
            if len(remaining) <= max_len:
                segments.append(remaining.strip())
                break
            cut = -1
            # 1) 在 [min_len, max_len] 范围反向找切分点（_find_cut_after 已取最靠后）
            cut = self._find_cut_after(remaining, min_len, max_len, symbols, words)
            # 2) 前向找（允许略超 max_len，最多到 max_len 的 2 倍内）
            if cut == -1:
                cut = self._find_cut_after(
                    remaining, max_len, min(len(remaining), max_len * 2),
                    symbols, words,
                )
            # 3) 硬切
            if cut == -1:
                cut = max_len
            seg = remaining[:cut].strip()
            if seg:
                segments.append(seg)
            remaining = remaining[cut:].strip()
        # 合并过短末尾
        if len(segments) >= 2 and len(segments[-1]) < 6:
            tail = segments.pop()
            segments[-1] += tail
        return segments

    async def _save_seg_history(self, event: AstrMessageEvent, content: str) -> None:
        """将分段合并后的完整回复写入对话历史（绕过框架发送后的必要补偿）。

        复刻自 astrbot_plugin_custome_segment_reply 的同名方法：取当前会话历史，
        确保末尾是 user 回合后追加 assistant 回合，再 update_conversation。
        """
        try:
            conv_mgr = self.context.conversation_manager
            if not conv_mgr:
                return
            umo = event.unified_msg_origin
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            if not curr_cid:
                return
            conversation = await conv_mgr.get_conversation(umo, curr_cid)
            if not conversation:
                return
            import json as _json

            try:
                history = (
                    _json.loads(conversation.history)
                    if isinstance(conversation.history, str)
                    else conversation.history
                )
            except (ValueError, TypeError):
                history = []
            user_content = event.message_str
            if user_content and (not history or history[-1].get("role") != "user"):
                history.append({"role": "user", "content": user_content})
            history.append({"role": "assistant", "content": content})
            await conv_mgr.update_conversation(
                unified_msg_origin=umo,
                conversation_id=curr_cid,
                history=history,
            )
        except Exception as e:
            logger.error(f"[ReplySeg] 保存对话历史失败: {e}")

    @filter.command("hitokoto", alias={"一言"})
    async def hitokoto_command(self, event: AstrMessageEvent):
        """获取随机每日一言，可按分类筛选。"""
        user_name = event.get_sender_name()
        message_str = event.message_str.strip()

        logger.debug(f"[Hitokoto] 收到消息: '{message_str}' from {user_name}")

        if self._is_help_command(message_str):
            logger.info(f"[Hitokoto] Help command triggered by {user_name}")
            yield event.plain_result(HITOKOTO_HELP_TEXT)
            return

        if not self._hitokoto_client:
            logger.warning(
                f"[Hitokoto] API client not initialized for user {user_name}"
            )
            yield event.plain_result(_format_api_key_not_configured("每日一言"))
            return

        try:
            category = self._parse_hitokoto_params(message_str)
            logger.info(
                f"[Hitokoto] Fetching for user {user_name}, category={category}"
            )

            result = await self._hitokoto_client.fetch_hitokoto(category=category)

            response_text = self._format_hitokoto_response(result)
            logger.info(f"[Hitokoto] Successfully fetched hitokoto for {user_name}")
            yield event.plain_result(response_text)

        except HitokotoAPIError as e:
            logger.error(f"[Hitokoto] API error for user {user_name}: {e}")
            error_msg = f"❌ 获取一言失败\n📝 错误信息：{str(e)}"
            if e.status_code:
                error_msg += f"\n🔢 状态码：{e.status_code}"
            error_msg += "\n💡 请稍后重试或发送 /hitokoto help 查看帮助"
            yield event.plain_result(error_msg)
        except Exception as e:
            logger.error(
                f"[Hitokoto] Unexpected error for user {user_name}: {e}", exc_info=True
            )
            yield event.plain_result(
                f"❌ 发生未知错误\n📝 错误信息：{str(e)}\n💡 请稍后重试"
            )

    def _parse_hitokoto_params(self, message: str) -> Optional[str]:
        cleaned = re.sub(
            r"^[/!！]\s*(hitokoto|一言)\s*", "", message.strip(), flags=re.IGNORECASE
        )
        cleaned = re.sub(
            r"^(hitokoto|一言)\s*", "", cleaned.strip(), flags=re.IGNORECASE
        )
        cleaned = cleaned.strip()

        if not cleaned or cleaned.lower() in ("help", "-h", "--help", "帮助"):
            return None

        category = cleaned.lower()
        if category in HITOKOTO_CATEGORIES:
            return category
        return None

    def _format_hitokoto_response(self, result: Dict[str, Any]) -> str:
        text = result.get("text", "")
        source = result.get("from", "未知来源")
        category = result.get("category_name", "未知")

        response_parts = [
            f"✨ 每日一言",
            f"",
            f"「{text}」",
            f"",
            f"—— {source}",
            f"📂 分类：{category}",
        ]

        return "\n".join(response_parts)

    @filter.command("weather", alias={"天气"})
    async def weather_command(self, event: AstrMessageEvent):
        """查询指定城市的实时天气信息。"""
        user_name = event.get_sender_name()
        message_str = event.message_str.strip()

        logger.debug(f"[Weather] 收到消息: '{message_str}' from {user_name}")

        if self._is_help_command(message_str):
            logger.info(f"[Weather] Help command triggered by {user_name}")
            yield event.plain_result(WEATHER_HELP_TEXT)
            return

        if not self._weather_client:
            logger.warning(f"[Weather] API client not initialized for user {user_name}")
            yield event.plain_result(_format_api_key_not_configured("天气查询"))
            return

        try:
            city = self._parse_weather_params(message_str)
            if not city:
                logger.warning(f"[Weather] No city specified by user {user_name}")
                yield event.plain_result(
                    "❌ 请指定城市名称\n💡 用法：/weather 广州市\n💡 发送 /weather help 查看帮助"
                )
                return

            if len(city) > 50:
                logger.warning(
                    f"[Weather] City name too long ({len(city)} chars) from user {user_name}"
                )
                yield event.plain_result(
                    "❌ 城市名称过长（最多50个字符）\n💡 请输入正确的城市名称"
                )
                return

            logger.info(f"[Weather] Fetching weather for user {user_name}, city={city}")

            result = await self._weather_client.fetch_weather(city)

            logger.debug(
                f"[Weather] API response received for {city}, type={result.get('type')}"
            )

            response_text = self._format_weather_response(result)
            logger.info(
                f"[Weather] Successfully formatted weather response for {user_name}, city={city}"
            )
            yield event.plain_result(response_text)

        except WeatherAPIError as e:
            logger.error(
                f"[Weather] API error for user {user_name}: {e} (status_code={e.status_code})"
            )
            error_msg = f"❌ 查询天气失败\n📝 错误信息：{str(e)}"
            if e.status_code:
                error_msg += f"\n🔢 状态码：{e.status_code}"
            error_msg += "\n💡 请稍后重试或检查城市名称是否正确"
            error_msg += "\n💡 支持的城市示例：广州市、北京市、上海市"
            yield event.plain_result(error_msg)
        except ValueError as e:
            logger.error(
                f"[Weather] Parameter validation error for user {user_name}: {e}"
            )
            yield event.plain_result(
                f"❌ 参数错误：{str(e)}\n💡 用法：/weather 城市名称"
            )
        except Exception as e:
            logger.error(
                f"[Weather] Unexpected error for user {user_name}: {e}", exc_info=True
            )
            yield event.plain_result(
                f"❌ 发生未知错误\n📝 错误信息：{str(e)}\n💡 请稍后重试或联系管理员"
            )

    def _parse_weather_params(self, message: str) -> Optional[str]:
        cleaned = re.sub(
            r"^[/!！]\s*(weather|天气)\s*", "", message.strip(), flags=re.IGNORECASE
        )
        cleaned = re.sub(
            r"^(weather|天气)\s*", "", cleaned.strip(), flags=re.IGNORECASE
        )
        cleaned = cleaned.strip()

        if not cleaned or cleaned.lower() in ("help", "-h", "--help", "帮助"):
            return None

        return cleaned if cleaned else None

    def _format_weather_response(self, result: Dict[str, Any]) -> str:
        response_type = result.get("type", "text")

        if response_type == "text":
            text_data = result.get("data", "")
            return f"🌤️ 天气查询\n\n{text_data}"

        data = result.get("data", {})
        city = result.get("city", "未知城市")

        if not isinstance(data, dict):
            logger.warning(f"[Weather] Invalid data format in response: {type(data)}")
            return f"🌤️ {city} 天气信息\n\n⚠️ 数据格式异常"

        response_parts = [f"🌤️ {city} 天气预报"]

        adm = data.get("adm", "")
        if adm:
            response_parts.append(f"📍 {adm}")

        now = data.get("now")
        if isinstance(now, dict) and now:
            response_parts.append("\n☀️ 当前天气")
            temp = now.get("temp", "")
            weather = now.get("weather", "")
            wind_dir = now.get("windDir", "")
            wind_scale = now.get("windScale", "")
            humidity = now.get("humidity", "")
            feels_like = now.get("feelsLike", "")

            if temp:
                response_parts.append(f"🌡️ 温度：{temp}")
            if weather:
                response_parts.append(f"☁️ 天气：{weather}")
            if feels_like:
                response_parts.append(f"🤒 体感温度：{feels_like}")
            if wind_dir and wind_scale:
                response_parts.append(f"💨 风力：{wind_dir} {wind_scale}级")
            elif wind_dir:
                response_parts.append(f"💨 风向：{wind_dir}")
            if humidity:
                response_parts.append(f"💧 湿度：{humidity}%")

        forecast_list = data.get("forecast")
        if isinstance(forecast_list, list) and forecast_list:
            response_parts.append("\n📅 未来天气预报")
            for i, forecast in enumerate(forecast_list[:3], 1):
                if not isinstance(forecast, dict):
                    continue

                date = forecast.get("date", "")
                weekday = forecast.get("weekday", "")
                weather = forecast.get("weather", "")
                temp_min = forecast.get("tempMin", "")
                temp_max = forecast.get("tempMax", "")
                wind_dir = forecast.get("windDir", "")
                wind_scale = forecast.get("windScale", "")
                humidity_f = forecast.get("humidity", "")

                day_label = f"\n📆 第{i}天"
                if date and weekday:
                    day_label += f"：{date}（{weekday}）"
                elif date:
                    day_label += f"：{date}"

                response_parts.append(day_label)

                if weather:
                    response_parts.append(f"   ☁️ 天气：{weather}")
                if temp_min or temp_max:
                    temp_str = (
                        f"{temp_min}~{temp_max}"
                        if temp_min and temp_max
                        else (temp_max or temp_min)
                    )
                    response_parts.append(f"   🌡️ 温度：{temp_str}")
                if wind_dir and wind_scale:
                    response_parts.append(f"   💨 风力：{wind_dir} {wind_scale}级")
                elif wind_dir:
                    response_parts.append(f"   � 风向：{wind_dir}")
                if humidity_f:
                    response_parts.append(f"   💧 湿度：{humidity_f}%")

        final_response = "\n".join([p for p in response_parts if p])

        if len(final_response.strip()) <= len(f"🌤️ {city} 天气预报"):
            logger.warning(
                f"[Weather] Response appears empty after formatting. Raw data keys: {list(data.keys())}"
            )
            raw_data = result.get("raw_response", {})
            return f"🌤️ {city} 天气信息\n\n⚠️ 未能解析天气数据\n原始数据：{str(raw_data)[:200]}"

        logger.info(
            f"[Weather] Formatted response with {len(response_parts)} parts for city: {city}"
        )
        return final_response

    @filter.command("femboy", alias={"男娘"})
    async def femboy_command(self, event: AstrMessageEvent):
        """获取一张随机男娘图片。"""
        user_name = event.get_sender_name()
        message_str = event.message_str.strip()

        logger.debug(f"[Femboy] 收到消息: '{message_str}' from {user_name}")

        if self._is_help_command(message_str):
            logger.info(f"[Femboy] Help command triggered by {user_name}")
            yield event.plain_result(FEMBOY_HELP_TEXT)
            return

        if not self._femboy_client:
            logger.warning(f"[Femboy] API client not initialized for user {user_name}")
            yield event.plain_result(_format_api_key_not_configured("男娘图片"))
            return

        try:
            logger.info(f"[Femboy] Fetching image for user {user_name}")

            result = await self._femboy_client.fetch_femboy_image()

            response_items = await self._process_femboy_response(result, event)
            for item in response_items:
                yield item

        except FemboyAPIError as e:
            logger.error(f"[Femboy] API error for user {user_name}: {e}")
            error_msg = f"❌ 获取男娘图片失败\n📝 错误信息：{str(e)}"
            if e.status_code:
                error_msg += f"\n🔢 状态码：{e.status_code}"
            error_msg += "\n💡 请稍后重试或发送 /femboy help 查看帮助"
            yield event.plain_result(error_msg)
        except Exception as e:
            logger.error(
                f"[Femboy] Unexpected error for user {user_name}: {e}", exc_info=True
            )
            yield event.plain_result(
                f"❌ 发生未知错误\n📝 错误信息：{str(e)}\n💡 请稍后重试"
            )

    async def _process_femboy_response(
        self, result: Dict[str, Any], event: AstrMessageEvent
    ) -> List[Any]:
        response_type = result.get("type")

        if response_type == "redirect":
            url = result.get("url", "")
            caption = "👗 随机男娘图片"
            return [
                event.chain_result([Comp.Plain(text=caption), Comp.Image(file=url)])
            ]

        if response_type == "json":
            data = result.get("data", {})
            image_url = data.get("url", "")
            source = data.get("from", "未知来源")
            note = data.get("note", "")

            if not image_url:
                return [event.plain_result("⚠️ 未能获取到图片链接\n💡 请稍后重试")]

            response_parts = ["👗 随机男娘图片"]
            if source and source != "未知来源":
                response_parts.append(f"📸 来源：{source}")
            if note:
                response_parts.append(f"📝 备注：{note}")

            caption = "\n".join(response_parts)
            return [
                event.chain_result(
                    [Comp.Plain(text=caption), Comp.Image(file=image_url)]
                )
            ]

        logger.warning(f"[Femboy] Unknown response type: {response_type}")
        return [event.plain_result("⚠️ API 返回了未知格式的数据，请联系管理员")]

    @filter.command("music", alias={"音乐"})
    async def music_command(self, event: AstrMessageEvent):
        """搜索音乐（网易云/酷狗，支持 auto 自动路由）并获取歌曲详情或音频。"""
        user_name = event.get_sender_name()
        message_str = event.message_str.strip()

        logger.debug(f"[Music] 收到消息: '{message_str}' from {user_name}")

        if self._is_help_command(message_str):
            logger.info(f"[Music] Help command triggered by {user_name}")
            yield event.plain_result(MUSIC_HELP_TEXT)
            return

        if not self._netease_client and not self._kugou_client:
            logger.warning(f"[Music] API client not initialized for user {user_name}")
            yield event.plain_result(_format_api_key_not_configured("音乐点歌"))
            return

        # 并发防护：进行中去重 + 冷却，防止连点触发大量并发下载/转码
        hint = self._acquire_music_slot(event)
        if hint:
            yield event.plain_result(hint)
            return
        try:
            query = self._parse_music_params(message_str)
            if not query:
                yield event.plain_result(
                    "❌ 请输入歌曲名或ID\n💡 用法：/music 歌曲名\n💡 发送 /music help 查看帮助"
                )
                return

            music_source = self._get_music_source(event)

            # 通过ID获取歌曲（ID 模式跨源不通用，固定走网易云）
            id_match = re.match(r"^(id|编号)\s*[:：]\s*(\d+)$", query, re.IGNORECASE)
            if id_match:
                song_id = id_match.group(2)
                logger.info(
                    f"[Music] Fetching song by ID {song_id} for user {user_name}"
                )
                if not self._netease_client:
                    yield event.plain_result("❌ ID 模式需要网易云音源，但未配置 API Key")
                    return
                song_data = await self._netease_client.get_song(song_id)
                response_items = await self._format_song_response(song_data, event)
                for item in response_items:
                    yield item
                return

            # 搜索模式：仅列出搜索结果（用当前音源；auto 走网易云）
            search_match = re.match(r"^(search|搜索)\s+(.+)$", query, re.IGNORECASE)
            if search_match:
                search_query = search_match.group(2).strip()
                logger.info(
                    f"[Music] Searching songs '{search_query}' for user {user_name} (source={music_source})"
                )
                list_source = "netease" if music_source == "auto" else music_source
                list_client = self._resolve_single_source(list_source)
                if list_client is None:
                    yield event.plain_result("❌ 当前音源不可用（未配置 API Key）")
                    return
                songs = await list_client.search_songs(search_query)
                if not songs:
                    yield event.plain_result(
                        f"😕 未找到与「{search_query}」相关的歌曲\n💡 请尝试其他关键词"
                    )
                    return
                response_text = self._format_search_results(songs, search_query)
                yield event.plain_result(response_text)
                return

            # file模式：返回未经转码的原始音乐文件
            file_match = re.match(r"^(file|文件)\s+(.+)$", query, re.IGNORECASE)
            if file_match:
                file_query = file_match.group(2).strip()
                logger.info(
                    f"[Music] Download original file '{file_query}' for user {user_name} (source={music_source})"
                )
                try:
                    song_data, used_source = await self._search_and_get(music_source, file_query)
                except NeteaseAPIError as e:
                    yield event.plain_result(f"😕 未找到与「{file_query}」相关的歌曲\n💡 {e}")
                    return

                file_path = await self._download_source_audio_to_temp(
                    song_data.get("url", ""),
                    song_data.get("name", file_query),
                    song_data.get("type", ""),
                )
                if not file_path:
                    yield event.plain_result(
                        f"❌ 无法获取原始音乐文件：{song_data.get('name', file_query)}"
                    )
                    return

                file_name = self._build_audio_filename(
                    song_data.get("name", file_query), file_path
                )
                # 体积校验：原始文件（如 flac）过大时，QQ/NapCat 端常以
                # retcode=1200（下载文件失败）拒绝。超过阈值则转码为 128kbps MP3 再发。
                final_path = file_path
                final_name = file_name
                src_size = os.path.getsize(file_path)
                if (
                    self._music_file_max_bytes > 0
                    and src_size > self._music_file_max_bytes
                ):
                    src_mb = src_size / (1024 * 1024)
                    lim_mb = self._music_file_max_bytes / (1024 * 1024)
                    logger.info(
                        f"[Music] 原始文件 {src_mb:.1f}MB 超过阈值 {lim_mb:.1f}MB，"
                        f"尝试转码为 MP3 后发送: {file_path}"
                    )
                    compressed = await self._compress_for_file(file_path)
                    if compressed:
                        final_path = compressed
                        final_name = self._build_audio_filename(
                            song_data.get("name", file_query), compressed
                        )
                        new_mb = os.path.getsize(compressed) / (1024 * 1024)
                        yield event.plain_result(
                            f"📦 原始文件过大（{src_mb:.1f}MB），已转码为 MP3（{new_mb:.1f}MB）后发送"
                        )
                    else:
                        # 转码失败：仍尝试发原文件，但提示可能失败
                        yield event.plain_result(
                            f"⚠️ 原始文件 {src_mb:.1f}MB 较大，转码失败（未安装 ffmpeg？），"
                            f"仍尝试发送原文件，可能因体积过大失败；建议改用 /音乐 直接 获取语音条"
                        )
                # 优先走 OneBot 本地上传，绕过 Comp.File → callback_api_base HTTP 回调。
                # 实测 callback 配成 webhook 路径时，NapCat 会报「下载文件失败」，表现为
                # /音乐 文件 偶发/常态失效（插件侧其实已下载成功）。
                sent = await self._send_music_file(event, final_path, final_name)
                if not sent:
                    yield event.plain_result(
                        f"❌ 发送音乐文件失败：{final_name}\n"
                        f"💡 可改用 /音乐 直接 获取语音条，或稍后重试"
                    )
                return

            # direct模式：仅返回语音条，不附带额外信息
            direct_match = re.match(r"^(direct|直接)\s+(.+)$", query, re.IGNORECASE)
            if direct_match:
                direct_query = direct_match.group(2).strip()
                logger.info(
                    f"[Music] Direct play '{direct_query}' for user {user_name} (source={music_source})"
                )
                try:
                    song_data, used_source = await self._search_and_get(music_source, direct_query)
                except NeteaseAPIError as e:
                    yield event.plain_result(f"😕 未找到与「{direct_query}」相关的歌曲\n💡 {e}")
                    return

                response_items = await self._format_song_response(
                    song_data, event, direct_mode=True
                )
                for item in response_items:
                    yield item
                return

            # 点歌模式：搜索并获取第一首歌的详细信息
            logger.info(f"[Music] Quick play '{query}' for user {user_name} (source={music_source})")
            try:
                song_data, used_source = await self._search_and_get(music_source, query)
            except NeteaseAPIError as e:
                yield event.plain_result(
                    f"😕 未找到与「{query}」相关的歌曲\n💡 请尝试其他关键词或切换音源（/音源）"
                )
                return

            response_items = await self._format_song_response(song_data, event)
            for item in response_items:
                yield item

        except NeteaseAPIError as e:
            logger.error(f"[Music] API error for user {user_name}: {e}")
            error_msg = f"❌ 获取音乐失败\n📝 错误信息：{str(e)}"
            if e.status_code:
                error_msg += f"\n🔢 状态码：{e.status_code}"
            error_msg += "\n💡 请稍后重试或发送 /music help 查看帮助"
            yield event.plain_result(error_msg)
        except Exception as e:
            logger.error(
                f"[Music] Unexpected error for user {user_name}: {e}", exc_info=True
            )
            yield event.plain_result(
                f"❌ 发生未知错误\n📝 错误信息：{str(e)}\n💡 请稍后重试"
            )
        finally:
            self._release_music_slot(event)

    @filter.command("点歌")
    async def play_song_command(self, event: AstrMessageEvent):
        """快捷点歌命令：等效于 /音乐 直接 <歌曲名>，仅返回语音条。"""
        user_name = event.get_sender_name()
        message_str = event.message_str.strip()

        logger.debug(f"[PlaySong] 收到消息: '{message_str}' from {user_name}")

        if self._is_help_command(message_str):
            logger.info(f"[PlaySong] Help command triggered by {user_name}")
            yield event.plain_result(MUSIC_HELP_TEXT)
            return

        if not self._netease_client and not self._kugou_client:
            logger.warning(
                f"[PlaySong] API client not initialized for user {user_name}"
            )
            yield event.plain_result(_format_api_key_not_configured("音乐点歌"))
            return

        query = self._parse_play_song_params(message_str)
        if not query:
            yield event.plain_result(
                "❌ 请输入歌曲名\n💡 用法：/点歌 歌曲名\n💡 发送 /点歌 help 查看帮助"
            )
            return

        # 并发防护：进行中去重 + 冷却，防止连点触发大量并发下载/转码
        hint = self._acquire_music_slot(event)
        if hint:
            yield event.plain_result(hint)
            return
        try:
            music_source = self._get_music_source(event)
            logger.info(f"[PlaySong] Direct play '{query}' for user {user_name} (source={music_source})")
            try:
                song_data, used_source = await self._search_and_get(music_source, query)
            except NeteaseAPIError as e:
                yield event.plain_result(
                    f"😕 未找到与「{query}」相关的歌曲\n💡 请尝试其他关键词或切换音源（/音源）"
                )
                return

            response_items = await self._format_song_response(
                song_data, event, direct_mode=True
            )
            for item in response_items:
                yield item

        except NeteaseAPIError as e:
            logger.error(f"[PlaySong] API error for user {user_name}: {e}")
            error_msg = f"❌ 获取音乐失败\n📝 错误信息：{str(e)}"
            if e.status_code:
                error_msg += f"\n🔢 状态码：{e.status_code}"
            error_msg += "\n💡 请稍后重试或发送 /点歌 help 查看帮助"
            yield event.plain_result(error_msg)
        except Exception as e:
            logger.error(
                f"[PlaySong] Unexpected error for user {user_name}: {e}", exc_info=True
            )
            yield event.plain_result(
                f"❌ 发生未知错误\n📝 错误信息：{str(e)}\n💡 请稍后重试"
            )
        finally:
            self._release_music_slot(event)

    def _acquire_music_slot(self, event: AstrMessageEvent) -> Optional[str]:
        """点歌并发防护：尝试为当前会话占用一个处理槽。

        Returns:
            None 表示放行（已占用槽位，调用方处理完后必须 _release_music_slot）；
            非 None 字符串表示被拦截，直接作为提示返回给用户。
        """
        umo = event.unified_msg_origin
        if not umo:
            return None  # 无法识别会话，不拦截
        # 1) 进行中去重：同一会话已有音乐命令在处理
        if umo in self._music_in_progress:
            return "⏳ 上一首歌还在处理中，请稍候再试～"
        # 2) 冷却：上一次完成后短时间内禁止再点
        if self._music_cooldown > 0:
            last = self._music_last_done.get(umo)
            if last is not None:
                elapsed = time.time() - last
                if elapsed < self._music_cooldown:
                    wait = self._music_cooldown - elapsed
                    return f"⏳ 点得太快啦，请等待约 {wait:.0f} 秒后再试～"
        # 放行：占用槽位
        self._music_in_progress.add(umo)
        return None

    def _release_music_slot(self, event: AstrMessageEvent) -> None:
        """释放当前会话的处理槽，并记录完成时间戳（用于冷却计算）。"""
        umo = event.unified_msg_origin
        if not umo:
            return
        self._music_in_progress.discard(umo)
        self._music_last_done[umo] = time.time()

    # --- 音源选择（auto / 网易云 / 酷狗）---
    def _get_music_source(self, event: AstrMessageEvent) -> str:
        """返回当前会话的音源偏好（auto/netease/kugou），未设置则返回默认。"""
        umo = event.unified_msg_origin
        return self._music_source_pref.get(umo, self._music_default_source)

    def _resolve_single_source(self, source: str):
        """把具体音源名(netease/kugou)解析为对应客户端。auto 不应传到这里。"""
        if source == "kugou":
            return self._kugou_client
        return self._netease_client  # 默认/兜底走网易云

    async def _try_source(
        self, source: str, query: str
    ) -> Optional[tuple]:
        """尝试单一音源：搜索→取首首歌详情。成功返回 (song_data, source)，失败返回 None。

        失败包括：搜索为空、取详情异常、详情无播放链接（VIP/无版权）。
        """
        client = self._resolve_single_source(source)
        if client is None:
            return None
        try:
            songs = await client.search_songs(query)
            if not songs:
                return None
            first = songs[0]
            song_id = str(first.get("id", ""))
            hash_val = str(first.get("hash", "")) if source == "kugou" else ""
            if source == "kugou" and not hash_val and not song_id:
                return None
            if source == "netease" and not song_id:
                return None
            song_data = await client.get_song(song_id, hash_val) if source == "kugou" else await client.get_song(song_id)
            # 必须有播放链接才算成功
            if not song_data.get("url"):
                return None
            return (song_data, source)
        except Exception as e:
            logger.info(f"[Music] 音源 {source} 取歌失败，将尝试下一个: {e}")
            return None

    async def _search_and_get(
        self, source: str, query: str
    ) -> tuple:
        """统一搜索+取详情入口，处理 auto 自动路由。

        - source=auto：网易云优先，失败(VIP/无版权/空/异常)转酷狗
        - source=netease/kugou：仅走指定源
        返回 (song_data, used_source)；全部失败抛 NeteaseAPIError。
        """
        if source == "auto":
            result = await self._try_source("netease", query)
            if result:
                return result
            logger.info(f"[Music] auto 模式：网易云未取到「{query}」，转酷狗")
            result = await self._try_source("kugou", query)
            if result:
                return result
            raise NeteaseAPIError("网易云与酷狗均未找到可播放的歌曲")
        # 指定单一源
        result = await self._try_source(source, query)
        if result:
            return result
        src_name = {"netease": "网易云", "kugou": "酷狗"}.get(source, source)
        raise NeteaseAPIError(f"{src_name}未找到可播放的歌曲")

    @filter.command("音源")
    async def music_source_command(self, event: AstrMessageEvent):
        """查看或切换当前会话的点歌音源（auto/网易云/酷狗）。"""
        message_str = event.message_str.strip()
        # 解析参数：去掉命令前缀和「音源」
        cleaned = re.sub(r"^[/!！]\s*音源\s*", "", message_str, flags=re.IGNORECASE)
        cleaned = re.sub(r"^音源\s*", "", cleaned, flags=re.IGNORECASE).strip().lower()

        source_names = {"auto": "auto（自动）", "netease": "网易云", "kugou": "酷狗"}
        alias_map = {
            "auto": "auto", "自动": "auto", "automatic": "auto",
            "netease": "netease", "网易云": "netease", "网易": "netease", "wy": "netease",
            "kugou": "kugou", "酷狗": "kugou", "kg": "kugou",
        }

        if not cleaned or cleaned in ("help", "-h", "--help", "帮助", "?", "？"):
            cur = self._get_music_source(event)
            yield event.plain_result(
                f"🎵 当前音源：{source_names.get(cur, cur)}\n\n"
                "💡 用法：\n"
                "  /音源 auto（自动）  网易云优先，失败转酷狗\n"
                "  /音源 网易云        仅网易云\n"
                "  /音源 酷狗          仅酷狗\n\n"
                "音源按会话(群/私聊)记忆，重启后重置为默认。"
            )
            return

        target = alias_map.get(cleaned)
        if not target:
            yield event.plain_result(
                f"❌ 未知音源「{cleaned}」\n💡 可选：auto / 网易云 / 酷狗\n💡 发送 /音源 查看当前状态"
            )
            return

        umo = event.unified_msg_origin
        if umo:
            self._music_source_pref[umo] = target
        yield event.plain_result(
            f"✅ 已切换音源为：{source_names[target]}\n"
            + ("（网易云优先，失败自动转酷狗）" if target == "auto" else "")
        )

    def _parse_play_song_params(self, message: str) -> Optional[str]:
        """解析 /点歌 命令参数，剥离命令名后返回剩余的歌曲名。"""
        cleaned = re.sub(r"^[/!！]\s*点歌\s*", "", message.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"^点歌\s*", "", cleaned.strip(), flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        if not cleaned or cleaned.lower() in ("help", "-h", "--help", "帮助"):
            return None

        return cleaned

    def _parse_music_params(self, message: str) -> Optional[str]:
        cleaned = re.sub(
            r"^[/!！]\s*(music|音乐)\s*", "", message.strip(), flags=re.IGNORECASE
        )
        cleaned = re.sub(r"^(music|音乐)\s*", "", cleaned.strip(), flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        if not cleaned or cleaned.lower() in ("help", "-h", "--help", "帮助"):
            return None

        return cleaned

    async def _format_song_response(
        self,
        song_data: Dict[str, Any],
        event: AstrMessageEvent,
        direct_mode: bool = False,
    ) -> List[Any]:
        name = song_data.get("name", "未知歌曲")
        artists = song_data.get("artists", "未知艺术家")
        album = song_data.get("album", "")
        pic_url = song_data.get("pic", "")
        url = song_data.get("url", "")
        level = song_data.get("level", "")
        bitrate = song_data.get("bitrate", 0)
        file_type = song_data.get("type", "")
        size = song_data.get("size", 0)

        results = []

        if not direct_mode:
            parts = [f"🎵 {name}", f"👤 艺术家：{artists}"]
            if album:
                parts.append(f"💿 专辑：{album}")

            quality_parts = []
            if level:
                level_map = {
                    "standard": "标准",
                    "higher": "较高",
                    "exhigh": "极高",
                    "lossless": "无损",
                    "hires": "Hi-Res",
                }
                quality_parts.append(level_map.get(level, level))
            if file_type:
                quality_parts.append(file_type.upper())
            if bitrate:
                quality_parts.append(f"{bitrate // 1000}kbps")
            if quality_parts:
                parts.append(f"🎧 音质：{' / '.join(quality_parts)}")

            if size:
                size_mb = size / (1024 * 1024)
                parts.append(f"📦 大小：{size_mb:.1f}MB")

            if url:
                parts.append(f"🔗 播放链接：{url}")
            else:
                parts.append("⚠️ 无法获取播放链接（可能需要VIP权限）")

            caption = "\n".join(parts)
            results.append(event.plain_result(caption))

            if pic_url:
                results.append(event.image_result(pic_url))

        # 如果有播放链接，尝试下载音频并通过 Comp.Record 发送语音条
        if url:
            try:
                local_path = await self._download_audio_to_temp(url, name)
                if local_path:
                    record_comp = Comp.Record.fromFileSystem(local_path)
                    results.append(event.chain_result([record_comp]))
                    logger.info(f"[Music] 已添加语音消息: {name} -> {local_path}")
                elif not direct_mode:
                    pass
                else:
                    results.append(event.plain_result(f"❌ 无法生成语音条：{name}"))
            except Exception as e:
                logger.warning(f"[Music] 发送语音消息失败: {e}，仅发送文本链接")
                if direct_mode:
                    results.append(event.plain_result(f"❌ 发送语音失败：{e}"))
        elif direct_mode:
            results.append(event.plain_result("⚠️ 无法获取播放链接（可能需要VIP权限）"))

        return results

    @staticmethod
    def _audio_extension(file_type: str, url: str) -> str:
        normalized_type = str(file_type).lower().strip().lstrip(".")
        if normalized_type in {"mp3", "flac", "wav", "m4a", "aac", "ogg", "opus"}:
            return f".{normalized_type}"

        url_without_query = url.lower().split("?", 1)[0]
        for extension in (".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".mp3"):
            if url_without_query.endswith(extension):
                return extension
        return ".mp3"

    @classmethod
    def _build_audio_filename(cls, name: str, source_path: str) -> str:
        safe_name = re.sub(r"[^\w\-.]", "_", name)[:50] or "music"
        return f"{safe_name}{os.path.splitext(source_path)[1]}"

    @staticmethod
    def _resolve_onebot_call_action(event: AstrMessageEvent):
        """从 event 上解析 OneBot call_action 可调用对象；不可用则返回 None。"""
        bot = getattr(event, "bot", None)
        if bot is None:
            return None
        call = getattr(bot, "call_action", None)
        if callable(call):
            return call
        api = getattr(bot, "api", None)
        call = getattr(api, "call_action", None) if api is not None else None
        return call if callable(call) else None

    async def _send_music_file(
        self, event: AstrMessageEvent, file_path: str, file_name: str
    ) -> bool:
        """发送本地音乐文件。

        优先使用 OneBot ``upload_group_file`` / ``upload_private_file`` 直接上传本地路径，
        避免 ``Comp.File`` 经 ``callback_api_base`` 转成 HTTP 回调后被 NapCat 二次下载失败
        （日志常见「下载文件失败」，而插件侧其实已成功落盘）。

        OneBot 不可用时再回退 ``Comp.File`` 消息段。
        """
        if not file_path or not os.path.isfile(file_path):
            logger.warning(f"[Music] 发送失败：本地文件不存在 {file_path}")
            return False
        if os.path.getsize(file_path) <= 0:
            logger.warning(f"[Music] 发送失败：本地文件为空 {file_path}")
            return False

        abs_path = os.path.abspath(file_path)
        call = self._resolve_onebot_call_action(event)
        if call is not None:
            try:
                group_id = ""
                try:
                    group_id = str(event.get_group_id() or "").strip()
                except Exception:
                    group_id = ""
                if group_id and group_id.isdigit():
                    await call(
                        "upload_group_file",
                        group_id=int(group_id),
                        file=abs_path,
                        name=file_name,
                    )
                    logger.info(
                        f"[Music] 已通过 upload_group_file 发送: {file_name} -> {abs_path}"
                    )
                    return True

                sender_id = ""
                try:
                    sender_id = str(event.get_sender_id() or "").strip()
                except Exception:
                    sender_id = ""
                if sender_id and sender_id.isdigit():
                    await call(
                        "upload_private_file",
                        user_id=int(sender_id),
                        file=abs_path,
                        name=file_name,
                    )
                    logger.info(
                        f"[Music] 已通过 upload_private_file 发送: {file_name} -> {abs_path}"
                    )
                    return True
                logger.warning(
                    "[Music] OneBot 可用但无法解析 group_id/user_id，回退 Comp.File"
                )
            except Exception as e:
                logger.warning(
                    f"[Music] OneBot 本地上传失败，回退 Comp.File: {e}",
                    exc_info=True,
                )

        # 回退：通用 File 消息段（依赖平台适配器；aiocqhttp 下可能再走 callback）
        try:
            await event.send(
                event.chain_result([Comp.File(name=file_name, file=abs_path)])
            )
            logger.info(f"[Music] 已通过 Comp.File 发送: {file_name} -> {abs_path}")
            return True
        except Exception as e:
            logger.warning(f"[Music] Comp.File 发送失败: {e}", exc_info=True)
            return False

    async def _download_source_audio_to_temp(
        self, url: str, name: str, file_type: str = ""
    ) -> Optional[str]:
        """原样下载音频文件，供文件模式作为附件发送。

        大体积 flac 下载可能超过 30s；对超时/网络错误做有限重试，并拒绝空文件。
        """
        if not url:
            logger.warning("[Music] 原始文件下载失败：没有播放链接")
            return None

        temp_dir = os.path.join(tempfile.gettempdir(), "astrbot_music")
        os.makedirs(temp_dir, exist_ok=True)
        self._cleanup_old_audio_files(temp_dir)

        safe_name = re.sub(r"[^\w\-.]", "_", name)[:50] or "music"
        extension = self._audio_extension(file_type, url)
        headers = {"User-Agent": "AstrBot-Music-Plugin/1.0"}
        if self._leiz_api_key:
            headers["x-api-key"] = self._leiz_api_key

        # 单次最长 90s（大 flac 常见 15~40MB）；共 3 次，指数退避。
        max_attempts = 3
        backoff_base = 0.8
        last_error: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            request_id = uuid.uuid4().hex[:12]
            temp_path = os.path.join(
                temp_dir, f"{safe_name}_{request_id}_source{extension}"
            )
            downloaded = False
            try:
                timeout = aiohttp.ClientTimeout(total=90, sock_connect=15, sock_read=60)
                async with aiohttp.ClientSession(
                    timeout=timeout, headers=headers
                ) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            last_error = f"HTTP {resp.status}"
                            logger.warning(
                                f"[Music] 下载原始音乐失败: {last_error} "
                                f"(attempt {attempt}/{max_attempts})"
                            )
                            # 4xx 业务错误不重试（除 408/429）
                            if resp.status < 500 and resp.status not in (408, 429):
                                return None
                        else:
                            with open(temp_path, "wb") as audio_file:
                                async for chunk in resp.content.iter_chunked(64 * 1024):
                                    if chunk:
                                        audio_file.write(chunk)
                            downloaded = True

                if downloaded:
                    size = os.path.getsize(temp_path)
                    if size <= 0:
                        last_error = "空文件"
                        logger.warning(
                            f"[Music] 下载原始音乐得到空文件 "
                            f"(attempt {attempt}/{max_attempts})"
                        )
                        self._remove_file(temp_path)
                    else:
                        logger.info(
                            f"[Music] 原始音频已下载（未转码）: {temp_path} "
                            f"({size / (1024 * 1024):.2f}MB)"
                        )
                        return temp_path
            except asyncio.TimeoutError:
                last_error = "超时"
                logger.warning(
                    f"[Music] 下载原始音乐超时 (attempt {attempt}/{max_attempts}): {name}"
                )
            except aiohttp.ClientError as e:
                last_error = f"网络错误: {e}"
                logger.warning(
                    f"[Music] 下载原始音乐网络错误 "
                    f"(attempt {attempt}/{max_attempts}): {e}"
                )
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(f"[Music] 下载原始音乐异常: {e}")
                self._remove_file(temp_path)
                return None
            finally:
                if not downloaded:
                    self._remove_file(temp_path)

            if attempt < max_attempts:
                await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))

        logger.warning(
            f"[Music] 下载原始音乐最终失败（{max_attempts} 次）: {name}; last={last_error}"
        )
        return None

    async def _download_audio_to_temp(self, url: str, name: str) -> Optional[str]:
        """下载音频文件到临时目录，并压缩为语音条专用低码率 MP3。

        无论上游返回何种格式（mp3/flac/wav/m4a），下载后一律经 ffmpeg
        压缩为 64kbps 单声道 MP3，确保语音条不超平台大小限制。
        """
        try:
            ext = ".mp3"
            if ".flac" in url.lower():
                ext = ".flac"
            elif ".wav" in url.lower():
                ext = ".wav"
            elif ".m4a" in url.lower():
                ext = ".m4a"

            temp_dir = os.path.join(tempfile.gettempdir(), "astrbot_music")
            os.makedirs(temp_dir, exist_ok=True)

            self._cleanup_old_audio_files(temp_dir)

            safe_name = re.sub(r"[^\w\-.]", "_", name)[:50] or "music"
            request_id = uuid.uuid4().hex[:12]
            temp_path = os.path.join(temp_dir, f"{safe_name}_{request_id}_source{ext}")

            timeout = aiohttp.ClientTimeout(total=30)
            # LeiZ 接口要求所有请求携带 API Key（鉴权头为 x-api-key）。
            # 歌曲下载地址可能经 LeiZ 代理，因此附加统一的 x-api-key 头；
            # 对非 LeiZ 的 CDN 地址多带此头无副作用。
            dl_headers = {"User-Agent": "AstrBot-Music-Plugin/1.0"}
            if self._leiz_api_key:
                dl_headers["x-api-key"] = self._leiz_api_key
            async with aiohttp.ClientSession(
                timeout=timeout, headers=dl_headers
            ) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(f"[Music] 下载音频失败: HTTP {resp.status}")
                        return None

                    with open(temp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)

            # 一律压缩为 64kbps 单声道 MP3，避免语音条超平台大小限制。
            # 源文件已是 .mp3 时仍需重压（上游常见 320kbps，体积过大）。
            src_mb = os.path.getsize(temp_path) / (1024 * 1024)
            logger.debug(f"[Music] 原始音频已下载: {temp_path} ({src_mb:.2f}MB)")
            compressed = await self._compress_for_voice(temp_path, temp_dir, safe_name)
            if compressed:
                return compressed

            logger.warning(
                "[Music] 语音压缩失败，回退发送原始音频（可能受平台大小/格式限制）: %s",
                temp_path,
            )
            return temp_path

        except asyncio.TimeoutError:
            logger.warning("[Music] 下载音频超时（30秒）: %s", name)
            if "temp_path" in locals():
                self._remove_file(temp_path)
            return None
        except Exception as e:
            logger.warning(
                "[Music] 下载音频异常 [%s] %r: %s",
                type(e).__name__,
                e,
                name,
                exc_info=True,
            )
            if "temp_path" in locals():
                self._remove_file(temp_path)
            return None

    async def _compress_for_voice(
        self, source_path: str, temp_dir: str, safe_name: str
    ) -> Optional[str]:
        """将音频压缩为语音条专用的低码率 MP3。"""
        if not shutil.which("ffmpeg"):
            logger.warning("[Music] ffmpeg 未安装，无法压缩音频")
            return None

        request_id = uuid.uuid4().hex[:12]
        mp3_path = os.path.join(temp_dir, f"{safe_name}_{request_id}_voice.mp3")
        proc = None
        compressed_path = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                source_path,
                "-vn",  # 丢弃视频/封面流
                "-codec:a",
                "libmp3lame",
                "-ar",
                "24000",  # 采样率：语音足够
                "-ac",
                "1",  # 单声道
                "-b:a",
                "64k",  # 码率：4分钟约 1.8MB
                mp3_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0 and os.path.isfile(mp3_path):
                self._remove_file(source_path)
                size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
                logger.info(
                    f"[Music] 已压缩为语音条 MP3 (64kbps mono): {mp3_path} ({size_mb:.2f}MB)"
                )
                compressed_path = mp3_path
            else:
                error_detail = (stderr or b"").decode("utf-8", errors="replace").strip()
                if len(error_detail) > 1000:
                    error_detail = f"{error_detail[-1000:]} (已截断)"
                logger.warning(
                    f"[Music] ffmpeg 压缩失败，退出码 {proc.returncode}: "
                    f"{error_detail or '无错误输出'}"
                )
        except asyncio.TimeoutError:
            logger.warning("[Music] ffmpeg 压缩超时")
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
        except Exception as e:
            logger.warning(f"[Music] ffmpeg 压缩异常: {e}")
        finally:
            if compressed_path is None:
                self._remove_file(mp3_path)
        return compressed_path

    async def _compress_for_file(self, source_path: str) -> Optional[str]:
        """将音频转码为 128kbps 立体声 MP3，用于 /音乐 文件 模式的体积超限降级。

        与 _compress_for_voice（64kbps 单声道，语音条专用）不同，这里保留立体声与
        较高码率，听感接近原曲，同时体积远小于无损 flac。需要 ffmpeg，失败返回 None。
        """
        if not shutil.which("ffmpeg"):
            logger.warning("[Music] ffmpeg 未安装，无法为文件模式转码")
            return None

        temp_dir = os.path.dirname(source_path)
        base = os.path.splitext(os.path.basename(source_path))[0]
        request_id = uuid.uuid4().hex[:12]
        mp3_path = os.path.join(temp_dir, f"{base}_{request_id}_file.mp3")
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                source_path,
                "-vn",  # 丢弃视频/封面流
                "-codec:a",
                "libmp3lame",
                "-ar",
                "44100",  # 标准采样率
                "-ac",
                "2",  # 立体声
                "-b:a",
                "128k",  # 码率：4分钟约 3.7MB
                mp3_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode == 0 and os.path.isfile(mp3_path):
                # 转码成功后删除原始大文件
                self._remove_file(source_path)
                size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
                logger.info(
                    f"[Music] 已转码为文件 MP3 (128kbps stereo): {mp3_path} ({size_mb:.2f}MB)"
                )
                return mp3_path
            error_detail = (stderr or b"").decode("utf-8", errors="replace").strip()
            if len(error_detail) > 1000:
                error_detail = f"{error_detail[-1000:]} (已截断)"
            logger.warning(
                f"[Music] 文件模式 ffmpeg 转码失败，退出码 {proc.returncode}: "
                f"{error_detail or '无错误输出'}"
            )
        except asyncio.TimeoutError:
            logger.warning("[Music] 文件模式 ffmpeg 转码超时")
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
        except Exception as e:
            logger.warning(f"[Music] 文件模式转码异常: {e}")
        finally:
            # 失败时清理产物
            if proc and proc.returncode != 0 and os.path.exists(mp3_path):
                self._remove_file(mp3_path)
        return None

    @staticmethod
    def _remove_file(file_path: str):
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.debug(f"[Music] 清理临时文件失败: {file_path}: {e}")

    @staticmethod
    def _cleanup_old_audio_files(temp_dir: str, max_age_seconds: int = 3600):
        """清理超过max_age_seconds的旧音频文件"""
        try:
            now = time.time()
            for filename in os.listdir(temp_dir):
                filepath = os.path.join(temp_dir, filename)
                if os.path.isfile(filepath):
                    if now - os.path.getmtime(filepath) > max_age_seconds:
                        os.remove(filepath)
        except Exception:
            pass

    def _format_search_results(self, songs: List[Dict[str, Any]], query: str) -> str:
        parts = [f"🔍 搜索「{query}」结果：\n"]
        for i, song in enumerate(songs[:10], 1):
            name = song.get("name", "未知")
            artists = song.get("artists", "未知")
            song_id = song.get("id", "")
            parts.append(f"  {i}. {name} - {artists}")
            if song_id:
                parts.append(f"     ID: {song_id}")

        parts.append(f"\n💡 使用 /music id:<歌曲ID> 获取详细信息和播放链接")
        return "\n".join(parts)

    @filter.command("pixiv", alias={"图片"})
    async def pixiv_command(self, event: AstrMessageEvent):
        """获取或按条件筛选 Pixiv 随机图片。"""
        user_name = event.get_sender_name()
        message_str = event.message_str.strip()

        logger.debug(f"[DEBUG] 收到消息: '{message_str}'")

        if self._is_help_command(message_str):
            logger.info(f"Help command triggered by {user_name}")
            yield event.plain_result(HELP_TEXT)
            return

        if not self._api_client:
            logger.warning(f"Pixiv API client not initialized for user {user_name}")
            yield event.plain_result(_format_api_key_not_configured("Pixiv 随机图片"))
            return

        try:
            params = self._build_request_params(message_str)

            logger.info(f"Fetching for user {user_name}, params={params}")

            api_params = self._prepare_api_params(params)
            result = await self._api_client.fetch_images(**api_params)

            response_items = await self._process_response(result, params, event)
            for item in response_items:
                yield item

        except PixivAPIError as e:
            logger.error(f"Pixiv API error for user {user_name}: {e}")
            error_msg = f"❌ 获取图片失败\n📝 错误信息：{str(e)}"
            if e.status_code:
                error_msg += f"\n🔢 状态码：{e.status_code}"
            error_msg += "\n💡 请稍后重试或检查参数是否正确"
            yield event.plain_result(error_msg)
        except ValueError as e:
            logger.error(f"Parameter error for user {user_name}: {e}")
            yield event.plain_result(
                f"❌ 参数错误：{str(e)}\n💡 发送 /pixiv help 查看使用说明"
            )
        except Exception as e:
            logger.error(f"Unexpected error for user {user_name}: {e}", exc_info=True)
            yield event.plain_result(
                f"❌ 发生未知错误\n📝 错误信息：{str(e)}\n💡 请稍后重试或联系管理员"
            )

    def _is_help_command(self, message: str) -> bool:
        """
        检测是否为帮助命令。
        支持所有命令名（英文和中文别名）的 help 检测。
        """
        if not message:
            return False

        msg_clean = message.strip()

        # 标准化消息：移除命令前缀
        normalized = re.sub(r"^[/!！]", "", msg_clean).strip()

        # 所有已知命令名（英文+中文别名），按长度降序排列避免前缀误匹配
        command_names = [
            "jmcommend",
            "漫画推荐",
            "hitokoto",
            "weather",
            "pixiv",
            "femboy",
            "music",
            "dglab",
            "图片",
            "一言",
            "天气",
            "男娘",
            "音乐",
            "点歌",
            "漫画",
            "电击",
            "jm",
        ]

        # 尝试剥离命令名，提取参数部分
        args_part = normalized
        for cmd in command_names:
            if normalized.lower().startswith(cmd.lower()):
                args_part = normalized[len(cmd) :].strip()
                break

        lower_args = args_part.lower().strip()

        # 定义所有帮助关键词
        help_keywords = {"help", "-h", "--help", "帮助", "?", "？"}

        # 精确匹配
        if lower_args in help_keywords:
            return True

        # 空参数不算help
        if not lower_args:
            return False

        # 检查是否以帮助关键词开头或结尾
        for kw in ["help", "帮助"]:
            if (
                lower_args == kw
                or lower_args.startswith(kw + " ")
                or lower_args.endswith(" " + kw)
            ):
                return True

        return False

    def _build_request_params(self, message: str) -> Dict[str, Any]:
        # 标准化消息：移除命令前缀和 "pixiv"/"图片" 关键字
        cleaned = re.sub(
            r"^[/!！]\s*(pixiv|图片)\s*", "", message.strip(), flags=re.IGNORECASE
        )
        cleaned = re.sub(r"^(pixiv|图片)\s*", "", cleaned.strip(), flags=re.IGNORECASE)

        logger.debug(
            f"[DEBUG] _build_request_params 输入: '{message}' → 清理后: '{cleaned}'"
        )

        parsed = CommandParser.parse(cleaned)

        params: Dict[str, Any] = {
            "r18": parsed.get("r18", self._default_r18),
            "num": parsed.get("num", self._default_num),
            "size": parsed.get("size", self._default_size),
        }

        if parsed.get("tag"):
            params["tag"] = parsed["tag"]
        if parsed.get("keyword"):
            params["keyword"] = parsed["keyword"]
        if parsed.get("uid"):
            params["uid"] = parsed["uid"]
        if parsed.get("aspectRatio"):
            params["aspectRatio"] = parsed["aspectRatio"]
        if parsed.get("dateAfter"):
            params["dateAfter"] = parsed["dateAfter"]
        if parsed.get("dateBefore"):
            params["dateBefore"] = parsed["dateBefore"]

        exclude_ai = parsed.get("excludeAI")
        if exclude_ai is None:
            exclude_ai = self._exclude_ai
        if exclude_ai:
            params["excludeAI"] = True

        logger.info(f"Parsed params: {params}")
        return params

    def _prepare_api_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        api_params = dict(params)
        api_params["proxy"] = self._image_proxy
        return api_params

    async def _process_response(
        self, result: Dict[str, Any], params: Dict[str, Any], event: AstrMessageEvent
    ) -> List[Any]:
        response_type = result.get("type")

        if response_type == "redirect":
            url = result.get("url", "")
            r18_label = self._get_r18_label(params.get("r18", 0))
            caption = self._build_caption(
                {
                    "url": url,
                },
                r18_label,
            )
            return [event.plain_result(caption), event.image_result(url)]

        if response_type == "json":
            data = result.get("data", {})
            items = self._extract_items(data)
            if not items:
                return [
                    event.plain_result(
                        "😕 未找到符合条件的图片，请尝试更换参数\n💡 发送 /pixiv help 查看使用说明"
                    )
                ]

            r18_label = self._get_r18_label(params.get("r18", 0))
            responses = []
            for i, item in enumerate(items):
                caption = self._build_caption(
                    item, r18_label, idx=i + 1, total=len(items)
                )
                responses.append(event.plain_result(caption))
                image_url = self._extract_image_url(item)
                if image_url:
                    responses.append(event.image_result(image_url))
                else:
                    responses.append(event.plain_result("⚠️ 未能提取到图片链接"))
            return responses

        logger.warning(f"Unknown response type: {response_type}")
        return [event.plain_result("⚠️ API 返回了未知格式的数据，请联系管理员")]

    def _extract_items(self, data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("data", "illusts", "illustrations", "items", "results"):
                if key in data and isinstance(data[key], list):
                    return [item for item in data[key] if isinstance(item, dict)]
            if "illust" in data and isinstance(data["illust"], dict):
                return [data["illust"]]
            if any(isinstance(v, (list, dict)) for v in data.values()):
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        return [item for item in v if isinstance(item, dict)]
        return []

    def _extract_image_url(self, item: Dict[str, Any]) -> Optional[str]:
        if not isinstance(item, dict):
            return None
        if isinstance(item.get("urls"), dict):
            urls = item["urls"]
            preferred_order = ["regular", "original", "small", "thumb", "mini"]
            for size in preferred_order:
                if urls.get(size):
                    return urls[size]
        for key in ("url", "image_url", "img_url", "regular", "original"):
            val = item.get(key)
            if val and isinstance(val, str) and val.startswith("http"):
                return val
        pid = item.get("pid")
        if pid:
            return f"https://{self._image_proxy}/{pid}.jpg"
        return None

    def _build_caption(
        self, item: Dict[str, Any], r18_label: str, idx: int = 0, total: int = 1
    ) -> str:
        parts = []

        if not isinstance(item, dict):
            return "⚠️ 数据格式异常"

        if total > 1 and idx > 0:
            parts.append(f"📷 [{idx}/{total}]")

        title = item.get("title", "")
        author = (
            item.get("author") or item.get("user_name") or item.get("userName") or ""
        )
        pid = item.get("pid") or item.get("id") or item.get("illust_id") or ""

        if title:
            parts.append(f"🎨 {title}")
        if author:
            parts.append(f"👤 作者：{author}")
        if pid:
            parts.append(f"🔗 {PIXIV_ARTWORK_URL.format(pid)}")

        tags = item.get("tags", [])
        if isinstance(tags, list) and tags:
            tag_names = []
            for t in tags[:8]:
                if isinstance(t, dict):
                    tag_names.append(t.get("name", str(t)))
                else:
                    tag_names.append(str(t))
            parts.append(f"🏷️ 标签：{' / '.join(tag_names)}")

        if r18_label:
            parts.append(r18_label)

        width = item.get("width", 0)
        height = item.get("height", 0)
        if width and height:
            parts.append(f"📐 尺寸：{width}×{height}")

        return "\n".join(parts)

    @staticmethod
    def _get_r18_label(r18: int) -> str:
        if r18 == 1:
            return "⚠️ [R-18] 此内容包含成人内容，请确保您已成年"
        if r18 == 2:
            return "🔞 [混合模式] 可能包含 R-18 内容"
        return ""

    @filter.command("jm", alias={"漫画"})
    async def jm_command(self, event: AstrMessageEvent):
        """搜索 JMComic 漫画、查看详情或获取章节内容。"""
        user_name = event.get_sender_name()
        message_str = event.message_str.strip()

        logger.debug(f"[JMComic] 收到消息: '{message_str}' from {user_name}")

        if self._is_help_command(message_str):
            logger.info(f"[JMComic] Help command triggered by {user_name}")
            yield event.plain_result(JMCOMIC_HELP_TEXT)
            return

        if not self._jmcomic_client:
            logger.warning(f"[JMComic] API client not initialized for user {user_name}")
            yield event.plain_result(_format_api_key_not_configured("JMComic 漫画"))
            return

        try:
            action, params = self._parse_jm_params(message_str)

            if action == "search":
                query = params.get("query", "")
                page = params.get("page", 1)
                if not query:
                    yield event.plain_result(
                        "❌ 请输入搜索关键词\n💡 用法：/jm search 关键词\n💡 发送 /jm help 查看帮助"
                    )
                    return

                logger.info(
                    f"[JMComic] Searching '{query}' page={page} for user {user_name}"
                )
                data = await self._jmcomic_client.search(query, page)
                response_text = self._format_jm_search_results(data, query, page)
                yield event.plain_result(response_text)

            elif action == "detail":
                comic_id = params.get("id", "")
                if not comic_id:
                    yield event.plain_result(
                        "❌ 请输入漫画ID\n💡 用法：/jm detail 漫画ID\n💡 发送 /jm help 查看帮助"
                    )
                    return

                logger.info(
                    f"[JMComic] Fetching detail for id={comic_id}, user={user_name}"
                )
                data = await self._jmcomic_client.get_detail(comic_id)
                response_text = self._format_jm_detail(data)
                yield event.plain_result(response_text)

            elif action == "chapter":
                chapter_id = params.get("id", "")
                if not chapter_id:
                    yield event.plain_result(
                        "❌ 请输入章节ID\n💡 用法：/jm 章节ID（或 /jm chapter 章节ID）\n💡 发送 /jm help 查看帮助"
                    )
                    return

                logger.info(
                    f"[JMComic] Fetching chapter id={chapter_id}, user={user_name}"
                )
                data = await self._jmcomic_client.get_chapter(chapter_id)
                images = self._extract_jm_images(data)
                if not images:
                    yield event.plain_result("⚠️ 该章节暂无图片数据")
                    return

                response_items, next_offset = await self._format_jm_chapter(
                    event, images, offset=0
                )
                for item in response_items:
                    yield item

                # 仍有剩余：记录游标供 /jm con 续看（仅内存、带 TTL）
                if next_offset < len(images):
                    self._set_jm_chapter_cursor(event, chapter_id, images, next_offset)

            elif action == "continue":
                cursor = self._get_jm_chapter_cursor(event)
                if not cursor:
                    yield event.plain_result(
                        "❌ 暂无可续看的章节\n💡 请先发送 /jm 章节ID 获取章节图片\n💡 发送 /jm help 查看帮助"
                    )
                    return

                chapter_id = cursor["chapter_id"]
                images = cursor["images"]
                offset = cursor["offset"]
                logger.info(
                    f"[JMComic] Continue chapter id={chapter_id} offset={offset} "
                    f"for user {user_name}"
                )
                response_items, next_offset = await self._format_jm_chapter(
                    event, images, offset=offset
                )
                for item in response_items:
                    yield item

                if next_offset < len(images):
                    self._set_jm_chapter_cursor(event, chapter_id, images, next_offset)
                else:
                    # 已是最后一段：清除游标
                    self._clear_jm_chapter_cursor(event)

            else:
                yield event.plain_result(
                    "❌ 未知子命令\n💡 可用命令：search(搜索) / detail(详情) / chapter(章节) / con(续看)\n💡 发送 /jm help 查看帮助"
                )

        except JMComicAPIError as e:
            logger.error(f"[JMComic] API error for user {user_name}: {e}")
            error_msg = f"❌ JMComic 请求失败\n📝 错误信息：{str(e)}"
            if e.status_code:
                error_msg += f"\n🔢 状态码：{e.status_code}"
            error_msg += "\n💡 请稍后重试或发送 /jm help 查看帮助"
            yield event.plain_result(error_msg)
        except Exception as e:
            logger.error(
                f"[JMComic] Unexpected error for user {user_name}: {e}", exc_info=True
            )
            yield event.plain_result(
                f"❌ 发生未知错误\n📝 错误信息：{str(e)}\n💡 请稍后重试"
            )

    def _parse_jm_params(self, message: str) -> tuple:
        """解析 /jm 命令参数，返回 (action, params)"""
        cleaned = re.sub(
            r"^[/!！]\s*(jm|漫画)\s*", "", message.strip(), flags=re.IGNORECASE
        )
        cleaned = re.sub(r"^(jm|漫画)\s*", "", cleaned.strip(), flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        if not cleaned or cleaned.lower() in ("help", "-h", "--help", "帮助"):
            return ("help", {})

        # 裸 ID 简化：/jm 413828 直接当作取章节图片（与旧写法 /jm chapter 413828 等效）
        # JM 的章节/漫画 ID 均为纯数字，关键词搜索不会是纯数字，故无歧义。
        if re.fullmatch(r"\d+", cleaned):
            return ("chapter", {"id": cleaned})

        # 解析子命令
        parts = cleaned.split(None, 1)
        action = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        # 中文子命令别名映射
        action_alias = {
            "搜索": "search",
            "详情": "detail",
            "章节": "chapter",
            "con": "continue",
            "续": "continue",
            "继续": "continue",
        }
        action = action_alias.get(action, action)

        if action == "continue":
            # /jm con（别名：续 / 继续）—— 续看上一章节剩余图片
            return ("continue", {})

        if action == "search":
            # 解析 page 参数
            page = 1
            page_match = re.search(r"page\s*[:：]\s*(\d+)", rest, re.IGNORECASE)
            if page_match:
                page = max(1, int(page_match.group(1)))
                rest = rest[: page_match.start()] + rest[page_match.end() :]

            query = rest.strip()
            return ("search", {"query": query, "page": page})

        elif action == "detail":
            comic_id = rest.strip()
            return ("detail", {"id": comic_id})

        elif action == "chapter":
            chapter_id = rest.strip()
            return ("chapter", {"id": chapter_id})

        else:
            # 如果第一个词不是已知子命令，当作搜索处理
            return ("search", {"query": cleaned, "page": 1})

    def _get_jm_session_key(self, event: AstrMessageEvent) -> str:
        """获取章节续看游标的会话 key（区分群/私聊）。"""
        return getattr(event, "session_id", "") or event.get_session_id()

    def _set_jm_chapter_cursor(
        self,
        event: AstrMessageEvent,
        chapter_id: str,
        images: List[Any],
        offset: int,
    ) -> None:
        """记录当前会话的章节续看游标（仅内存、带 TTL）。"""
        self._jm_chapter_cursor[self._get_jm_session_key(event)] = {
            "chapter_id": chapter_id,
            "images": images,
            "offset": offset,
            "ts": time.time(),
        }

    def _get_jm_chapter_cursor(self, event: AstrMessageEvent) -> Optional[dict]:
        """读取并校验当前会话的章节续看游标；过期返回 None。"""
        key = self._get_jm_session_key(event)
        cursor = self._jm_chapter_cursor.get(key)
        if not cursor:
            return None
        # 过期清理（章节 URL 有时效，避免续看过期链接）
        if time.time() - cursor.get("ts", 0) > _JM_CHAPTER_CURSOR_TTL:
            self._jm_chapter_cursor.pop(key, None)
            return None
        return cursor

    def _clear_jm_chapter_cursor(self, event: AstrMessageEvent) -> None:
        """清除当前会话的章节续看游标。"""
        self._jm_chapter_cursor.pop(self._get_jm_session_key(event), None)

    def _format_jm_search_results(
        self, data: Dict[str, Any], query: str, page: int
    ) -> str:
        """格式化搜索结果"""
        results = data.get("results", [])
        if not results:
            return f"😕 未找到与「{query}」相关的漫画\n💡 请尝试其他关键词"

        parts = [f"📚 搜索「{query}」结果（第{page}页）：\n"]
        for i, item in enumerate(results[:20], 1):
            comic_id = item.get("id", "")
            title = item.get("title", "未知")
            author = item.get("author", "N/A")
            category = item.get("category", {})
            cat_title = category.get("title", "") if isinstance(category, dict) else ""

            parts.append(f"  {i}. 【{comic_id}】{title}")
            info_parts = []
            if author and author != "N/A":
                info_parts.append(f"作者: {author}")
            if cat_title:
                info_parts.append(f"分类: {cat_title}")
            if info_parts:
                parts.append(f"     {' | '.join(info_parts)}")

        parts.append(f"\n💡 使用 /jm detail <漫画ID> 查看详情")
        if len(results) >= 20:
            parts.append(f"💡 使用 /jm search {query} page:{page + 1} 查看下一页")

        return "\n".join(parts)

    def _format_jm_detail(self, data: Dict[str, Any]) -> str:
        """格式化漫画详情"""
        if not data:
            return "⚠️ 未获取到漫画详情数据"

        title = data.get("title", "未知标题")
        author_raw = data.get("author", "未知作者")
        if isinstance(author_raw, list):
            author = " / ".join(author_raw) if author_raw else "未知作者"
        else:
            author = str(author_raw)
        description = data.get("description", "")
        tags = data.get("tags", [])
        comic_id = data.get("id", "")
        total_views = data.get("total_views", "")
        likes = data.get("likes", "")
        series = data.get("series", [])
        related_list = data.get("related_list", [])

        parts = [f"📖 漫画详情"]
        if comic_id:
            parts.append(f"🆔 ID：{comic_id}")
        parts.append(f"📕 标题：{title}")
        parts.append(f"👤 作者：{author}")

        if total_views:
            parts.append(f"👁️ 浏览：{total_views}")
        if likes:
            parts.append(f"❤️ 喜欢：{likes}")

        if description:
            desc_short = description[:200] + ("..." if len(description) > 200 else "")
            parts.append(f"📝 简介：{desc_short}")

        if tags:
            if isinstance(tags, list):
                tag_names = []
                for t in tags[:10]:
                    if isinstance(t, dict):
                        tag_names.append(t.get("name", str(t)))
                    else:
                        tag_names.append(str(t))
                parts.append(f"🏷️ 标签：{' / '.join(tag_names)}")

        if series and isinstance(series, list):
            parts.append(f"\n📑 系列（共{len(series)}部）：")
            for i, s in enumerate(series[:10], 1):
                if isinstance(s, dict):
                    s_id = s.get("id", "")
                    s_name = s.get("name", f"第{i}部")
                    parts.append(f"  {i}. 【{s_id}】{s_name}")
                else:
                    parts.append(f"  {i}. {s}")
            if len(series) > 10:
                parts.append(f"  ... 还有 {len(series) - 10} 部")

        parts.append(f"\n💡 使用 /jm chapter {comic_id} 获取章节图片")

        return "\n".join(parts)

    def _extract_jm_images(self, data: Dict[str, Any]) -> List[Any]:
        """从章节接口返回中提取图片列表，兼容多种字段名。"""
        if not isinstance(data, dict):
            return []
        images = data.get("images", [])
        if not images:
            for key in ("urls", "pages", "pics"):
                if key in data and isinstance(data[key], list):
                    images = data[key]
                    break
        return images or []

    @staticmethod
    def _extract_jm_image_url(img: Any) -> str:
        """从单张图片项中提取 URL（优先已解密的 decoded_url）。"""
        if isinstance(img, str):
            return img
        if isinstance(img, dict):
            return img.get("decoded_url", "") or img.get("url", "")
        return ""

    @staticmethod
    def _jm_image_extension(url: str) -> str:
        """从图片 URL 推断扩展名，默认 .jpg。"""
        url_no_query = url.lower().split("?", 1)[0]
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
            if url_no_query.endswith(ext):
                return ext
        return ".jpg"

    async def _download_jm_image_to_temp(
        self, url: str, idx: int, temp_dir: str
    ) -> Optional[str]:
        """下载单张章节图片到临时目录，失败返回 None。"""
        if not url:
            return None
        temp_path = None
        downloaded = False
        try:
            ext = self._jm_image_extension(url)
            request_id = uuid.uuid4().hex[:12]
            temp_path = os.path.join(temp_dir, f"jm_{idx + 1}_{request_id}{ext}")
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {"User-Agent": "AstrBot-JMComic-Plugin/1.0"}
            if self._leiz_api_key:
                # 图片地址可能经 LeiZ 代理，统一附 x-api-key；对裸 CDN 无副作用。
                headers["x-api-key"] = self._leiz_api_key
            async with aiohttp.ClientSession(
                timeout=timeout, headers=headers
            ) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"[JMComic] 下载图片失败: HTTP {resp.status} {url}"
                        )
                        return None
                    with open(temp_path, "wb") as img_file:
                        async for chunk in resp.content.iter_chunked(8192):
                            img_file.write(chunk)
                    downloaded = True
            return temp_path
        except Exception as e:
            logger.warning(f"[JMComic] 下载图片异常 [{type(e).__name__}]: {e}")
            return None
        finally:
            if temp_path and not downloaded:
                self._remove_file(temp_path)

    @staticmethod
    def _prepare_image_for_forward(path: str, max_bytes: int) -> str:
        """把章节图片转码为最适合 QQ 合并转发的形态。

        两件事：
        1. 统一转 JPEG —— QQ/QQNT 的合并转发节点对 webp 等格式兼容性差，
           实测会触发 retcode=1200（res_id 已下发但腾讯拒绝）。JPEG 最稳。
           仅当原图已是体积合规的 .jpg/.jpeg 时才直接复用，否则重编码。
        2. 体积超 max_bytes 时逐档降质（90→…→50）直至达标或到下限。

        损坏图片捕获异常并返回原路径，不阻断整批发送。
        返回最终要发送的图片路径（可能与入参不同）。
        """
        try:
            from PIL import Image
        except ImportError:
            logger.warning("[JMComic] 未安装 Pillow，跳过图片转码")
            return path

        try:
            size = os.path.getsize(path)
        except OSError:
            return path

        # 已是合规的 JPEG 且体积达标：直接复用，避免无谓重编码。
        lower = path.lower()
        if (lower.endswith(".jpg") or lower.endswith(".jpeg")) and size <= max_bytes:
            return path

        try:
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                # 输出到独立文件，避免与原 .jpg 同名覆盖（PIL 惰性加载期间
                # 直接覆盖源文件不安全）。成功后删除原文件，由调用方 track 新路径。
                base = os.path.splitext(path)[0]
                out_path = f"{base}_{uuid.uuid4().hex[:8]}.jpg"
                # 体积未超阈值：用固定高质量转码一次（纯格式转换，解决 webp）。
                if size <= max_bytes:
                    rgb.save(out_path, format="JPEG", quality=92, optimize=True)
                    _remove_file_safe(path)
                    return out_path
                # 体积超阈值：逐档降质直至达标。
                for quality in range(90, 45, -5):
                    rgb.save(out_path, format="JPEG", quality=quality, optimize=True)
                    if os.path.getsize(out_path) <= max_bytes:
                        _remove_file_safe(path)
                        return out_path
                # 全部档位仍未达标：保留最后（最低质量 q50）结果作为兜底，
                # 仍优于原图（已在循环里以 q50 写过一次）。
                if os.path.getsize(out_path) < size:
                    _remove_file_safe(path)
                    return out_path
                _remove_file_safe(out_path)
                return path
        except (OSError, ValueError) as e:
            logger.warning(f"[JMComic] 转码图片异常 [{type(e).__name__}]: {e}")
            return path

    async def _format_jm_chapter(
        self,
        event: AstrMessageEvent,
        images: List[Any],
        offset: int = 0,
    ) -> tuple:
        """下发章节图片的某一段（offset 起，共 page_size 张）。

        下载并按需压缩后，通过合并转发批量发送。返回 (results, next_offset)：
        next_offset < total 表示仍有剩余，调用方应保留游标供 /jm con 续看。
        """
        total = len(images)
        page_size = self._jm_page_size
        end = min(offset + page_size, total)
        segment = images[offset:end]

        temp_dir = os.path.join(tempfile.gettempdir(), "astrbot_jm")
        os.makedirs(temp_dir, exist_ok=True)

        nodes = []
        for i, img in enumerate(segment):
            global_idx = offset + i  # 全章节范围内的序号（1 基用于展示）
            img_url = self._extract_jm_image_url(img)
            if not img_url:
                continue
            local_path = await self._download_jm_image_to_temp(
                img_url, global_idx, temp_dir
            )
            if not local_path:
                continue
            final_path = self._prepare_image_for_forward(
                local_path, self._jm_image_max_bytes
            )
            # 临时图片交由框架在整条流水线发送完成后统一清理。
            # 不能在返回前删除：Comp.Image.fromFileSystem 是延迟读取的，
            # 实际读取（转 base64）发生在后续发送阶段 Node.to_dict() 中，
            # 提前删除会导致合并转发节点内图片为空。
            _track_jm_temp_file(event, final_path)
            node_content = [
                Comp.Plain(text=f"第{global_idx + 1}/{total}张"),
                Comp.Image.fromFileSystem(final_path),
            ]
            nodes.append(Comp.Node(content=node_content, name="JMComic", uin="0"))

        if not nodes:
            return (
                [event.plain_result("⚠️ 未能下载/解析本段章节图片")],
                offset,
            )

        # 仍有剩余：附「发送 /jm con 继续」提示节点
        if end < total:
            nodes.append(
                Comp.Node(
                    content=[
                        Comp.Plain(
                            text=(
                                f"本章共{total}张，已展示第{offset + 1}~{end}张，"
                                f"剩余{total - end}张。\n"
                                "发送 /jm con 继续查看后续图片。"
                            )
                        )
                    ],
                    name="JMComic",
                    uin="0",
                )
            )

        forward_msg = Comp.Nodes(nodes=nodes)
        header = f"🖼️ 章节图片（第{offset + 1}~{end}张 / 共{total}张）"
        results = [
            event.plain_result(header),
            event.chain_result([forward_msg]),
        ]
        return results, end

    @filter.command("jmcommend", alias={"漫画推荐"})
    async def jmcommend_command(self, event: AstrMessageEvent):
        """随机推荐一部 JMComic 漫画。"""
        user_name = event.get_sender_name()
        logger.debug(f"[JMComic] 随机推荐请求 from {user_name}")

        if self._is_help_command(event.message_str.strip()):
            yield event.plain_result(
                "📚 JMComic 随机推荐\n\n"
                "📌 用法：/jmcommend（别名：/漫画推荐）\n"
                "📌 功能：随机推荐一部漫画作品\n\n"
                "💡 返回漫画的标题、作者、分类等信息\n"
                "💡 使用 /jm detail <ID>（或 /漫画 详情 <ID>）可查看详情"
            )
            return

        if not self._jmcomic_client:
            logger.warning(f"[JMComic] API client not initialized for user {user_name}")
            yield event.plain_result(_format_api_key_not_configured("JMComic 漫画"))
            return

        try:
            # 使用随机关键词搜索来获取随机漫画
            random_keywords = [
                "原神",
                "少女",
                "恋爱",
                "校园",
                "冒险",
                "魔法",
                "日常",
                "百合",
                "奇幻",
                "都市",
                "青春",
                "甜蜜",
                "治愈",
                "热血",
                "悬疑",
            ]
            keyword = random.choice(random_keywords)
            page = random.randint(1, 3)

            logger.info(f"[JMComic] Random recommend: keyword={keyword}, page={page}")
            data = await self._jmcomic_client.search(keyword, page)

            results = data.get("results", [])
            if not results:
                # 如果没结果，用默认关键词重试
                data = await self._jmcomic_client.search("漫画", 1)
                results = data.get("results", [])

            if not results:
                yield event.plain_result("😕 暂时无法获取推荐，请稍后再试")
                return

            # 随机选一部
            comic = random.choice(results)
            comic_id = comic.get("id", "")
            title = comic.get("title", "未知标题")
            author = comic.get("author", "未知作者")
            category = comic.get("category", {})
            cat_title = (
                category.get("title", "未知分类")
                if isinstance(category, dict)
                else "未知分类"
            )
            tags = comic.get("tags", [])

            parts = [
                "📚 随机漫画推荐",
                "",
                f"📕 标题：{title}",
                f"👤 作者：{author}",
                f"📂 分类：{cat_title}",
                f"🆔 ID：{comic_id}",
            ]

            if tags and isinstance(tags, list):
                tag_names = [
                    t.get("name", str(t)) if isinstance(t, dict) else str(t)
                    for t in tags[:8]
                ]
                if tag_names:
                    parts.append(f"🏷️ 标签：{' / '.join(tag_names)}")

            parts.append("")
            parts.append(f"💡 使用 /jm detail {comic_id} 查看详情")
            parts.append(f"💡 使用 /jm chapter {comic_id} 查看图片")

            yield event.plain_result("\n".join(parts))

        except JMComicAPIError as e:
            logger.error(f"[JMComic] Recommend API error: {e}")
            error_msg = f"❌ 获取推荐失败\n📝 错误信息：{str(e)}"
            if e.status_code:
                error_msg += f"\n🔢 状态码：{e.status_code}"
            error_msg += "\n💡 请稍后重试"
            yield event.plain_result(error_msg)
        except Exception as e:
            logger.error(f"[JMComic] Recommend unexpected error: {e}", exc_info=True)
            yield event.plain_result(
                f"❌ 发生未知错误\n📝 错误信息：{str(e)}\n💡 请稍后重试"
            )

    @filter.command("解析")
    async def media_parse_command(self, event: AstrMessageEvent):
        """自动解析小红书、B站和抖音媒体链接。"""
        user_name = event.get_sender_name()
        message_str = event.message_str.strip()
        if self._is_help_command(message_str):
            yield event.plain_result(MEDIA_PARSER_HELP_TEXT)
            return
        url = self._parse_media_url(message_str)
        if not url:
            yield event.plain_result("请提供有效的媒体链接")
            return
        try:
            result = await self._media_parser.parse(url)
            platform = result.get("platform", "")
            data = result.get("data", {})
            response_items = self._format_media_response(platform, data, event)
            for item in response_items:
                yield item
        except MediaParserError as e:
            yield event.plain_result(f"解析失败: {str(e)}")
        except Exception as e:
            yield event.plain_result(f"发生未知错误: {str(e)}")

    @filter.command("xhs", alias={"小红书"})
    async def xhs_parse_command(self, event: AstrMessageEvent):
        """解析小红书链接中的媒体内容。"""
        message_str = event.message_str.strip()
        if self._is_help_command(message_str):
            yield event.plain_result("小红书解析: /xhs <链接>")
            return
        url = self._parse_media_url(message_str)
        if not url or not URLExtractor.extract_xiaohongshu(url):
            yield event.plain_result("请提供有效的小红书链接")
            return
        try:
            data = await self._media_parser.xiaohongshu.parse(url)
            for item in self._format_xiaohongshu_response(data, event):
                yield item
        except Exception as e:
            yield event.plain_result(f"小红书解析失败: {str(e)}")

    @filter.command("bilibili", alias={"B站", "b站"})
    async def bilibili_parse_command(self, event: AstrMessageEvent):
        """解析 Bilibili 链接中的媒体内容。"""
        message_str = event.message_str.strip()
        if self._is_help_command(message_str):
            yield event.plain_result("B站解析: /bilibili <链接>")
            return
        url = self._parse_media_url(message_str)
        if not url or not URLExtractor.extract_bilibili(url):
            yield event.plain_result("请提供有效的B站链接")
            return
        try:
            data = await self._media_parser.bilibili.parse(url)
            for item in self._format_bilibili_response(data, event):
                yield item
        except Exception as e:
            yield event.plain_result(f"B站解析失败: {str(e)}")

    @filter.command("douyin", alias={"抖音"})
    async def douyin_parse_command(self, event: AstrMessageEvent):
        """解析抖音链接中的媒体内容。"""
        message_str = event.message_str.strip()
        if self._is_help_command(message_str):
            yield event.plain_result("抖音解析: /douyin <链接>")
            return
        url = self._parse_media_url(message_str)
        if not url or not URLExtractor.extract_douyin(url):
            yield event.plain_result("请提供有效的抖音链接")
            return
        try:
            data = await self._media_parser.douyin.parse(url)
            for item in self._format_douyin_response(data, event):
                yield item
        except Exception as e:
            yield event.plain_result(f"抖音解析失败: {str(e)}")

    def _parse_media_url(self, message: str) -> Optional[str]:
        cleaned = re.sub(
            r"^[/!！]\s*(解析|xhs|小红书|bilibili|B站|b站|douyin|抖音)\s*",
            "",
            message.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(解析|xhs|小红书|bilibili|B站|b站|douyin|抖音)\s*",
            "",
            cleaned.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = cleaned.strip()
        if not cleaned or cleaned.lower() in ("help", "-h", "--help", "帮助"):
            return None
        url_pattern = re.compile(r"https?://[^\s]+")
        match = url_pattern.search(cleaned)
        if match:
            return match.group(0)
        if (
            cleaned.startswith("xhslink.com/")
            or cleaned.startswith("b23.tv/")
            or cleaned.startswith("v.douyin.com/")
        ):
            return f"https://{cleaned}"
        return None

    def _format_media_response(
        self, platform: str, data: Dict[str, Any], event: AstrMessageEvent
    ) -> List[Any]:
        if platform == "xiaohongshu":
            return self._format_xiaohongshu_response(data, event)
        elif platform == "bilibili":
            return self._format_bilibili_response(data, event)
        elif platform == "douyin":
            return self._format_douyin_response(data, event)
        return [event.plain_result("未知平台")]

    def _format_xiaohongshu_response(
        self, data: Dict[str, Any], event: AstrMessageEvent
    ) -> List[Any]:
        title = data.get("title", "")
        desc = data.get("desc", "")
        author = data.get("author", "")
        likes = data.get("likes", "")
        images = data.get("images", [])
        video = data.get("video")
        url = data.get("url", "")
        parts = ["📕 小红书笔记解析"]
        if title:
            parts.append(f"📝 标题：{title}")
        if author:
            parts.append(f"👤 作者：{author}")
        if likes:
            parts.append(f"❤️ 点赞：{likes}")
        if desc:
            parts.append(f"📄 简介：{desc[:200]}")
        if url:
            parts.append(f"🔗 链接：{url}")
        results = [event.plain_result("\n".join(parts))]
        if images:
            for i, img in enumerate(images[:9]):
                img_url = img.get("url", "") if isinstance(img, dict) else str(img)
                if img_url:
                    results.append(event.image_result(img_url))
        if video and isinstance(video, dict) and video.get("url"):
            results.append(event.plain_result(f"🎬 视频：{video['url']}"))
        return results

    def _format_bilibili_response(
        self, data: Dict[str, Any], event: AstrMessageEvent
    ) -> List[Any]:
        title = data.get("title", "")
        desc = data.get("desc", "")
        cover = data.get("cover", "")
        duration = data.get("duration", 0)
        link = data.get("link", "")
        owner = data.get("owner", {})
        stat = data.get("stat", {})
        download_url = data.get("download_url")
        pages = data.get("pages", [])
        owner_name = owner.get("name", "") if isinstance(owner, dict) else ""
        parts = ["📺 B站视频解析"]
        if title:
            parts.append(f"📝 标题：{title}")
        if owner_name:
            parts.append(f"👤 UP主：{owner_name}")
        if duration:
            mins, secs = divmod(duration, 60)
            parts.append(f"⏱️ 时长：{mins}:{secs:02d}")
        if pages and len(pages) > 1:
            parts.append(f"📑 分P：共{len(pages)}P")
        stat_parts = []
        view = stat.get("view", 0) if isinstance(stat, dict) else 0
        like = stat.get("like", 0) if isinstance(stat, dict) else 0
        if view:
            stat_parts.append(f"▶️ {self._format_number(view)}")
        if like:
            stat_parts.append(f"👍 {self._format_number(like)}")
        if stat_parts:
            parts.append(" ".join(stat_parts))
        if desc:
            parts.append(f"📄 简介：{desc[:200]}")
        if link:
            parts.append(f"🔗 链接：{link}")
        if download_url:
            parts.append(f"📥 下载：{download_url}")
        results = [event.plain_result("\n".join(parts))]
        if cover:
            results.append(event.image_result(cover))
        return results

    def _format_douyin_response(
        self, data: Dict[str, Any], event: AstrMessageEvent
    ) -> List[Any]:
        title = data.get("title", "")
        desc = data.get("desc", "")
        author = data.get("author", "")
        likes = data.get("likes", "")
        comments = data.get("comments", "")
        shares = data.get("shares", "")
        cover = data.get("cover", "")
        video_url = data.get("video_url", "")
        url = data.get("url", "")
        parts = ["🎵 抖音视频解析"]
        if title:
            parts.append(f"📝 标题：{title}")
        if author:
            parts.append(f"👤 作者：{author}")
        stat_parts = []
        if likes:
            stat_parts.append(f"❤️ {likes}")
        if comments:
            stat_parts.append(f"💬 {comments}")
        if shares:
            stat_parts.append(f"🔄 {shares}")
        if stat_parts:
            parts.append(" ".join(stat_parts))
        if desc:
            parts.append(f"📄 简介：{desc[:200]}")
        if url:
            parts.append(f"🔗 链接：{url}")
        if video_url:
            parts.append(f"📥 无水印视频：{video_url}")
        results = [event.plain_result("\n".join(parts))]
        if cover:
            results.append(event.image_result(cover))
        return results

    @staticmethod
    def _format_number(num: int) -> str:
        if num >= 10000:
            return f"{num / 10000:.1f}万"
        return str(num)

    async def terminate(self):
        logger.info("CurrentCortexPlugin is being terminated")
        if hasattr(self, "_dglab_webui") and self._dglab_webui:
            await self._dglab_webui.stop()
            logger.info("✅ CurrentCortex WebUI 已停止")
        if hasattr(self, "_connection_pool"):
            await self._connection_pool.stop()
            logger.info("✅ CurrentCortex 连接池已停止")

    @filter.command("dglab", alias={"电击"})
    async def dglab_command(self, event: AstrMessageEvent):
        """管理、绑定和控制 DG-LAB 设备。"""
        if not getattr(self, "_pool_started", False):
            await self._connection_pool.start()
            if self._dglab_webui:
                await self._dglab_webui.start()
            self._pool_started = True

        message_str = event.message_str.strip()

        try:
            async for result in self._dglab_handler.handle_command(event, message_str):
                yield result
        except Exception as e:
            logger.error(f"[DGLab] 命令处理异常: {e}", exc_info=True)
            yield event.plain_result(
                f"❌ CurrentCortex 命令执行失败\n"
                f"📝 错误: {str(e)}\n"
                f"💡 发送 /dglab help 查看帮助"
            )

    @filter.command("apitest", alias={"连通测试", "接口测试"})
    async def apitest_command(self, event: AstrMessageEvent):
        """诊断 LeiZ API 上游接口的鉴权与连通状态。"""
        message_str = event.message_str.strip()

        if self._is_help_command(message_str):
            yield event.plain_result(API_TEST_HELP_TEXT)
            return

        # 未配置统一 API Key：6 个客户端均为 None，无法做任何探测
        if not self._leiz_api_key:
            yield event.plain_result(_format_api_key_not_configured("接口连通性测试"))
            return

        yield event.plain_result("🔍 正在并行探测 LeiZ 接口，请稍候…")

        # (显示名, 客户端实例, 最轻量只读调用)
        # 注意：必须用每个客户端最省流量的只读请求，避免下载图片/音频
        targets = [
            (
                "Pixiv",
                self._api_client,
                lambda c: c.fetch_images(num=1, size="regular"),
            ),
            ("一言", self._hitokoto_client, lambda c: c.fetch_hitokoto()),
            ("天气", self._weather_client, lambda c: c.fetch_weather("北京")),
            ("男娘", self._femboy_client, lambda c: c.fetch_femboy_image()),
            ("点歌", self._netease_client, lambda c: c.search_songs("在你的身边")),
            ("酷狗", self._kugou_client, lambda c: c.search_songs("在你的身边")),
            ("JMComic", self._jmcomic_client, lambda c: c.search("姐姐")),
        ]

        async def _probe(name, client, call):
            """单接口探测。返回 (name, status, elapsed, extra)。

            status: ok / http_err / net_err / skipped
            extra: 正常为 None，异常为状态码或简短错误
            """
            if client is None:  # 兜底：理论上已被 _leiz_api_key 判定拦截
                return (name, "skipped", 0.0, None)

            start = time.time()
            try:
                await call(client)
                elapsed = time.time() - start
                return (name, "ok", elapsed, None)
            except Exception as e:  # 捕获对应 *APIError（均带 status_code）
                elapsed = time.time() - start
                code = getattr(e, "status_code", 0)
                if code:  # 非 0 = HTTP 状态码（401/402/5xx 等）
                    return (name, "http_err", elapsed, f"HTTP {code}")
                # 0 = 超时 / 网络错误
                msg = str(e).strip().replace("\n", " ")
                return (
                    name,
                    "net_err",
                    elapsed,
                    (msg[:40] + "…") if len(msg) > 40 else msg,
                )

        overall_start = time.time()
        # 并行探测，避免串行最坏 6 × timeout
        results = await asyncio.gather(*[_probe(n, c, f) for n, c, f in targets])
        overall_elapsed = time.time() - overall_start

        # 组装输出
        status_icon = {
            "ok": "🟢",
            "http_err": "🟡",
            "net_err": "🔴",
            "skipped": "⚫",
        }
        lines = ["🔍 LeiZ API 接口连通性测试", "━━━━━━━━━━━━━━━━━━━━"]
        lines.append(f"配置超时: {self._request_timeout}s | 接口数: {len(targets)}")
        lines.append("")

        ok_count = 0
        for name, status, elapsed, extra in results:
            icon = status_icon.get(status, "❓")
            line = f"{icon} {name:<8} {elapsed:.2f}s"
            if extra:
                line += f"  {extra}"
            lines.append(line)
            if status == "ok":
                ok_count += 1

        abnormal = len(targets) - ok_count
        lines.append("")
        lines.append(
            f"📊 汇总: {ok_count}/{len(targets)} 正常 · {abnormal} 异常 · "
            f"总耗时 {overall_elapsed:.2f}s"
        )

        if abnormal:
            lines.append("💡 红色为超时/网络问题，黄色为 HTTP 错误（如 401 鉴权失败）")

        yield event.plain_result("\n".join(lines))
