#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# name: 顾家家居会员俱乐部
# cron: 0 10 * * *

"""
顾家小程序自动化脚本 (YYB_SERVER 适配版)

功能：
  1. 通过 YYB_SERVER 取码服务获取微信 code
  2. 使用 code 换取 token（两步登录）
  3. 查询用户信息
  4. 每日签到
  5. 每日社区互动（点赞/收藏）
  6. 自动适配青龙通知渠道（SendNotify / QYWX_KEY）
  7. 品赞代理，业务请求优先代理，失败直连兜底
  8. Token缓存机制

环境变量：
  YYB_SERVER        取码服务地址，多账号每行一个，格式：地址@微信账号标识
  PLUSPLUS_TOKEN    PushPlus token，可选
  PROXY_API         品赞代理提取 API，可选
  PROXY_TYPE        http / socks5，默认 http

依赖：
  pip install requests
"""

import hashlib
import json
import os
import random
import string
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Tuple

import requests


APP_NAME = "顾家小程序签到"
APPID = "wx0770280d160f09fe"
PAGE_VERSION = "286"
API_BASE = "https://mc.kukahome.com/club-server"
INTEGRAL_BASE = "https://mc.kukahome.com/integral-server"
BRAND_CODE = "K001"
SMALL_APPLICATION_ID = "667516"
SMALL_CRYPTO = "FH3yRrHG2RfexND8"
VERSION_NUMBER = "2.8.6"
TOKEN_CACHE_FILE = "gujiajiaju_token_cache.json"

# ===================== YYB_SERVER 取码服务配置 =====================
# 多账号格式（每行一个）：地址@微信账号标识，例如 192.168.1.21:8088@wx_gj_01
SERVERS = []
_YYB_SERVER_RAW = os.getenv("YYB_SERVER", "").strip()
if _YYB_SERVER_RAW:
    SERVERS = [line.strip() for line in _YYB_SERVER_RAW.splitlines() if line.strip()]
else:
    # 默认本地兜底（兼容旧版四端口配置）
    SERVERS = [
        "127.0.0.1:8088",
        "192.168.31.36:8088",
        "192.168.31.88:8088",
        "192.168.31.62:8088",
    ]

PLUSPLUS_TOKEN = os.getenv("PLUSPLUS_TOKEN", "")
PROXY_API = os.getenv("PROXY_API", "")
PROXY_TYPE = os.getenv("PROXY_TYPE", "http").lower()

PROXY_RETRY_TIMES = 3
PROXY_VALIDATE_URL = "http://httpbin.org/ip"
# PROXY_VALIDATE_TIMEOUT removed (now using inline timeout=15)
ENABLE_DIRECT_FALLBACK = True
REQUEST_TIMEOUT = 10
API_REQUEST_DELAY = 0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows "
    "WindowsWechat/WMPF"
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


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def md5(input_str: str) -> str:
    return hashlib.md5(input_str.encode()).hexdigest()


def is_object(val: Any) -> bool:
    return isinstance(val, dict)


def build_parameter_base(data: Dict[str, Any]) -> str | None:
    if not data:
        return None
    if not is_object(data):
        return None

    keys = sorted(data.keys(), key=lambda k: [ord(c) for c in k])

    pairs = []
    for key in keys:
        value = data[key]
        if value is None or value == "" or value == 0:
            continue
        if isinstance(value, list):
            continue
        if isinstance(value, dict):
            pairs.append(f"{key}={json.dumps(value, separators=(',', ':'))}")
            continue
        if isinstance(value, int) and value == 0:
            pairs.append(f"{key}=0")
            continue
        pairs.append(f"{key}={value}")

    return "&".join(pairs) if pairs else None


def build_parameter_sign(data: Dict[str, Any], timestamp: int) -> str:
    base = build_parameter_base(data)
    if not base:
        return ""

    salt = str(timestamp)[4:10]
    return md5(md5(base) + salt)


