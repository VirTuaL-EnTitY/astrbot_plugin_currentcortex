"""Pages 中转服务器(一键部署)纯函数单元测试。

覆盖: .env 渲染、systemd 单元渲染、ufw status 解析、unit 检测。

运行方式: python3 test_relay_pages.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))


class MockLogger:
    def info(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _Stub:
    logger = MockLogger()


# stub astrbot.api / astrbot.api.web(_pages_api 顶层依赖)
astrbot = type(sys)("astrbot")
api = type(sys)("astrbot.api")
api.logger = MockLogger()
web = type(sys)("astrbot.api.web")
web.error_response = lambda *a, **k: None
web.json_response = lambda *a, **k: None
web.request = type("R", (), {"json": staticmethod(lambda **k: None)})()
astrbot.api = api
api.web = web
sys.modules.update({"astrbot": astrbot, "astrbot.api": api, "astrbot.api.web": web})

import _pages_api as P  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {('- ' + str(detail)) if detail else ''}")


def test_env_render():
    print("\n📄 .env 渲染")
    v3 = P._render_relay_env("v3")
    check("v3 端口 9999", "PORT=9999" in v3, v3)
    check("v3 心跳 60000", "HEARTBEAT_INTERVAL=60000" in v3)
    check("v3 波形参数", "DEFAULT_PUNISHMENT_TIME=1" in v3 and "DEFAULT_PUNISHMENT_DURATION=5" in v3)
    v4 = P._render_relay_env("v4")
    check("v4 端口 9998", "PORT=9998" in v4, v4)
    check("v4 心跳 30000", "HEARTBEAT_INTERVAL=30000" in v4)
    check("v4 无波形参数", "DEFAULT_PUNISHMENT" not in v4)
    check("公共项", "PREFIX=/" in v4 and "LOG_LEVEL=info" in v4)


def test_unit_render():
    print("\n⚙️ systemd 单元渲染")
    for v in ("v3", "v4"):
        unit = P._render_relay_unit(v)
        check(f"{v} 执行对应 server.ts", f"ExecStart={P.RELAY_BUN_PATH} run {v}-server.ts" in unit)
        check(f"{v} 工作目录", f"WorkingDirectory={P._relay_dir(v)}" in unit)
        check(f"{v} 自启与重启", "WantedBy=multi-user.target" in unit and "Restart=on-failure" in unit)
        check(f"{v} PATH 含 bun", "/root/.bun/bin" in unit)


def test_ufw_parse():
    print("\n🧱 ufw status 解析")
    sample = (
        "Status: active\n"
        "To                         Action      From\n"
        "--                         ------      ----\n"
        "22/tcp                     ALLOW IN    Anywhere\n"
        "9998/tcp                   ALLOW IN    Anywhere\n"
        "9998/tcp (v6)              ALLOW IN    Anywhere (v6)\n"
        "8080/tcp (PyMineCore)      ALLOW IN    Anywhere\n"
    )
    check("放行端口命中", P._parse_ufw_status(sample, 9998))
    check("带注释命中", P._parse_ufw_status(sample, 8080))
    check("未放行端口不命中", not P._parse_ufw_status(sample, 9999))
    check("头行不误判", not P._parse_ufw_status("Status: active\nTo Action From\n", 9999))
    check(
        "前缀防误判(999 不等于 9998)",
        not P._parse_ufw_status("999/tcp    ALLOW IN    Anywhere\n", 9998),
    )
    check("空输出不命中", not P._parse_ufw_status("", 9998))


def test_find_unit():
    print("\n🔎 unit 存在性检测")
    with tempfile.TemporaryDirectory() as td:
        old = P.RELAY_UNIT_DIR
        P.RELAY_UNIT_DIR = td
        try:
            check("无 unit", P._relay_find_unit("v3") == "")
            with open(os.path.join(td, "dglab-v4.service"), "w") as f:
                f.write(P._render_relay_unit("v4"))
            check("接管旧名 dglab-v4", P._relay_find_unit("v4") == "dglab-v4")
            with open(os.path.join(td, "dglab-relay-v4.service"), "w") as f:
                f.write(P._render_relay_unit("v4"))
            check("新名优先于旧名", P._relay_find_unit("v4") == "dglab-relay-v4")
            check("v3 不受影响", P._relay_find_unit("v3") == "")
        finally:
            P.RELAY_UNIT_DIR = old


def main():
    print("=" * 60)
    print("🧪 Pages 中转服务器一键部署 · 纯函数测试")
    print("=" * 60)
    test_env_render()
    test_unit_render()
    test_ufw_parse()
    test_find_unit()
    print("\n" + "=" * 60)
    print(f"📊 总计: {PASS}/{PASS + FAIL} 通过")
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
