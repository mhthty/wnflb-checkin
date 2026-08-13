# -*- coding: utf-8 -*-
"""
Discuz! X3.4 论坛自动签到 - 福利吧专版 (fx_checkin 插件)
支持 Cookie 登录 / 账号密码登录 + 多渠道推送
"""
import os
import re
import sys
import time
import argparse
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = os.environ.get("FORUM_URL", "https://www.wnflb2023.com").rstrip("/")


# ========================= 多渠道推送 =========================
def send_notification(title: str, content: str):
    """多渠道通知聚合 (环境变量为空自动跳过该渠道)"""
    pushed_any = False

    # Server酱 (推荐，免费，微信)
    sct_token = os.environ.get("SCT_TOKEN", "").strip()
    if not sct_token:
        sct_token = os.environ.get("SERVERCHAN_KEY", "").strip()
    if sct_token:
        try:
            url = f"https://sctapi.ftqq.com/{sct_token}.send"
            r = requests.post(url, data={"title": title, "desp": content}, timeout=10)
            ok = r.status_code == 200 and r.json().get("code") == 0
            print(f"  [Server酱] {'✅ 成功' if ok else '❌ 失败'}")
            if ok:
                pushed_any = True
        except Exception as e:
            print(f"  [Server酱] ❌ 异常: {e}")

    # PushPlus
    pp_token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if pp_token:
        try:
            url = "https://www.pushplus.plus/send"
            r = requests.get(url, params={"token": pp_token, "title": title, "content": content}, timeout=10)
            ok = r.status_code == 200 and '"code":200' in r.text
            print(f"  [PushPlus] {'✅ 成功' if ok else '❌ 失败'}")
            if ok:
                pushed_any = True
        except Exception as e:
            print(f"  [PushPlus] ❌ 异常: {e}")

    # Telegram
    tg_bot = os.environ.get("TG_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TG_CHAT_ID", "").strip()
    if tg_bot and tg_chat:
        try:
            url = f"https://api.telegram.org/bot{tg_bot}/sendMessage"
            payload = {"chat_id": tg_chat, "text": f"<b>{title}</b>\n<pre>{content}</pre>", "parse_mode": "HTML"}
            r = requests.post(url, json=payload, timeout=15)
            ok = r.status_code == 200 and r.json().get("ok")
            print(f"  [Telegram] {'✅ 成功' if ok else '❌ 失败'}")
            if ok:
                pushed_any = True
        except Exception as e:
            print(f"  [Telegram] ❌ 异常: {e}")

    # Bark (iOS)
    bark_url = os.environ.get("BARK_URL", "").strip()
    if bark_url:
        try:
            r = requests.post(bark_url, json={"title": title, "body": content}, timeout=15)
            print(f"  [Bark] {'✅ 成功' if r.status_code == 200 else '❌ 失败'}")
            if r.status_code == 200:
                pushed_any = True
        except Exception as e:
            print(f"  [Bark] ❌ 异常: {e}")

    # 企业微信机器人
    wecom = os.environ.get("WECOM_WEBHOOK", "").strip()
    if wecom:
        try:
            payload = {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{content}"}}
            r = requests.post(wecom, json=payload, timeout=15)
            print(f"  [企业微信] {'✅ 成功' if r.status_code == 200 else '❌ 失败'}")
            if r.status_code == 200:
                pushed_any = True
        except Exception as e:
            print(f"  [企业微信] ❌ 异常: {e}")

    # 虾推啥
    xts_token = os.environ.get("XIATUISHE_TOKEN", "").strip()
    if xts_token:
        try:
            xts_server = os.environ.get("XIATUISHE_SERVER", "https://wx.xtuis.cn").strip() or "https://wx.xtuis.cn"
            url = f"{xts_server.rstrip('/')}/{xts_token}.send"
            r = requests.get(url, params={"text": title, "desp": content[:500]}, timeout=10)
            ok = r.status_code == 200 and any(k in r.text.lower() for k in ("success", "ok", "成功"))
            print(f"  [虾推啥] {'✅ 成功' if ok else '❌ 失败'}")
            if ok:
                pushed_any = True
        except Exception as e:
            print(f"  [虾推啥] ❌ 异常: {e}")

    # 全部没配置
    if not pushed_any and not any([
        os.environ.get("SCT_TOKEN"), os.environ.get("SERVERCHAN_KEY"),
        os.environ.get("PUSHPLUS_TOKEN"), os.environ.get("TG_BOT_TOKEN"),
        os.environ.get("BARK_URL"), os.environ.get("WECOM_WEBHOOK"),
        os.environ.get("XIATUISHE_TOKEN"),
    ]):
        print("  (未配置推送通知，如需推送请在 GitHub Secrets 配置)")


# ========================= 签到核心 =========================
class DiscuzSigner:
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(self, forum_url, username="", password="", cookie=""):
        self.forum_url = forum_url
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.formhash = ""
        self.logged_in = False
        if cookie:
            self._load_cookie(cookie)

    def _load_cookie(self, cookie_str):
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip())
        print(f"  [Cookie] 已注入 {len(self.session.cookies)} 个")

    @staticmethod
    def _extract_formhash(html):
        m = re.search(r'name="formhash"\s+value="([a-f0-9]{8})"', html)
        if m:
            return m.group(1)
        m = re.search(r'formhash=([a-f0-9]{8})', html)
        return m.group(1) if m else ""

    def _verify_login(self):
        try:
            resp = self.session.get(self.forum_url, timeout=15)
        except Exception as e:
            print(f"  [登录] 验证请求失败: {e}")
            return False
        html = resp.text
        self.formhash = self._extract_formhash(html)
        if self.username and self.username in html:
            return True
        if re.search(r"discuz_uid\s*=\s*\d{3,}", html):
            return True
        return False

    def login_via_cookie(self):
        print("  [登录] Cookie 方式...")
        if self._verify_login():
            print("  ✅ Cookie 有效，已登录")
            self.logged_in = True
            return True
        print("  ❌ Cookie 已失效")
        return False

    def login_via_password(self):
        print("  [登录] 账号密码方式...")
        login_url = urljoin(self.forum_url, "member.php?mod=logging&action=login")
        try:
            resp = self.session.get(login_url, timeout=15)
            self.formhash = self._extract_formhash(resp.text)
            if not self.formhash:
                print("  ❌ 未找到 formhash")
                return False
        except Exception as e:
            print(f"  ❌ 访问登录页失败: {e}")
            return False

        post_url = urljoin(self.forum_url,
            "member.php?mod=logging&action=login&loginsubmit=yes&inajax=1")
        data = {"formhash": self.formhash, "username": self.username,
                "password": self.password, "questionid": "0", "answer": ""}
        try:
            resp = self.session.post(post_url, data=data, timeout=15)
        except Exception as e:
            print(f"  ❌ 登录请求失败: {e}")
            return False

        text = resp.text
        if "请输入验证码" in text:
            print("  ❌ 论坛要求验证码，账号密码方式无法自动处理，请使用 Cookie 方式")
            return False
        if "密码错误" in text:
            print("  ❌ 账号或密码错误")
            return False
        if self._verify_login():
            print("  ✅ 登录成功")
            self.logged_in = True
            return True
        print("  ❌ 登录后验证失败")
        return False

    def sign(self):
        """执行签到 (fx_checkin 插件)"""
        if not self.logged_in:
            if len(self.session.cookies) > 0:
                self.login_via_cookie()
            if not self.logged_in and self.password:
                self.login_via_password()
            if not self.logged_in:
                return False, "登录失败"

        sign_path = os.environ.get("FORUM_SIGN_PATH", "plugin.php?id=fx_checkin:checkin")
        sign_url = urljoin(self.forum_url, sign_path)

        print(f"  [签到] 访问签到页: {sign_url}")
        try:
            resp = self.session.get(sign_url, timeout=15)
        except Exception as e:
            return False, f"访问签到页失败: {e}"

        if self._already_signed(resp.text):
            print("  ✅ 今日已签到（跳过）")
            return True, "今日已签到"

        self.formhash = self._extract_formhash(resp.text) or self.formhash
        print(f"  [签到] formhash={self.formhash}")

        fx_url = self._build_fx_url()
        print(f"  [签到] 调用接口: {fx_url}")
        try:
            sign_resp = self.session.get(fx_url, timeout=15)
        except Exception as e:
            return False, f"签到请求失败: {e}"

        body = sign_resp.text
        print(f"  [签到] 响应: {body[:200]}")

        if any(k in body for k in ["今日已签", "今天已经", "已签到"]):
            return True, "今日已签到"
        if any(k in body for k in ["签到成功", "签到获得", "完成签到"]):
            return True, "签到成功"
        if "CDATA" in body or "succeed" in body.lower():
            return True, "签到成功"

        # 回头验证
        try:
            after = self.session.get(sign_url, timeout=15)
            if self._already_signed(after.text):
                return True, "签到成功"
        except Exception:
            pass

        return False, "签到请求无响应"

    def _build_fx_url(self):
        fh = self.formhash or ""
        return (f"{self.forum_url}/plugin.php?id=fx_checkin:checkin"
                f"&formhash={fh}&{fh}&infloat=yes"
                f"&handlekey=fx_checkin&inajax=1"
                f"&ajaxtarget=fwin_content_fx_checkin")

    @staticmethod
    def _already_signed(html):
        return any(k in html for k in [
            "今日已签到", "已经签到", "今日签过", "完成今日签到"])