def read_token_cache() -> Dict[str, Any]:
    try:
        if not os.path.exists(TOKEN_CACHE_FILE):
            return {}
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def write_token_cache(cache: Dict[str, Any]) -> None:
    try:
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"❌ [缓存] 写入token缓存失败: {exc}")


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
            host = proxy_obj.get("ip") or proxy_obj.get("Ip") or proxy_obj.get("host")
            port = proxy_obj.get("port") or proxy_obj.get("Port")
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
        from urllib.parse import quote
        auth = f"{quote(username)}:{quote(password)}@"

    scheme = "socks5" if PROXY_TYPE == "socks5" else "http"
    proxy_url = f"{scheme}://{auth}{host}:{port}"

    print(f"🛠️ [代理] 生成 {scheme.upper()} 代理 {host}:{port}")

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
            print(f"✅ [代理] 验证通过，出口 IP: {ip}")
            return True, ip
    except Exception as exc:
        print(f"⚠️ [代理] 验证失败: {exc}")

    return False, ""


def get_valid_proxy(account_name: str) -> Tuple[Dict[str, str] | None, str]:
    if not PROXY_API:
        print(f"⚠️ [代理] {account_name} 未配置 PROXY_API，使用直连")
        return None, ""

    print(f"🌐 [代理] {account_name} 正在获取品赞代理...")

    for index in range(1, PROXY_RETRY_TIMES + 1):
        try:
            response = direct_session().get(PROXY_API, timeout=15)
            proxy_info = parse_proxy_response(response.text)

            if not proxy_info:
                print(f"⚠️ [代理] 第 {index} 次代理解析失败")
                continue

            print(f"✅ [代理] 提取到 {proxy_info['host']}:{proxy_info['port']}")
            proxies = build_proxy_dict(proxy_info)

            ok, ip = validate_proxy(proxies)
            if ok:
                return proxies, ip

            print(f"⚠️ [代理] 第 {index} 次代理不可用")
        except Exception as exc:
            print(f"⚠️ [代理] 第 {index} 次获取代理异常: {exc}")

        if index < PROXY_RETRY_TIMES:
            sleep(2)

    print("⚠️ [代理] 获取失败，使用直连")
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
            print(f"⚠️ [代理] {server} 代理请求失败: {exc}")
            if not ENABLE_DIRECT_FALLBACK:
                raise
            print("🔁 [兜底] 切换直连重试")

    session = direct_session()
    return session.request(method, url, **kwargs)




def parse_yyb_go_entry(raw_value: str) -> Tuple[str | None, str | None]:
    """解析 YYB_SERVER 单条配置，格式：地址@微信账号标识

    返回 (server_host, ref)
    """
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None, None

    at = raw_value.rfind("@")
    if at == -1:
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
        print(f"🔐 [授权] 请求YYB Go取码: {url} (ref={ref})")
        try:
            response = direct_session().post(
                url,
                json={"ref": ref, "app_id": APPID},
                timeout=20,
            )
            data = response.json()
            code = data.get("data", {}).get("result", {}).get("code")
            if data.get("code") != 0 or not code:
                print(f"❌ [授权] YYB Go 取码失败: {json_preview(data)}")
                return None
            print(f"✅ [授权] code 获取成功: {mask(code)}")
            return code
        except Exception as exc:
            print(f"❌ [授权] 取码异常: {exc}")
            return None

    # 兼容旧本地 /login 接口
    url = f"http://{server}/login"
    print(f"🔐 [授权] 请求本地 code 服务: {url}")

    try:
        response = direct_session().get(
            url,
            params={"appId": APPID},
            timeout=20,
        )
        data = response.json()

        if data.get("err") != 0 or not data.get("code"):
            print(f"❌ [授权] code 获取失败: {json_preview(data)}")
            return None

        code = data.get("code")
        print(f"✅ [授权] code 获取成功: {mask(code)}")
        return code

    except Exception as exc:
        print(f"❌ [授权] code 获取异常: {str(exc)}")
        return None


