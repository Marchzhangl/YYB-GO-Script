#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
加多宝Club小程序动态 code 版 (YYB_SERVER 适配版)

功能：
  1. 通过 YYB_SERVER 取码服务获取微信 code
  2. /loginsession/2weichatmicroprogram 使用 jscode 换 token
  3. /nanoprogramauth 使用 jscode 换 apitoken
  4. 手机号验证 + 会员注册（签到前必须完成）
  5. 每日签到
  6. 每日任务（分享小程序、浏览商城）
  7. 宝藏星期五抽奖
  8. 查询积分/阅历
  9. 自动适配青龙通知渠道（SendNotify / QYWX_KEY）
  10. 品赞代理，业务请求优先代理，失败直连兜底

环境变量：
  YYB_SERVER        取码服务地址，多账号每行一个，格式：地址@微信账号标识
  PLUSPLUS_TOKEN    PushPlus token，可选
  PROXY_API         品赞代理提取 API，可选
  PROXY_TYPE        http / socks5，默认 http

依赖：
  pip install requests
  socks5 代理需：
  pip install requests[socks]
"""

# === YYB_SERVER 统一通知注入 begin ===
import os as __os, sys as __sys, io as __io, atexit as __atexit, re as __re
_yyh_logs = []
class __LogHook(__io.TextIOBase):
    def __init__(self, s): self._s = s
    def write(self, s):
        if s and s != '\n': _yyh_logs.append(s.rstrip('\n'))
        self._s.write(s); return len(s)
    def flush(self): self._s.flush()
    def isatty(self): return self._s.isatty()
if not isinstance(__sys.stdout, __LogHook): __sys.stdout = __LogHook(__sys.stdout)
if not isinstance(__sys.stderr, __LogHook): __sys.stderr = __LogHook(__sys.stderr)

__pushed = False
def __push():
    global __pushed
    if __pushed: return
    try:
        body = '\n'.join(_yyh_logs[-40:])
        title = __os.path.basename(__sys.argv[0]) if __sys.argv else 'YYB_SERVER'
        sn = None
        try:
            from sendNotify import sendNotify as _sn
            sn = _sn
        except Exception:
            sn = None
        if sn and callable(sn):
            try: sn(title, body); return
            except Exception: pass
        key = __resolve_key()
        if key:
            import json as __json, urllib.request as __ur
            data = __json.dumps({'msgtype':'text','text':{'content':f'【{title}】\n{body}'}}).encode('utf-8')
            req = __ur.Request(f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}', data=data, headers={'Content-Type':'application/json'})
            __ur.urlopen(req, timeout=15)
    except Exception:
        pass
    __pushed = True

def __resolve_key():
    k = __os.environ.get('QYWX_KEY') or __os.environ.get('QYWX') or __os.environ.get('WEWORK_KEY')
    if k: return k
    for cand in ('sendNotify.js', '/ql/data/scripts/sendNotify.js'):
        try:
            t = open(cand, encoding='utf-8').read()
            m = __re.search(r"QYWX_KEY\s*=\s*'([^']+)'", t)
            if not m:
                m = __re.search(r'QYWX_KEY\s*=\s*"([^"]+)"', t)
            if m: return m.group(1)
        except Exception:
            pass
    return None

__orig_os_exit = __os._exit
def __patched_os_exit(code=0):
    global __pushed
    if __pushed:
        return __orig_os_exit(code)
    __pushed = True
    try: __push()
    except Exception: pass
    return __orig_os_exit(code)
try: __os._exit = __patched_os_exit
except Exception: pass

__atexit.register(__push)
# === YYB_SERVER 统一通知注入 end ===

import json
import os
import random
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import requests


APP_NAME = "加多宝Club小程序"
APPID = "wx8371875e443e177f"
CLIENT_CODE = "CLI2113448692"

# ===================== YYB_SERVER 取码服务配置 =====================
# 多账号格式（每行一个）：地址@微信账号标识，例如 192.168.1.21:8088@wx_jdb_01
# 脚本自动按行解析，逐个账号取码执行任务
SERVERS = []
YYB_SERVER_RAW = os.getenv("YYB_SERVER", "").strip()
if YYB_SERVER_RAW:
    SERVERS = [line.strip() for line in YYB_SERVER_RAW.splitlines() if line.strip()]
else:
    # 默认本地兜底（兼容旧版单端口配置）
    SERVERS = ["127.0.0.1:8088"]

# ==================== 功能开关 ====================
ENABLE_LOTTERY = True    # 【抽奖开关】True = 开启抽奖，False = 关闭抽奖
# ==================== 功能开关 ====================

PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()

PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
PROXY_FETCH_INTERVAL = 3
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 30

BASE_URL = "https://api-mp.jdbchina.com"

LOGIN_URL = f"{BASE_URL}/geement.authjextra/api/v1/loginsession/2weichatmicroprogram"
NANOPROGRAM_AUTH_URL = f"{BASE_URL}/geement.authjextra/api/v1/common/nanoprogramauth"
GET_PHONE_URL = f"{BASE_URL}/geement.authjextra/api/v1/loginsession/2weichatmicroprogram/getuserphonenumberwithcheckid"
REGISTER_MEMBER_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/informationvbyfiled"
USER_INFO_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/information"

SIGNIN_LIST_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin?status=30&pageNum=1&pageSize=1"
SIGNIN_USERINFO_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/userinfo"
SIGNIN_DO_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/signbyuser"
SIGNIN_USERLOGS_URL = f"{BASE_URL}/geement.marketingplay/api/v1/signin/userlogs"

TASK_JOIN_URL = f"{BASE_URL}/geement.marketingplay/api/v1/task/join"

ACT_DETAIL_URL = f"{BASE_URL}/geement.actjextra/api/v1/act"
ACT_PRIZES_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/prizes"
ACT_CHECK_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/check"
ACT_LOTTERY_COUNT_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/lottery/data/todaycount"
ACT_LOTTERY_DO_URL = f"{BASE_URL}/geement.actjextra/api/v1/act/data/pu"

SENIORITY_URL = f"{BASE_URL}/geement.usercenter/api/v1/user/seniority"
POINT_URL = f"{BASE_URL}/thirty.jdb/api/member/point/expire"

SIGN_TASK_ID = "SIGN26062416004235"
SHARE_TASK_ID = "2508121123571"
BROWSE_TASK_ID = "2508121124311"
ACT_CODE = "ACT2508121127551"
SEN_CODE = "SEN2508111752581"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541923) XWEB/20089"
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def mask(value: Any) -> str:
    value = str(value or "")
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-6:]}"


def json_preview(data: Any, limit: int = 800) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)[:limit]
    except Exception:
        return str(data)[:limit]


def to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def log_title() -> None:
    print()
    print("+" + "=" * 50 + "+")
    print("| 加多宝Club小程序动态 code 版 (YYB_SERVER 适配版)  |")
    print(f"| 启动时间: {now_text():<38}|")
    print(f"| 账号数量: {len(SERVERS):<40}|")
    print("+" + "=" * 50 + "+")


def log_account_header(index: int, total: int, server: str) -> None:
    print()
    print("+" + "-" * 50 + "+")
    print(f"| 账号 {index} / {total:<41}|")
    print(f"| 来源 {server:<44}|")
    print("+" + "-" * 50 + "+")


def direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def parse_proxy_response(text: Any) -> Dict[str, Any] | None:
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)

    text = text.strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        proxy_obj = None

        if isinstance(data.get("data"), list) and data["data"]:
            proxy_obj = data["data"][0]
        elif isinstance(data.get("data"), dict):
            proxy_obj = data["data"]
        elif data.get("ip") and data.get("port"):
            proxy_obj = data
        elif isinstance(data.get("result"), dict):
            proxy_obj = data["result"]

        if proxy_obj:
            host = proxy_obj.get("ip") or proxy_obj.get("host")
            port = proxy_obj.get("port")
            if host and port:
                return {
                    "host": str(host),
                    "port": int(port),
                    "username": proxy_obj.get("user") or proxy_obj.get("username") or "",
                    "password": proxy_obj.get("pass") or proxy_obj.get("password") or "",
                }
    except Exception:
        pass

    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            return {
                "host": parts[0],
                "port": int(parts[1]),
                "username": parts[2] if len(parts) > 2 else "",
                "password": parts[3] if len(parts) > 3 else "",
            }

    return None


def build_proxy_dict(proxy_info: Dict[str, Any] | None) -> Dict[str, str] | None:
    if not proxy_info:
        return None

    host = proxy_info["host"]
    port = proxy_info["port"]
    username = proxy_info.get("username", "")
    password = proxy_info.get("password", "")

    auth = ""
    if username and password:
        auth = f"{quote(username)}:{quote(password)}@"

    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"

    print(f"  [代理] 生成 {scheme.upper()} 代理 {host}:{port}")

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def validate_proxy(proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    if not proxies:
        return False, ""

    try:
        response = requests.get(PROXY_VALIDATE_URL, proxies=proxies, timeout=15)
        if response.status_code == 200:
            try:
                ip = response.json().get("origin", "未知")
            except Exception:
                ip = "未知"
            print(f"  [代理] 验证通过，出口 IP: {ip}")
            return True, ip
    except Exception as exc:
        print(f"  [代理] 验证失败: {exc}")

    return False, ""


def get_valid_proxy(account_name: str) -> Tuple[Dict[str, str] | None, str]:
    if not PROXY_API:
        print(f"  [代理] {account_name} 未配置 PROXY_API，使用直连")
        return None, ""

    print(f"  [代理] {account_name} 正在获取品赞代理...")

    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)

            if not proxy_info:
                print(f"  [代理] 第 {index} 次代理解析失败")
                continue

            print(f"  [代理] 提取到 {proxy_info['host']}:{proxy_info['port']}")
            proxies = build_proxy_dict(proxy_info)

            ok, ip = validate_proxy(proxies)
            if ok:
                return proxies, ip

            print(f"  [代理] 第 {index} 次代理不可用")
        except Exception as exc:
            print(f"  [代理] 第 {index} 次获取代理异常: {exc}")

        if index < PROXY_RETRY_TIMES:
            sleep(2)

    print("  [代理] 获取失败，使用直连")
    return None, ""


def request_with_proxy(
    method: str,
    url: str,
    *,
    proxies: Dict[str, str] | None = None,
    server: str = "",
    **kwargs,
) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)

    if proxies:
        try:
            return requests.request(method, url, proxies=proxies, **kwargs)
        except Exception as exc:
            print(f"  [代理] {server} 代理请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("  [兜底] 切换直连重试")

    session = direct_session()
    return session.request(method, url, **kwargs)


def send_pushplus(title: str, content: str) -> None:
    if not PLUSPLUS_TOKEN:
        print("  [PushPlus] 未配置 PLUSPLUS_TOKEN，跳过推送")
        return

    try:
        requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PLUSPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "txt",
            },
            timeout=10,
        )
        print("  [PushPlus] 推送成功")
    except Exception as exc:
        print(f"  [PushPlus] 推送失败: {exc}")


def parse_yyb_go_entry(raw_value: str) -> Tuple[str | None, str | None]:
    """解析 YYB_SERVER 单条配置，格式：地址@微信账号标识

    返回 (server_host, ref)
    """
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None, None

    at = raw_value.rfind("@")
    if at == -1:
        # 兼容没有 @ 的旧地址，当作仅地址
        return raw_value, ""

    server = raw_value[:at].strip()
    ref = raw_value[at + 1:].strip()

    if server.startswith("http://"):
        server = server[7:]
    elif server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")

    if not server:
        return None, None
    return server, ref


def get_code(entry: str) -> str | None:
    """从 YYB_SERVER 取码服务获取微信 code

    entry 格式：地址@微信账号标识；若只有地址则兼容本地旧接口 /login
    """
    server, ref = parse_yyb_go_entry(entry)
    if not server:
        print("  [授权] 无效的 YYB_SERVER 配置")
        return None

    # 优先使用 YYB Go 统一取码接口
    if ref:
        url = f"http://{server}/wxapp/getCode"
        max_retry = 2
        for attempt in range(1, max_retry + 1):
            print(f"  [授权] 请求YYB Go取码: {url} (ref={ref})" + (f" (第{attempt}次重试)" if attempt > 1 else ""))
            try:
                response = direct_session().post(
                    url,
                    json={"ref": ref, "app_id": APPID},
                    timeout=20,
                    proxies={"http": None, "https": None},
                )
                data = response.json()
                code = data.get("data", {}).get("result", {}).get("code")
                if data.get("code") != 0 or not code:
                    print(f"  [授权] YYB Go 取码失败: {json_preview(data)}")
                    if attempt < max_retry:
                        sleep(2)
                        continue
                    return None
                print("  [授权] code 获取成功")
                return code
            except Exception as exc:
                print(f"  [授权] 取码异常: {exc}")
                if attempt < max_retry:
                    sleep(2)
                    continue
                return None
        return None

    # 兼容旧本地 /login 接口
    url = f"http://{server}/login"
    max_retry = 2
    for attempt in range(1, max_retry + 1):
        print(f"  [授权] 请求本地 code 服务: {url}" + (f" (第{attempt}次重试)" if attempt > 1 else ""))
        try:
            response = direct_session().get(
                url,
                params={"appId": APPID},
                timeout=20,
            )
            data = response.json()

            if data.get("err") != 0 or not data.get("code"):
                print(f"  [授权] code 获取失败: {json_preview(data)}")
                if attempt < max_retry:
                    sleep(2)
                    continue
                return None

            print("  [授权] code 获取成功")
            return data["code"]
        except Exception as exc:
            print(f"  [授权] code 获取异常: {exc}")
            if attempt < max_retry:
                sleep(2)
                continue
            return None
    return None


def common_headers(token: str | None = None, apitoken: str | None = None) -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "xweb_xhr": "1",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": f"https://servicewechat.com/{APPID}/45/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if token:
        headers["unique_identity"] = token
        headers["apitoken"] = apitoken or token
    return headers


def login_by_code(server: str, login_code: str, auth_code: str, proxies: Dict[str, str] | None) -> Tuple[str | None, str | None, Dict[str, Any] | None]:
    """使用两个独立的 jscode 换 token 和 apitoken

    微信 code 只能用一次，所以登录和 apitoken 需要两个不同的 code。
    返回 (unique_identity, apitoken, raw_login_data)
    """
    try:
        # Step 1: 用 login_code 登录获取 token(unique_identity)
        print("  [登录] 使用 jscode 换 token")

        response = request_with_proxy(
            "POST",
            LOGIN_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "*/*",
                "xweb_xhr": "1",
                "Referer": f"https://servicewechat.com/{APPID}/45/page-frame.html",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            data={
                "jscode": login_code,
                "app_id": APPID,
                "client_code": CLIENT_CODE,
            },
            proxies=proxies,
            server=server,
        )

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:800]}

        token = data.get("data", {}).get("token")
        if not token:
            print(f"  [登录] token 获取失败: {json_preview(data)}")
            return None, None, data

        print(f"  [登录] token(unique_identity) 获取成功: {mask(token)}")

        # Step 2: 用 auth_code 换 apitoken
        apitoken = None
        try:
            print("  [登录] 使用第二个 jscode 换 apitoken")
            auth_resp = request_with_proxy(
                "GET",
                NANOPROGRAM_AUTH_URL,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "*/*",
                    "xweb_xhr": "1",
                    "Referer": f"https://servicewechat.com/{APPID}/45/page-frame.html",
                },
                params={
                    "app_id": APPID,
                    "client_code": CLIENT_CODE,
                    "jscode": auth_code,
                },
                proxies=proxies,
                server=server,
            )
            auth_data = auth_resp.json()
            apitoken = auth_data.get("data")
            if apitoken:
                print(f"  [登录] apitoken 获取成功: {mask(apitoken)}")
            else:
                print(f"  [登录] apitoken 获取失败，将使用 token 作为替代: {json_preview(auth_data)}")
                apitoken = token
        except Exception as exc:
            print(f"  [登录] apitoken 获取异常: {exc}，将使用 token 作为替代")
            apitoken = token

        return token, apitoken, data

    except Exception as exc:
        print(f"  [登录] 请求异常: {exc}")
        return None, None, None


def api_get(server: str, url: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> Dict[str, Any]:
    response = request_with_proxy(
        "GET",
        url,
        headers=common_headers(token, apitoken),
        proxies=proxies,
        server=server,
    )
    try:
        return response.json()
    except Exception:
        return {
            "success": False,
            "msg": f"JSON解析失败: {response.text[:300]}",
        }


def api_post(server: str, url: str, token: str, apitoken: str, proxies: Dict[str, str] | None, payload: Dict[str, Any] | None = None, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    headers = common_headers(token, apitoken)
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        headers["Content-Type"] = "application/json"

    response = request_with_proxy(
        "POST",
        url,
        headers=headers,
        json=payload if payload is not None else None,
        data=data if data is not None else None,
        proxies=proxies,
        server=server,
    )
    try:
        return response.json()
    except Exception:
        return {
            "success": False,
            "msg": f"JSON解析失败: {response.text[:300]}",
        }


def check_and_register_member(server: str, token: str, apitoken: str, phone_code: str, proxies: Dict[str, str] | None) -> Tuple[bool, str]:
    """手机号验证 + 会员注册（签到前必须完成）

    流程：
    1. 先查询当前用户信息，判断是否已注册为会员
    2. 如果未注册，尝试使用第三个 code 进行手机号验证
    3. 手机验证成功后，调用 informationvbyfiled 注册会员
    4. 如果手机验证失败（code 服务不支持 getPhoneNumber 类型 code），跳过注册

    返回 (是否已注册为会员, 描述信息)
    """
    # Step 1: 查询用户信息
    info_resp = api_get(server, USER_INFO_URL, token, apitoken, proxies)
    if not info_resp.get("success"):
        return False, f"查询用户信息失败: {info_resp.get('msg', '未知错误')}"

    user_data = info_resp.get("data", {})
    member_info = user_data.get("extra_memberinfo", {})
    member_status = member_info.get("member_status", 0)
    phone = user_data.get("phone", "")

    if member_status == 1:
        member_id = ""
        memberdto = member_info.get("memberdto") or {}
        if memberdto:
            member_id = memberdto.get("m_id", "")
        print(f"  [会员] 已注册为会员 (ID: {member_id})")
        if phone:
            print(f"  [会员] 手机号: {mask(phone)}")
        return True, f"已注册为会员 (ID: {member_id})"

    print("  [会员] 尚未注册为会员，尝试手机验证+注册...")

    if not phone:
        print("  [会员] 用户无手机号，尝试通过 code 获取...")
    
    # Step 2: 尝试手机验证
    check_id = None
    phone_number = phone

    if phone_code:
        print("  [会员] 使用第三个 code 尝试获取手机号验证...")
        phone_resp = api_post(
            server,
            GET_PHONE_URL,
            token, apitoken, proxies,
            data={
                "code": phone_code,
                "app_id": APPID,
                "client_code": CLIENT_CODE,
            },
        )

        if phone_resp.get("success"):
            phone_data = phone_resp.get("data", {})
            check_id = phone_data.get("check_id")
            phone_number = phone_data.get("phone_number", phone)
            print(f"  [会员] 手机号验证成功，check_id: {mask(check_id) if check_id else '无'}")
        else:
            msg = phone_resp.get("msg", "")
            print(f"  [会员] 手机号验证失败: {msg[:80]}")
            print("  [会员] 注意: 本地 code 服务可能不支持 getPhoneNumber 类型 code")
    else:
        print("  [会员] 未获取手机验证 code，跳过手机验证")

    # Step 3: 尝试注册会员
    if check_id and phone_number:
        print("  [会员] 尝试注册会员...")
        reg_payload = {
            "custom_fields": [{"id": "phone", "field_valuestr": phone_number}],
            "register_member": True,
            "register_member_phonenumbercheckdto": {"system_checkid": check_id},
            "member_sourceinfo": {
                "source_key01": "jdbmember001",
                "source_key02": "加多宝小程序虚拟门店",
                "source_key03": "",
                "source_key04": "",
            },
        }
        reg_resp = api_post(
            server,
            REGISTER_MEMBER_URL,
            token, apitoken, proxies,
            payload=reg_payload,
        )

        if reg_resp.get("success"):
            reg_data = reg_resp.get("data", {})
            reg_result = reg_data.get("register_member_result") or {}
            new_member_id = reg_result.get("member_id", "")
            print(f"  [会员] 注册成功! 会员ID: {new_member_id}")
            return True, f"注册成功 (ID: {new_member_id})"
        else:
            msg = reg_resp.get("msg", "")
            print(f"  [会员] 注册失败: {msg}")
    else:
        if not check_id:
            print("  [会员] 缺少 check_id，无法完成注册")
            print("  [会员] 提示: 需要在微信小程序中手动授权手机号完成首次注册")

    return False, "未注册为会员（缺少手机号验证）"


def do_signin(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    """每日签到，返回签到结果描述（含奖励详情）"""
    # 先获取当前签到活动信息
    signin_list = api_get(server, SIGNIN_LIST_URL, token, apitoken, proxies)
    if not signin_list.get("success"):
        return f"获取签到活动失败: {signin_list.get('msg', '未知错误')}"

    signin_data = signin_list.get("data", [])
    if not signin_data:
        return "暂无进行中的签到活动"

    activity_id = signin_data[0].get("activitydto", {}).get("id", SIGN_TASK_ID)

    # 查看签到状态
    userinfo_url = f"{SIGNIN_USERINFO_URL}?task_id={activity_id}"
    userinfo = api_get(server, userinfo_url, token, apitoken, proxies)

    total_days = 0
    already_signed = False
    if userinfo.get("success"):
        ud = userinfo.get("data", {})
        total_days = ud.get("total_signindays", 0)
        continuity_days = ud.get("continuity_signindays", 0)
        latest_time = str(ud.get("latest_signin_time", ""))
        print(f"  [签到] 累计签到 {total_days} 天，连续 {continuity_days} 天")
        today_str = datetime.now().strftime("%Y-%m-%d")
        if latest_time.startswith(today_str):
            already_signed = True

    if already_signed:
        print("  [签到] 今日已经完成签到")
        _show_signin_rewards(server, token, apitoken, proxies, activity_id)
        return f"今日已签到 (累计{total_days}天)"

    # 执行签到
    resp = api_post(server, SIGNIN_DO_URL, token, apitoken, proxies, data={"task_id": activity_id})

    if resp.get("success"):
        print("  [签到] 签到成功!")
        sleep(1)
        _show_signin_rewards(server, token, apitoken, proxies, activity_id)
        # 更新签到天数
        userinfo2 = api_get(server, f"{SIGNIN_USERINFO_URL}?task_id={activity_id}", token, apitoken, proxies)
        if userinfo2.get("success"):
            total_days = userinfo2["data"].get("total_signindays", total_days + 1)
        return f"签到成功 (累计{total_days}天)"
    else:
        msg = resp.get("msg") or ""
        if "已完成签到" in msg or "已经签到" in msg:
            print("  [签到] 今日已经完成签到")
            _show_signin_rewards(server, token, apitoken, proxies, activity_id)
            return f"今日已签到 (累计{total_days}天)"
        print(f"  [签到] 签到失败: {msg}")
        return f"签到失败: {msg}"


def _show_signin_rewards(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None, activity_id: str) -> None:
    """查询签到日志并显示今日签到奖励详情"""
    logs_url = f"{SIGNIN_USERLOGS_URL}?task_id={activity_id}&pageNum=1&pageSize=7"
    logs_resp = api_get(server, logs_url, token, apitoken, proxies)
    if not logs_resp.get("success"):
        return
    today_str = datetime.now().strftime("%Y-%m-%d")
    for log in logs_resp.get("data", []):
        signin_date = str(log.get("signin_date", ""))
        if not signin_date.startswith(today_str):
            continue
        rc_str = log.get("reward_content", "")
        if not rc_str:
            continue
        try:
            rewards = json.loads(rc_str)
        except Exception:
            continue
        for reward in rewards:
            for detail in reward.get("rule_reward_details", []):
                name = detail.get("relationship_name", "未知")
                count = detail.get("reward_count", 0)
                print(f"  [签到] 获得奖励: {name} × {count}")


def do_task(server: str, task_id: str, task_name: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    """完成每日任务，返回结果描述"""
    join_url = f"{TASK_JOIN_URL}?task_id={task_id}"
    resp = api_get(server, join_url, token, apitoken, proxies)

    if resp.get("success") and resp.get("data") == "成功":
        print(f"  [任务] {task_name}完成")
        return f"{task_name}: 成功"
    elif "已参" in (resp.get("msg") or ""):
        print(f"  [任务] {task_name}今日已完成")
        return f"{task_name}: 今日已完成"
    else:
        msg = resp.get("data") or resp.get("msg") or "任务失败"
        print(f"  [任务] {task_name}: {msg}")
        return f"{task_name}: {msg}"


def do_lottery(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    """宝藏星期五抽奖，返回抽奖结果描述"""
    if not ENABLE_LOTTERY:
        return "抽奖已关闭"

    # 获取活动详情
    detail_url = f"{ACT_DETAIL_URL}?act_code={ACT_CODE}"
    detail_resp = api_get(server, detail_url, token, apitoken, proxies)

    act_name = ACT_CODE
    if detail_resp.get("success") and detail_resp.get("data"):
        actdto = detail_resp["data"][0].get("actdto", {}) if detail_resp["data"] else {}
        act_name = actdto.get("activity_name", ACT_CODE)
        print(f"  [抽奖] 活动: {act_name}")

    # 获取奖品列表
    prizes_url = f"{ACT_PRIZES_URL}?act_code={ACT_CODE}&is_enable=1"
    prizes_resp = api_get(server, prizes_url, token, apitoken, proxies)

    if prizes_resp.get("success") and prizes_resp.get("data"):
        print("  [抽奖] 奖品列表:")
        for prize in prizes_resp["data"]:
            if prize.get("prize_type") == 2:
                continue
            pl = prize.get("prize_level", "")
            pn = prize.get("prize_name", "")
            wr = float(prize.get("prize_win_rate", 0)) * 100
            pc = prize.get("prize_count", 0)
            gc = prize.get("granted_count", 0)
            left = pc - gc
            print(f"    {pl}: {pn} (中奖率{wr:.0f}%, 剩余{left})")

    # 检查活动状态
    check_url = f"{ACT_CHECK_URL}?act_code={ACT_CODE}"
    check_resp = api_get(server, check_url, token, apitoken, proxies)

    if not check_resp.get("success"):
        return f"抽奖活动检查失败: {check_resp.get('msg', '未知错误')}"

    check_data = check_resp.get("data", {})
    act_status = check_data.get("act_status_full", 0)
    lottery_stime = check_data.get("lottery_stime", "")
    lottery_etime = check_data.get("lottery_etime", "")
    if lottery_stime:
        print(f"  [抽奖] 抽奖时间: {lottery_stime} ~ {lottery_etime}")

    if act_status != 1 and act_status != 2:
        return f"活动「{act_name}」未在进行中 (状态: {act_status})"

    # 查询今日可抽奖次数
    count_url = f"{ACT_LOTTERY_COUNT_URL}?act_code={ACT_CODE}"
    count_resp = api_get(server, count_url, token, apitoken, proxies)
    today_count = 0

    if count_resp.get("success"):
        today_count = count_resp.get("data", 0)
        print(f"  [抽奖] 今日已抽奖 {today_count} 次")

    # 判断是否还有抽奖次数
    max_per_day = check_data.get("user_max_scan_count_perday", 1)
    remaining = max(0, max_per_day - today_count)

    if remaining <= 0:
        return f"「{act_name}」今日抽奖次数已用完 ({today_count}/{max_per_day})"

    print(f"  [抽奖] 今日可抽奖 {remaining} 次")

    prize_list: List[str] = []
    for draw_index in range(1, remaining + 1):
        wait_time = random.randint(2, 5)
        print(f"  [抽奖] 第 {draw_index} 次抽奖前等待 {wait_time}s")
        sleep(wait_time)

        # 执行抽奖
        resp = api_post(server, ACT_LOTTERY_DO_URL, token, apitoken, proxies, data={"act_code": ACT_CODE})

        if not resp.get("success"):
            msg = resp.get("msg") or "抽奖失败"
            prize_list.append(f"第{draw_index}次失败: {msg}")
            print(f"  [抽奖] {msg}")
            continue

        prize_data = resp.get("data")
        if isinstance(prize_data, dict):
            prize_name = prize_data.get("prize_name") or prize_data.get("prizeName") or "未知奖品"
            prize_level = prize_data.get("prize_level") or prize_data.get("prizeLevel") or ""
            prize_list.append(f"{prize_level} {prize_name}" if prize_level else prize_name)
            print(f"  [抽奖] 第 {draw_index} 次获得: {prize_level} {prize_name}" if prize_level else f"  [抽奖] 第 {draw_index} 次获得: {prize_name}")
        elif prize_data is True:
            prize_list.append(f"「{act_name}」参与成功")
            print(f"  [抽奖] 第 {draw_index} 次「{act_name}」参与成功")
        else:
            prize_list.append(str(prize_data))
            print(f"  [抽奖] 第 {draw_index} 次结果: {prize_data}")

    return "、".join(prize_list) if prize_list else "无抽奖机会"


def query_point(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    """查询积分，返回积分数值字符串"""
    resp = api_get(server, POINT_URL, token, apitoken, proxies)

    if resp.get("success"):
        point = resp.get("data", {}).get("point", 0)
        print(f"  [积分] 当前积分: {point}")
        return str(point)
    else:
        msg = resp.get("msg") or "查询失败"
        print(f"  [积分] {msg}")
        return msg


def query_seniority(server: str, token: str, apitoken: str, proxies: Dict[str, str] | None) -> str:
    """查询阅历(积分)，返回总阅历"""
    url = f"{SENIORITY_URL}?sencodes={SEN_CODE}"
    resp = api_get(server, url, token, apitoken, proxies)

    if resp.get("success"):
        data_list = resp.get("data", [])
        if data_list:
            total = data_list[0].get("total_count", 0)
            used = data_list[0].get("used_count", 0)
            print(f"  [阅历] 总计 {total}，已使用 {used}")
            return f"总{total}/用{used}"
        return "暂无阅历数据"
    else:
        msg = resp.get("msg") or "查询失败"
        print(f"  [阅历] {msg}")
        return msg


def run_account(index: int, total: int, entry: str) -> Dict[str, Any]:
    result = {
        "server": entry,
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "token": "-",
        "memberMsg": "-",
        "signMsg": "-",
        "taskShareMsg": "-",
        "taskBrowseMsg": "-",
        "lotteryMsg": "-",
        "point": "-",
        "seniority": "-",
        "error": "",
    }

    log_account_header(index, total, entry)

    server_host, ref = parse_yyb_go_entry(entry)
    if not server_host:
        result["error"] = "YYB_SERVER 配置格式错误，应为 地址@微信账号标识"
        return result

    proxies, proxy_ip = get_valid_proxy(entry)
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    sleep(PROXY_FETCH_INTERVAL)

    delay = random.randint(2, 6)
    print(f"  [延迟] 启动延迟 {delay}s")
    sleep(delay)

    # 获取登录 code（第1个）
    login_code = get_code(entry)
    if not login_code:
        result["error"] = "获取登录 code 失败"
        return result

    # 获取授权 code（第2个，用于 apitoken）
    sleep(1)
    auth_code = get_code(entry)
    if not auth_code:
        result["error"] = "获取授权 code 失败"
        return result

    # 获取手机验证 code（第3个，用于会员注册）
    sleep(1)
    phone_code = get_code(entry)
    if phone_code:
        print("  [授权] 手机验证 code 获取成功")
    else:
        print("  [授权] 手机验证 code 获取失败，将跳过手机验证")

    # 登录
    token, apitoken, raw_login = login_by_code(entry, login_code, auth_code, proxies)
    if not token:
        result["error"] = f"登录失败: {json_preview(raw_login)}"
        return result

    result["token"] = mask(token)

    try:
        # ★ 关键步骤：先注册会员，再签到
        # 会员注册必须在签到之前完成，否则签到奖励（阅历）不会发放
        member_ok, member_msg = check_and_register_member(entry, token, apitoken, phone_code, proxies)
        result["memberMsg"] = member_msg

        sleep(random.randint(1, 3))

        # 每日签到
        result["signMsg"] = do_signin(entry, token, apitoken, proxies)

        sleep(random.randint(1, 3))

        # 分享小程序任务
        result["taskShareMsg"] = do_task(entry, SHARE_TASK_ID, "分享小程序", token, apitoken, proxies)

        sleep(random.randint(1, 3))

        # 浏览商城任务
        result["taskBrowseMsg"] = do_task(entry, BROWSE_TASK_ID, "浏览商城", token, apitoken, proxies)

        sleep(random.randint(1, 3))

        # 抽奖
        result["lotteryMsg"] = do_lottery(entry, token, apitoken, proxies)

        sleep(random.randint(1, 3))

        # 查询积分
        result["point"] = query_point(entry, token, apitoken, proxies)

        # 查询阅历
        result["seniority"] = query_seniority(entry, token, apitoken, proxies)

        result["success"] = True
        return result

    except Exception as exc:
        result["error"] = traceback.format_exc().strip()
        print(f"  [账号] 执行失败: {exc}")
        return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    content = "加多宝Club四账号任务结果\n"
    content += "—" * 30 + "\n"
    content += f"总结：{success_count} 成功 / {fail_count} 失败\n"
    content += f"时间：{now_text()}\n"
    content += "—" * 30 + "\n"

    for idx, res in enumerate(results, 1):
        status_text = "成功" if res["success"] else "失败"

        content += f"\n账号 {idx}\n"
        content += f"  来源：{res['server']}\n"
        content += f"  代理：{res['proxyStatus']}\n"
        content += f"  出口IP：{res['proxyIp']}\n"
        content += f"  Token：{res['token']}\n"
        content += f"  会员：{res['memberMsg']}\n"
        content += f"  签到：{res['signMsg']}\n"
        content += f"  分享任务：{res['taskShareMsg']}\n"
        content += f"  浏览任务：{res['taskBrowseMsg']}\n"
        content += f"  抽奖：{res['lotteryMsg']}\n"
        content += f"  积分：{res['point']}\n"
        content += f"  阅历：{res['seniority']}\n"
        content += f"  结果：{status_text}\n"

        if not res["success"]:
            content += f"  原因：{res['error']}\n"

        content += "—" * 30 + "\n"

    return content


def main() -> None:
    if not SERVERS:
        print("❌ 错误：未读取到环境变量 YYB_SERVER 或无有效服务地址！")
        print("配置示例（青龙环境变量值，每行一个）：")
        print("127.0.0.1:8088@wx_jdb_01")
        print("192.168.1.21:8088@wx_jdb_02")
        exit(1)

    log_title()

    results: List[Dict[str, Any]] = []

    for index, entry in enumerate(SERVERS, 1):
        try:
            result = run_account(index, len(SERVERS), entry)
            results.append(result)
        except Exception as exc:
            print(f"  [主程序] {entry} 执行异常: {exc}")
            results.append({
                "server": entry,
                "success": False,
                "proxyStatus": "-",
                "proxyIp": "-",
                "token": "-",
                "memberMsg": "-",
                "signMsg": "-",
                "taskShareMsg": "-",
                "taskBrowseMsg": "-",
                "lotteryMsg": "-",
                "point": "-",
                "seniority": "-",
                "error": traceback.format_exc().strip(),
            })

        if index < len(SERVERS):
            print("  [间隔] 等待 2s 后处理下一个账号")
            sleep(2)

    success_count = sum(1 for item in results if item["success"])
    fail_count = len(results) - success_count

    print()
    print("+" + "=" * 50 + "+")
    print("| 加多宝Club任务执行完成                          |")
    print(f"| 成功: {success_count:<42}|")
    print(f"| 失败: {fail_count:<42}|")
    print(f"| 结束时间: {now_text():<35}|")
    print("+" + "=" * 50 + "+")

    send_pushplus("加多宝Club任务完成", build_notify(results))


if __name__ == "__main__":
    main()
