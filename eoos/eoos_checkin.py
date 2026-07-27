# -*- coding: utf-8 -*-
"""
name: EOOS Emby 签到
cron: 30 8 * * *
new Env('EOOS Emby 签到');
"""

"""
EOOS Emby 管理站每日签到脚本
站点: https://eoos.top
签到流程: 登录 → 查状态 → 获取验证码 → OCR识别 → 验证 → 签到

环境变量:
  EOOS_USER     - 用户名
  EOOS_PASS     - 密码
  EOOS_OCR_URL  - OCR服务地址 (可选, 默认 http://localhost:7778)
"""

import os
import sys
import json
import time
import requests
from datetime import datetime

SITE_URL = "https://eoos.top"
OCR_URL = os.getenv("EOOS_OCR_URL", "http://localhost:7778")
USERNAME = os.getenv("EOOS_USER", "")
PASSWORD = os.getenv("EOOS_PASS", "")
MAX_RETRY = 3

HEADERS = {
    "Content-Type": "application/json",
    "Origin": SITE_URL,
    "Referer": f"{SITE_URL}/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def login(session):
    resp = session.post(
        f"{SITE_URL}/api/auth/login",
        headers=HEADERS,
        json={"userName": USERNAME, "password": PASSWORD},
        timeout=15,
    )
    data = resp.json()
    if "token" not in data:
        raise Exception(f"登录失败: {data.get('message', resp.text)}")
    token = data["token"]
    user = data.get("user", {})
    log(f"登录成功: {user.get('userName', USERNAME)} | 余额: {user.get('rCoin', '?')} RCoin")
    return token


def get_checkin_status(session, token):
    resp = session.get(
        f"{SITE_URL}/api/checkin/status",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        timeout=15,
    )
    data = resp.json()
    if data.get("hasCheckedInToday"):
        log(f"今日已签到，获得 {data.get('amount', '?')} {data.get('currencyUnit', 'RCoin')}")
        return True
    return False


def generate_captcha(session, token, action="checkin"):
    resp = session.get(
        f"{SITE_URL}/api/captcha/generate",
        params={"action": action},
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        timeout=15,
    )
    data = resp.json()
    if not data.get("success"):
        error = data.get("error", "未知错误")
        if "未启用" in error:
            return None, None  # 验证码功能未启用
        raise Exception(f"获取验证码失败: {error}")
    captcha = data["data"]
    return captcha["sessionId"], captcha["imageData"]


def solve_captcha(image_data):
    if "," in image_data and image_data.startswith("data:"):
        b64 = image_data.split(",", 1)[1]
    else:
        b64 = image_data
    resp = requests.post(
        f"{OCR_URL}/classification",
        json={"image": b64},
        timeout=15,
    )
    return resp.json().get("result", "").strip()


def verify_captcha(session, token, action, answer, session_id):
    resp = session.post(
        f"{SITE_URL}/api/captcha/verify",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        json={"action": action, "answer": answer, "sessionId": session_id},
        timeout=15,
    )
    return resp.json()


def do_checkin(session, token, verification_token=None):
    payload = {}
    if verification_token:
        payload["verificationToken"] = verification_token
    resp = session.post(
        f"{SITE_URL}/api/checkin",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        json=payload,
        timeout=15,
    )
    return resp.json()


def checkin_with_captcha(session, token):
    for attempt in range(1, MAX_RETRY + 1):
        log(f"获取验证码 (第{attempt}次)...")
        session_id, image_data = generate_captcha(session, token, "checkin")

        if session_id is None:
            # 验证码功能未启用，尝试直接签到
            log("验证码功能未启用，尝试直接签到...")
            result = do_checkin(session, token)
            if result.get("success"):
                amount = result.get("amount", "?")
                unit = result.get("currencyUnit", "RCoin")
                balance = result.get("balance", "")
                log(f"✅ 签到成功！获得 {amount} {unit}" + (f" | 余额: {balance}" if balance else ""))
                return True
            else:
                msg = result.get("message", "")
                if "已经签到" in msg:
                    log(f"今日已签到: {msg}")
                    return True
                log(f"❌ 签到失败: {msg}")
                log("提示: 站点验证码功能未启用且后端要求验证，请联系站长修复")
                return False

        try:
            log("OCR识别中...")
            answer = solve_captcha(image_data)
            if not answer:
                log("识别结果为空，重试...")
                continue
            log(f"识别结果: {answer}")

            log("提交验证...")
            verify_result = verify_captcha(session, token, "checkin", answer, session_id)
            if not verify_result.get("success"):
                log(f"验证失败: {verify_result.get('error', '未知错误')}，重试...")
                continue

            verified_token = verify_result.get("sessionId", session_id)
            log("验证通过，执行签到...")
            result = do_checkin(session, token, verified_token)

            if result.get("success"):
                amount = result.get("amount", "?")
                unit = result.get("currencyUnit", "RCoin")
                balance = result.get("balance", "")
                log(f"✅ 签到成功！获得 {amount} {unit}" + (f" | 余额: {balance}" if balance else ""))
                return True
            else:
                msg = result.get("message", "")
                if "已经签到" in msg:
                    log(f"今日已签到: {msg}")
                    return True
                log(f"签到失败: {msg}")
                return False

        except Exception as e:
            log(f"第{attempt}次出错: {e}")
            if attempt < MAX_RETRY:
                time.sleep(2)
            continue

    log(f"❌ {MAX_RETRY}次重试后仍失败")
    return False


def main():
    if not USERNAME or not PASSWORD:
        print("❌ 请设置环境变量 EOOS_USER 和 EOOS_PASS")
        sys.exit(1)

    session = requests.Session()
    try:
        token = login(session)

        if get_checkin_status(session, token):
            print("\n今日已签到，无需重复操作")
            return

        log("开始签到流程...")
        if not checkin_with_captcha(session, token):
            sys.exit(1)

    except Exception as e:
        print(f"❌ 执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