def run_account(index: int, total: int, entry: str) -> Dict[str, Any]:
    result = {
        "server": entry,
        "success": False,
        "proxyStatus": "未使用代理",
        "proxyIp": "-",
        "token": "-",
        "userInfo": "-",
        "signInStatus": "-",
        "communityStatus": "-",
        "error": "",
    }

    proxies, proxy_ip = get_valid_proxy(entry)
    result["proxyStatus"] = "使用专属代理" if proxies else "使用直连"
    result["proxyIp"] = proxy_ip or "-"

    print(f"\n{'='*50}")
    print(f"🌍 [账号 {index}/{total}] 来源: {entry}")

    code = get_code(entry)
    if not code:
        result["error"] = "获取 code 失败"
        return result

    tmp_token = ""
    access_token = ""
    member_id = ""
    user_info = {}

    try:
        identify_url = f"{API_BASE}/api/user/identify"
        identify_timestamp = int(time.time() * 1000)
        identify_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{identify_timestamp}").lower()

        identify_headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Customer": "",
            "brandCode": BRAND_CODE,
            "appid": SMALL_APPLICATION_ID,
            "sign": identify_sign,
            "timestamp": str(identify_timestamp),
            "versionNumber": VERSION_NUMBER,
        }

        identify_resp = request_with_proxy(
            "POST",
            identify_url,
            proxies=proxies,
            server=entry,
            headers=identify_headers,
            params={"code": code},
        )

        try:
            identify_data = identify_resp.json()
        except Exception:
            identify_data = {}

        print(f"🔍 [登录] identify响应: {json_preview(identify_data)}")

        if identify_data.get("code") != 0 or not identify_data.get("data"):
            result["error"] = f"identify失败: {identify_data.get('message', '未知错误')}"
            print(f"❌ [登录] {result['error']}")
            return result

        identify_result = identify_data.get("data", {})
        status = identify_result.get("status", 0)

        if status != 4:
            result["error"] = f"登录状态异常: status={status}"
            print(f"❌ [登录] {result['error']}")
            return result

        tmp_token = identify_result.get("token", "")
        if not tmp_token:
            result["error"] = "identify未返回tmpToken"
            print(f"❌ [登录] {result['error']}")
            return result

        print(f"✅ [登录] identify成功: tmpToken={mask(tmp_token)}")

        sleep(API_REQUEST_DELAY)

        authorize_url = f"{API_BASE}/api/user/authorizeLogin"
        authorize_timestamp = int(time.time() * 1000)
        authorize_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{authorize_timestamp}").lower()

        authorize_headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Customer": "",
            "brandCode": BRAND_CODE,
            "appid": SMALL_APPLICATION_ID,
            "sign": authorize_sign,
            "timestamp": str(authorize_timestamp),
            "versionNumber": VERSION_NUMBER,
            "tmpToken": tmp_token,
        }

        authorize_body = {
            "source": "顾家小程序",
            "contentName": "",
        }

        parameter_sign = build_parameter_sign(authorize_body, authorize_timestamp)
        if parameter_sign:
            authorize_headers["parameterSign"] = parameter_sign

        authorize_resp = request_with_proxy(
            "POST",
            authorize_url,
            proxies=proxies,
            server=entry,
            headers=authorize_headers,
            json=authorize_body,
        )

        try:
            authorize_data = authorize_resp.json()
        except Exception:
            authorize_data = {}

        print(f"🔍 [登录] authorizeLogin响应: {json_preview(authorize_data)}")

        if authorize_data.get("code") != 0 or not authorize_data.get("data"):
            result["error"] = f"authorizeLogin失败: {authorize_data.get('message', '未知错误')}"
            print(f"❌ [登录] {result['error']}")
            return result

        authorize_result = authorize_data.get("data", {})
        access_token = authorize_result.get("token", "")
        member_id = str(authorize_result.get("memberId", ""))

        if not access_token:
            result["error"] = "authorizeLogin未返回token"
            print(f"❌ [登录] {result['error']}")
            return result

        print(f"✅ [登录] 登录成功: memberId={member_id}, token={mask(access_token)}")
        result["token"] = mask(access_token)

        sleep(API_REQUEST_DELAY)

        userinfo_url = f"{API_BASE}/api/user/info"
        userinfo_timestamp = int(time.time() * 1000)
        userinfo_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{userinfo_timestamp}").lower()

        userinfo_headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Customer": member_id,
            "brandCode": BRAND_CODE,
            "appid": SMALL_APPLICATION_ID,
            "sign": userinfo_sign,
            "timestamp": str(userinfo_timestamp),
            "versionNumber": VERSION_NUMBER,
            "AccessToken": access_token,
        }

        userinfo_resp = request_with_proxy(
            "POST",
            userinfo_url,
            proxies=proxies,
            server=entry,
            headers=userinfo_headers,
            json={},
        )

        try:
            userinfo_data = userinfo_resp.json()
        except Exception:
            userinfo_data = {}

        print(f"🔍 [用户] 查询用户信息响应: {json_preview(userinfo_data)}")

        if not userinfo_data.get("data"):
            result["error"] = "查询用户信息失败: 返回为空"
            print(f"❌ [用户] {result['error']}")
            return result

        user_info = userinfo_data.get("data", {})
        nick_name = user_info.get("nickName", user_info.get("name", member_id))
        mobile = user_info.get("mobile", "")

        if mobile:
            print(f"👤 [用户] {nick_name} {mask_phone(mobile)}")
        else:
            print(f"👤 [用户] {nick_name}")

        result["userInfo"] = f"{nick_name} {mask_phone(mobile)}" if mobile else nick_name

        sleep(API_REQUEST_DELAY)

        calendar_url = f"{INTEGRAL_BASE}/user/sign/calendar"
        calendar_timestamp = int(time.time() * 1000)
        calendar_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{calendar_timestamp}").lower()

        calendar_headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Customer": member_id,
            "brandCode": BRAND_CODE,
            "appid": SMALL_APPLICATION_ID,
            "sign": calendar_sign,
            "timestamp": str(calendar_timestamp),
            "versionNumber": VERSION_NUMBER,
            "AccessToken": access_token,
        }

        calendar_resp = request_with_proxy(
            "GET",
            calendar_url,
            proxies=proxies,
            server=entry,
            headers=calendar_headers,
        )

        try:
            calendar_data = calendar_resp.json()
        except Exception:
            calendar_data = {}

        print(f"🔍 [日历] 日历查询响应: {json_preview(calendar_data)}")

        if calendar_data.get("code") == 0:
            print(f"✅ [日历] 日历查询成功")
        else:
            print(f"⚠️  [日历] 日历查询失败")

        sleep(API_REQUEST_DELAY)

        sign_url = f"{INTEGRAL_BASE}/scenePoint/scene/point"
        sign_timestamp = int(time.time() * 1000)
        sign_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{sign_timestamp}").lower()
        parameter_sign = build_parameter_sign({
            "scene": "sign",
            "brandCode": BRAND_CODE,
        }, sign_timestamp)

        sign_headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Customer": member_id,
            "brandCode": BRAND_CODE,
            "appid": SMALL_APPLICATION_ID,
            "sign": sign_sign,
            "timestamp": str(sign_timestamp),
            "versionNumber": VERSION_NUMBER,
            "AccessToken": access_token,
            "parameterSign": parameter_sign,
        }

        sign_body = {
            "scene": "sign",
            "brandCode": BRAND_CODE,
        }

        sign_resp = request_with_proxy(
            "POST",
            sign_url,
            proxies=proxies,
            server=entry,
            headers=sign_headers,
            json=sign_body,
        )

        try:
            sign_data = sign_resp.json()
        except Exception:
            sign_data = {}

        print(f"🔍 [签到] 签到响应: {json_preview(sign_data)}")

        if sign_data.get("code") == 0:
            print(f"✅ [签到] 签到成功")
            result["signInStatus"] = "成功"
            result["success"] = True
        else:
            error_msg = sign_data.get("message", sign_data.get("msg", ""))
            if any(keyword in error_msg for keyword in ["已签", "重复", "already", "今日"]):
                print(f"✅ [签到] 今日已签到")
                result["signInStatus"] = "已签到"
                result["success"] = True
            else:
                print(f"❌ [签到] 签到失败: {error_msg}")
                result["error"] = f"签到失败: {error_msg}"

        sleep(API_REQUEST_DELAY)

        # ========== 每日社区互动（点赞3次+收藏3次 = 9积分） ==========
        print(f"\n--- 每日社区互动 ---")

        COMMUNITY_LIKE_LIMIT = 3
        COMMUNITY_COLLECT_LIMIT = 3

        # 获取帖子列表（用 selectPage 接口，返回 likeStatus/collectStatus）
        post_list = []
        for page_num in range(1, 4):
            sleep(API_REQUEST_DELAY)
            list_url = f"{API_BASE}/applet/waterfall/selectPage"
            list_timestamp = int(time.time() * 1000)
            list_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{list_timestamp}").lower()

            list_body = {
                "source": 1,
                "pageNum": page_num,
                "pageSize": 10,
                "topicId": "119",
            }

            list_parameter_sign = build_parameter_sign(list_body, list_timestamp)

            list_headers = {
                "User-Agent": USER_AGENT,
                "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "X-Customer": member_id,
                "brandCode": BRAND_CODE,
                "appid": SMALL_APPLICATION_ID,
                "sign": list_sign,
                "timestamp": str(list_timestamp),
                "versionNumber": VERSION_NUMBER,
                "AccessToken": access_token,
                "parameterSign": list_parameter_sign,
            }

            list_resp = request_with_proxy(
                "POST",
                list_url,
                proxies=proxies,
                server=entry,
                headers=list_headers,
                json=list_body,
            )

            try:
                list_data = list_resp.json()
            except Exception:
                list_data = {}

            if list_data.get("code") == 0 and list_data.get("data"):
                ld = list_data["data"]
                items = []
                if isinstance(ld, dict) and "list" in ld:
                    items = ld["list"]
                elif isinstance(ld, list):
                    items = ld
                post_list.extend(items)
                # 如果已获取足够帖子就不再翻页
                if len(post_list) >= 20:
                    break
            else:
                print(f"⚠️  [社区] 第{page_num}页获取失败")
                break

        print(f"📝 [社区] 共获取 {len(post_list)} 个帖子")

        # 筛选未点赞和未收藏的帖子
        unliked_posts = [p for p in post_list if p.get("likeStatus") != 1]
        uncollected_posts = [p for p in post_list if p.get("collectStatus") != 1]

        print(f"📝 [社区] 未点赞: {len(unliked_posts)} 个，未收藏: {len(uncollected_posts)} 个")

        like_count = 0
        like_fail_count = 0
        collect_count = 0
        collect_fail_count = 0

        # 点赞3次（选未点赞的帖子）
        # 点赞3次（选未点赞的帖子，每次先调 likeSendPoint 发积分再调 like）
        for i, post in enumerate(unliked_posts[:COMMUNITY_LIKE_LIMIT]):
            sleep(API_REQUEST_DELAY)
            post_id = post.get("id")
            post_title = str(post.get("title", ""))[:20]
            print(f"👍 [社区] 第{i+1}次点赞: id={post_id}, title={post_title}")

            # 1) 先调 likeSendPoint 发放积分（triggerType=1 点赞）
            lsp_url = f"{API_BASE}/front/member/likeSendPoint"
            lsp_timestamp = int(time.time() * 1000)
            lsp_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{lsp_timestamp}").lower()
            lsp_body = {
                "postOrderId": int(post_id) if post_id else 0,
                "triggerType": 1,
                "content": "点赞",
                "os": "weapp",
                "appVersion": VERSION_NUMBER,
            }
            lsp_parameter_sign = build_parameter_sign(lsp_body, lsp_timestamp)
            lsp_headers = {
                "User-Agent": USER_AGENT,
                "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "X-Customer": member_id,
                "brandCode": BRAND_CODE,
                "appid": SMALL_APPLICATION_ID,
                "sign": lsp_sign,
                "timestamp": str(lsp_timestamp),
                "versionNumber": VERSION_NUMBER,
                "AccessToken": access_token,
                "parameterSign": lsp_parameter_sign,
            }
            try:
                lsp_resp = request_with_proxy(
                    "POST", lsp_url, proxies=proxies, server=entry,
                    headers=lsp_headers, json=lsp_body,
                )
                lsp_data = lsp_resp.json()
                if lsp_data.get("code") == 0:
                    print(f"💰 [社区] 点赞积分领取成功")
                else:
                    lsp_msg = lsp_data.get("message", lsp_data.get("msg", ""))
                    print(f"⚠️ [社区] 点赞积分领取: {lsp_msg}")
            except Exception as exc:
                print(f"⚠️ [社区] likeSendPoint异常: {exc}")

            sleep(API_REQUEST_DELAY)

            # 2) 再调 postOrder/like 完成点赞
            like_url = f"{API_BASE}/front/postOrder/like"
            like_timestamp = int(time.time() * 1000)
            like_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{like_timestamp}").lower()
            like_body = {"id": post_id}
            like_parameter_sign = build_parameter_sign(like_body, like_timestamp)
            like_headers = {
                "User-Agent": USER_AGENT,
                "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "X-Customer": member_id,
                "brandCode": BRAND_CODE,
                "appid": SMALL_APPLICATION_ID,
                "sign": like_sign,
                "timestamp": str(like_timestamp),
                "versionNumber": VERSION_NUMBER,
                "AccessToken": access_token,
                "parameterSign": like_parameter_sign,
            }
            like_resp = request_with_proxy(
                "POST", like_url, proxies=proxies, server=entry,
                headers=like_headers, json=like_body,
            )
            try:
                like_data = like_resp.json()
            except Exception:
                like_data = {}
            if like_data.get("code") == 0:
                like_count += 1
                print(f"✅ [社区] 点赞成功 ({like_count}/{COMMUNITY_LIKE_LIMIT})")
            else:
                like_msg = like_data.get("message", like_data.get("msg", ""))
                if any(kw in like_msg for kw in ["已", "重复", "already", "今日"]):
                    like_count += 1
                    print(f"✅ [社区] 今日已点赞 ({like_count}/{COMMUNITY_LIKE_LIMIT})")
                else:
                    like_fail_count += 1
                    print(f"❌ [社区] 点赞失败: {like_msg}")

        # 收藏3次（选未收藏的帖子）
        # 收藏3次（选未收藏的帖子，每次先调 likeSendPoint 发积分再调 collect）
        for i, post in enumerate(uncollected_posts[:COMMUNITY_COLLECT_LIMIT]):
            sleep(API_REQUEST_DELAY)
            post_id = post.get("id")
            post_title = str(post.get("title", ""))[:20]
            print(f"⭐ [社区] 第{i+1}次收藏: id={post_id}, title={post_title}")

            # 1) 先调 likeSendPoint 发放积分（triggerType=2 收藏）
            lsp_url = f"{API_BASE}/front/member/likeSendPoint"
            lsp_timestamp = int(time.time() * 1000)
            lsp_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{lsp_timestamp}").lower()
            lsp_body = {
                "postOrderId": int(post_id) if post_id else 0,
                "triggerType": 2,
                "content": "收藏",
                "os": "weapp",
                "appVersion": VERSION_NUMBER,
            }
            lsp_parameter_sign = build_parameter_sign(lsp_body, lsp_timestamp)
            lsp_headers = {
                "User-Agent": USER_AGENT,
                "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "X-Customer": member_id,
                "brandCode": BRAND_CODE,
                "appid": SMALL_APPLICATION_ID,
                "sign": lsp_sign,
                "timestamp": str(lsp_timestamp),
                "versionNumber": VERSION_NUMBER,
                "AccessToken": access_token,
                "parameterSign": lsp_parameter_sign,
            }
            try:
                lsp_resp = request_with_proxy(
                    "POST", lsp_url, proxies=proxies, server=entry,
                    headers=lsp_headers, json=lsp_body,
                )
                lsp_data = lsp_resp.json()
                if lsp_data.get("code") == 0:
                    print(f"💰 [社区] 收藏积分领取成功")
                else:
                    lsp_msg = lsp_data.get("message", lsp_data.get("msg", ""))
                    print(f"⚠️ [社区] 收藏积分领取: {lsp_msg}")
            except Exception as exc:
                print(f"⚠️ [社区] likeSendPoint异常: {exc}")

            sleep(API_REQUEST_DELAY)

            # 2) 再调 postOrder/collect 完成收藏
            collect_url = f"{API_BASE}/front/postOrder/collect"
            collect_timestamp = int(time.time() * 1000)
            collect_sign = md5(f"{SMALL_APPLICATION_ID}{SMALL_CRYPTO}{collect_timestamp}").lower()
            collect_body = {"id": post_id}
            collect_parameter_sign = build_parameter_sign(collect_body, collect_timestamp)
            collect_headers = {
                "User-Agent": USER_AGENT,
                "Referer": f"https://servicewechat.com/{APPID}/{PAGE_VERSION}/page-frame.html",
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "X-Customer": member_id,
                "brandCode": BRAND_CODE,
                "appid": SMALL_APPLICATION_ID,
                "sign": collect_sign,
                "timestamp": str(collect_timestamp),
                "versionNumber": VERSION_NUMBER,
                "AccessToken": access_token,
                "parameterSign": collect_parameter_sign,
            }
            collect_resp = request_with_proxy(
                "POST", collect_url, proxies=proxies, server=entry,
                headers=collect_headers, json=collect_body,
            )
            try:
                collect_data = collect_resp.json()
            except Exception:
                collect_data = {}
            if collect_data.get("code") == 0:
                collect_count += 1
                print(f"✅ [社区] 收藏成功 ({collect_count}/{COMMUNITY_COLLECT_LIMIT})")
            else:
                collect_msg = collect_data.get("message", collect_data.get("msg", ""))
                if any(kw in collect_msg for kw in ["已", "重复", "already", "今日"]):
                    collect_count += 1
                    print(f"✅ [社区] 今日已收藏 ({collect_count}/{COMMUNITY_COLLECT_LIMIT})")
                else:
                    collect_fail_count += 1
                    print(f"❌ [社区] 收藏失败: {collect_msg}")

        # 汇总结果
        like_done = like_count >= COMMUNITY_LIKE_LIMIT
        collect_done = collect_count >= COMMUNITY_COLLECT_LIMIT
        if like_done and collect_done:
            result["communityStatus"] = f"成功(赞{like_count}/藏{collect_count})"
            if not result["success"]:
                result["success"] = True
        elif like_count > 0 or collect_count > 0:
            result["communityStatus"] = f"部分(赞{like_count}/藏{collect_count})"
        else:
            result["communityStatus"] = "失败"



    except Exception as exc:
        result["error"] = f"执行异常: {str(exc)}"
        print(f"❌ [异常] {result['error']}")
        traceback.print_exc()
        return result

    return result


