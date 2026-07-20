#!/usr/bin/env python3
# name: 小福家
# cron: 30 7 * * *
# -*- coding: utf-8 -*-

"""
小福家小程序登录 - code 版
code 从 YYB Go (YYB_SERVER) 获取，手机号加密数据从 phonecode 服务获取

环境变量：
  YYB_SERVER           必填：YYB Go 服务地址@微信账号标识，多行换行
  PHONECODE_SERVER     可选：phonecode 服务地址，默认同 YYB Go 地址
                        （如果 phonecode 和 YYB Go 在同一机器不同端口，单独配置）

依赖：
  pip install requests
"""

import os
import sys
import json
import time
import hashlib
import requests

# ========== 配置 ==========
APPID = "wxe6ba46e6100e68e9"
APPKEY = "b98b1abf926b44e3998e5573b42f101f"
APPSECRET = "e5e3333fbb7448c7813281c68bad7f57"
API_HOST = "api.xiaofujia.com"
API_BASE = f"https://{API_HOST}"
PLATFORM = 12  # WECHAT_MNP

# phonecode 服务地址，默认从 YYB_SERVER 第一行提取
PHONECODE_SERVER = os.getenv("PHONECODE_SERVER", "")

# ========== 从 YYB_SERVER 读取服务地址 ==========
env_YYB_SERVER = os.getenv("YYB_SERVER", "")
if env_YYB_SERVER:
    raw_lines = env_YYB_SERVER.splitlines()
else:
    print("❌ 错误：未读取到环境变量 YYB_SERVER！")
    print("青龙环境变量YYB_SERVER填写示例：192.168.3.191:8000@微信账号标识")
    sys.exit(1)

SERVERS = []
for line in raw_lines:
    line = line.strip()
    if line and "@" in line:
        SERVERS.append(line)

if not SERVERS:
    print("❌ 错误：YYB_SERVER 无有效账号（格式：地址@微信账号标识）")
    sys.exit(1)

print(f"✅ 读取到 {len(SERVERS)} 个账号")


def parse_yyb_entry(raw: str) -> dict:
    value = raw.strip()
    at_idx = value.index("@")
    server = value[:at_idx].strip()
    ref = value[at_idx + 1:].strip()
    if server.startswith("http://"):
        server = server[7:]
    elif server.startswith("https://"):
        server = server[8:]
    server = server.rstrip("/")
    if not server or not ref:
        return None
    return {"server": server, "ref": ref}


def get_code(entry: str) -> str | None:
    """从 YYB Go 获取微信 code"""
    parsed = parse_yyb_entry(entry)
    if not parsed:
        return None
    server, ref = parsed["server"], parsed["ref"]
    url = f"http://{server}/wxapp/getCode"
    print(f"[{server}] 请求YYB Go获取code...")
    try:
        resp = requests.post(url, json={"ref": ref, "app_id": APPID}, timeout=20)
        data = resp.json()
        code = (((data.get("data") or {}).get("result") or {}).get("code"))
        if data.get("code") != 0 or not code:
            print(f"[{server}] 获取code失败: {json.dumps(data, ensure_ascii=False)[:200]}")
            return None
        print(f"[{server}] 获取code成功: {code[:8]}****")
        return code
    except Exception as e:
        print(f"[{server}] 获取code异常: {e}")
        return None


def get_phonecode_host(entry: str) -> str:
    """获取 phonecode 服务地址"""
    if PHONECODE_SERVER:
        host = PHONECODE_SERVER
    else:
        parsed = parse_yyb_entry(entry)
        host = parsed["server"] if parsed else ""
    
    # 去掉端口，phonecode 可能是另一个端口
    # 如果没配 PHONECODE_SERVER，尝试同地址
    if not host.startswith("http"):
        host = f"http://{host}"
    return host