# ========================= 主入口 =========================
def main():
    username = os.environ.get("FORUM_USERNAME", "").strip()
    password = os.environ.get("FORUM_PASSWORD", "").strip()
    cookie = os.environ.get("FORUM_COOKIE", "").strip()
    forum_url = os.environ.get("FORUM_URL", "https://www.wnflb2023.com").strip().rstrip("/")

    print("=" * 50)
    print(f"Discuz! 自动签到 - 福利吧 (fx_checkin)")
    print(f"论坛: {forum_url}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if not cookie and not password:
        print("❌ 请配置 FORUM_COOKIE (推荐) 或 FORUM_PASSWORD")
        sys.exit(1)

    signer = DiscuzSigner(forum_url=forum_url, username=username,
                          password=password, cookie=cookie)
    success, msg = signer.sign()

    login_method = "Cookie" if cookie else "账号密码"
    print()
    print(f"签到结果: {'✅ 成功' if success else '❌ 失败'} - {msg}")
    print()
    print("推送通知:")
    title = f"{'✅' if success else '❌'} 论坛签到{'成功' if success else '失败'}"
    content = (f"**论坛**: {forum_url}\n"
               f"**用户**: {username or '(Cookie 方式)'}\n"
               f"**登录方式**: {login_method}\n"
               f"**结果**: {'成功' if success else '失败'}\n"
               f"**详情**: {msg}\n"
               f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    send_notification(title, content)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