def build_notify(results: List[Dict[str, Any]]) -> str:
    success_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - success_count

    lines = []
    lines.append("")
    lines.append(f"📱 {APP_NAME} 任务结果")
    lines.append("")
    lines.append("━" * 22)
    lines.append(f"🏁 总结：{success_count} 成功 / {fail_count} 失败")
    lines.append(f"🕒 时间：{now_text()}")
    lines.append("━" * 22)
    lines.append("")

    for idx, res in enumerate(results, 1):
        icon = "✅" if res["success"] else "❌"
        result_text = "成功" if res["success"] else "失败"

        lines.append(f"🧩 账号 {idx}")
        lines.append(f"🌍 来源：{res['server']}")
        lines.append(f"🌐 代理：{res['proxyStatus']}")
        lines.append(f"📡 出口IP：{res['proxyIp']}")
        lines.append(f"👤 用户：{res['userInfo']}")
        lines.append(f"✅ 签到：{res['signInStatus']}")
        lines.append(f"💬 社区互动：{res['communityStatus']}")
        lines.append(f"{icon} 结果：{result_text}")

        if not res["success"]:
            lines.append(f"❌ 原因：{res['error']}")

        lines.append("━" * 22)
        lines.append("")

    return "\n".join(lines)



def send_pushplus(title: str, content: str) -> None:
    if not PLUSPLUS_TOKEN:
        print("⚠️ [PushPlus] 未配置 PLUSPLUS_TOKEN，跳过推送")
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
        print("✅ [PushPlus] 推送成功")
    except Exception as exc:
        print(f"❌ [PushPlus] 推送失败: {exc}")

def main() -> None:
    print(f"\n{'='*50}")
    print(f"🚀 {APP_NAME} 自动签到")
    print(f"{'='*50}\n")

    results = []
    for i, server in enumerate(SERVERS, 1):
        try:
            result = run_account(i, len(SERVERS), server)
            results.append(result)

            if i < len(SERVERS):
                sleep(2)

        except Exception as exc:
            print(f"❌ [账号 {i}] 执行异常: {str(exc)}")
            traceback.print_exc()
            results.append({
                "server": server,
                "success": False,
                "error": f"执行异常: {str(exc)}",
            })

    success_count = sum(1 for r in results if r.get("success"))
    print(f"\n{'='*50}")
    print(f"📊 执行完成")
    print(f"✅ 成功: {success_count} | ❌ 失败: {len(results) - success_count}")
    print(f"{'='*50}\n")

    if PLUSPLUS_TOKEN:
        notify_title = f"{APP_NAME} 签到通知"
        notify_content = build_notify(results)
        send_pushplus(notify_title, notify_content)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断执行")
    except Exception as exc:
        print(f"\n\n❌ 程序异常: {exc}")
        traceback.print_exc()