def get_mobile_encrypted(entry: str) -> dict | None:
    """从 phonecode 服务获取手机号加密数据"""
    parsed = parse_yyb_entry(entry)
    if not parsed:
        return None
    ref = parsed["ref"]
    
    phonecode_host = get_phonecode_host(entry)
    url = f"{phonecode_host}/api/v1/wx/app/get/all/mobile"
    print(f"[{phonecode_host}] 请求phonecode手机号数据...")
    
    try:
        resp = requests.post(url, json={
            "appid": APPID,
            "wxid": ref,
            "data": json.dumps({"api_name": "webapi_getuserwxphone", "with_credentials": True}),
            "opt": 1
        }, timeout=20)
        data = resp.json()
        
        if data.get("Code") != 0 and data.get("code") != 0:
            print(f"[{phonecode_host}] 获取手机号失败: {json.dumps(data, ensure_ascii=False)[:200]}")
            return None
        
        all_mobile = data.get("Data", {}).get("ALLMobile", [])
        if not all_mobile:
            print(f"[{phonecode_host}] 未找到手机号数据")
            return None
        
        mobile = all_mobile[0]
        encrypted = mobile.get("encryptedData")
        iv = mobile.get("iv")
        if not encrypted or not iv:
            print(f"[{phonecode_host}] 手机号数据不完整")
            return None
        
        print(f"[{phonecode_host}] 获取手机号加密数据成功")
        return {"encryptedData": encrypted, "iv": iv}
    except Exception as e:
        print(f"[{phonecode_host}] 获取手机号异常: {e}")
        return None


def xiaofujia_sign(params: dict) -> str:
    p = params.copy()
    p["time"] = int(time.time())
    p["appkey"] = APPKEY
    sign_str = ""
    for key in sorted(p.keys()):
        if p[key] is not None:
            sign_str += f"{key}{p[key]}"
    sign_str += APPSECRET
    return hashlib.md5(sign_str.encode()).hexdigest()


def xiaofujia_login(code: str, mobile_data: dict) -> dict | None:
    print("→ 开始小福家登录...")
    login_url = f"{API_BASE}/familychat/user/login"
    
    auth_token = json.dumps({
        "code": code,
        "mobile_encrypt_data": mobile_data["encryptedData"],
        "mobile_iv": mobile_data["iv"]
    })
    
    body = {
        "auth_type": 2,
        "auth_token": auth_token,
        "platform": PLATFORM,
        "did": "nfPQXpkJaxRQ8BQw4B66KWtWBFXC22SH",
        "metadata": {"launch_mnp_scene": 0}
    }
    
    t = int(time.time())
    sign = xiaofujia_sign({})
    full_url = f"{login_url}?time={t}&appkey={APPKEY}&sign={sign}"
    
    headers = {
        "content-type": "application/json;charset=UTF-8",
        "Host": API_HOST,
        "Connection": "keep-alive",
        "cPkg": "MiTee Client on 8",
        "Accept-Encoding": "gzip,compress,br,deflate",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x18003121) NetType/WIFI Language/zh_CN",
        "Referer": "https://servicewechat.com/wxe6ba46e6100e68e9/116/page-frame.html"
    }
    
    try:
        resp = requests.post(full_url, json=body, headers=headers, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            print(f"✗ 小福家登录失败: {data.get('msg', '未知错误')}")
            return None
        token = data.get("data", {})
        access_token = token.get("access_token", "")
        print(f"✓ 小福家登录成功！access_token: {access_token[:15]}...")
        return {"access_token": access_token}
    except Exception as e:
        print(f"✗ 小福家登录异常: {e}")
        return None


# ========== 主流程 ==========
def main():
    print("┌─────────────────────────────┐")
    print("│ 小福家小程序登录 │")
    print("└─────────────────────────────┘")
    
    phonecode_host = get_phonecode_host(SERVERS[0]) if SERVERS else ""
    print(f"phonecode 服务: {phonecode_host}")
    
    for i, entry in enumerate(SERVERS):
        parsed = parse_yyb_entry(entry)
        if not parsed:
            print(f"✗ 第{i+1}行格式无效，跳过")
            continue
        
        print(f"\n========== 账号[{i+1}] {parsed['ref']} ==========")
        
        # 1. 从 YYB Go 获取 code
        code = get_code(entry)
        if not code:
            continue
        
        # 2. 从 phonecode 服务获取手机号
        mobile_data = get_mobile_encrypted(entry)
        if not mobile_data:
            continue
        
        # 3. 小福家登录
        result = xiaofujia_login(code, mobile_data)
        if result:
            print(f"✓ 账号[{i+1}] 登录成功")
            print(f"ACCESS_TOKEN={result['access_token']}")
        else:
            print(f"✗ 账号[{i+1}] 登录失败")
        
        if i < len(SERVERS) - 1:
            time.sleep(5)
    
    print("\n┌─────────────────────────────┐")
    print("│ 所有账号处理完成 │")
    print("└─────────────────────────────┘")


if __name__ == "__main__":
    main()
