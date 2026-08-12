# 福利吧论坛自动签到（账号密码版）

基于 [appcctv/wnflb-checkin](https://github.com/appcctv/wnflb-checkin) 二次开发。
原版只支持 Cookie 签到，本版新增 **账号密码登录**：Cookie 过期后自动用账号密码重新登录，
海外或者风控 IP 登录需要验证码时用 [ddddocr](https://github.com/sml2h3/ddddocr) 自动识别。

论坛：`https://www.wnflb2023.com/` （Discuz! X3.4）

---

## 逆向分析结论（已确认的接口）

| 功能 | 方法 / 地址 | 说明 |
|------|------------|------|
| 登录页 | `GET member.php?mod=logging&action=login` | 返回 `formhash`、`loginhash` |
| 提交登录（首次） | `POST member.php?mod=logging&action=login&loginsubmit=yes&loginhash={loginhash}` | 表单字段：`formhash` `username` `password` `questionid` `answer` `cookietime` |
| 验证码校验 | `GET misc.php?mod=seccode&action=check&inajax=1&modid=member::logging&idhash={idhash}&secverify={code}` | 浏览器在最终提交前调用，校验验证码并在 cookie 写入 `seccode<idhash>` 标记 |
| 提交登录（二次挑战） | `POST member.php?mod=logging&action=login&loginsubmit=yes&loginhash={loginhash}&inajax=1` | **海外或者风控 IP 被要求验证码时**：凭据已由 `auth` 令牌关联，**不重发账号密码**；字段为 `formhash` `referer` `auth` `questionid` `answer` `seccodehash` `seccodemodid=member::logging` `seccodeverify` |
| 验证码图片 | `GET misc.php?mod=seccode&update={rand}&idhash={idhash}` | 同一 session 拉取，**必须带同源 Referer**，否则被 WAF 返回 `Access Denied` |
| 签到 | `GET plugin.php?id=fx_checkin:checkin&formhash={A}&{B}&inajax=1` | `fx_checkin` 插件，formhash 从首页 HTML 里 `fx_checkin:checkin&formhash=...` 提取 |

### 海外或者风控 IP 的「二次验证码挑战」流程（已实战验证）

论坛按 **IP 信誉**动态决定是否要验证码。被判定为风险 IP（例如 GitHub Actions 的运行机）时，
登录**提交之后**才下发"请输入验证码后继续登录" + 一个 `auth` 一次性令牌（藏在挑战页隐藏域 `name="auth"`）。
脚本处理步骤：

1. 首次 `POST` 提交账号密码（不带验证码）→ 被挑战，从响应取 `auth`；
2. 带 `auth` 拉挑战页，解析出 `formhash` / `loginhash` / `idhash`；
3. 拉取验证码图片（ddddocr 识别），先调 `action=check` 校验通过；
4. 二次 `POST` 提交（`auth` + 验证码，**不重发账号密码**，URL 带 `inajax=1`）完成登录。

> 验证码是**条件触发**的：登录过的 IP 不需要验证码，海外或者风控 IP 登录才需要）。
> 脚本对此做了**自适应**：登录页出现验证码字段就识别并提交；被服务端二次挑战也能自动走完上述流程。

---

## 方式一：GitHub Actions（推荐）

1. **Fork** 本仓库到你的账号。
2. 进入 `Settings → Secrets and variables → Actions → New repository secret`，添加：
   - `FORUM_USERNAME`：论坛账号（**必填**）
   - `FORUM_PASSWORD`：论坛密码（**必填**）
   - `FORUM_COOKIE`：（可选）直接填 Cookie 字符串，优先级高于下面两种方式
   - `PUSHPLUS_TOKEN` / `SERVERCHAN_KEY`：（可选）微信推送通知
3. 进入 `Actions` 标签页，手动 **Run workflow** 跑一次验证；之后会按 cron
   （北京时间 01:00 / 22:00）自动运行。
4. **Cookie 通过 GitHub Cache 跨运行持久化**：首次运行走账号密码+验证码登录，
   成功后 Cookie 经 `actions/cache` 缓存；之后的运行自动恢复复用，**跳过登录与验证码**直接签到。
   Cookie 过期（或 Cache 超过保留期被清理）时，脚本会检测失效并自动重新登录一次。
   > 缓存采用**固定 key** + 仅在「重新登录成功」时删旧存新：cookie 没过期不生成新缓存、生成新缓存的同时旧的被删除，**不会无限累积**。

> ⚠️ **安全建议：Fork 后把仓库改为私有（强烈推荐）**。Cache 里存的是含登录会话令牌（`auth`）的 `cookies.json`，
> GitHub 官方明确：**公开仓库中任何人都能通过 fork/PR 读取 cache 内容**，等于把登录态暴露给所有人。
> 请按下方「安全建议」一节把本仓库设为 **Private**，cache 即仅你自己可见，自动刷新又零维护。
> 注意：`upload/download-artifact@v4` 默认只在同一 workflow run 内生效、**无法跨 run 复用**，故此处改用 `actions/cache`（支持跨运行命中）。
> 本地（固定 IP）运行同样由 `cookies.json` 复用。若 Actions 连不上论坛（网络原因），可改用本地运行或自建国内 runner。

---

## 方式二：本地运行

```bash
pip install -r requirements.txt

# 方式 A：用账号密码
python wnflb_checkin.py --username "你的账号" --password "你的密码"

# 方式 B：直接用 Cookie（兼容旧版）
FORUM_COOKIE="xxx=yyy; ..." python wnflb_checkin.py

# 仅解析登录页、确认 formhash/loginhash/验证码（无需账号，排查用）
python wnflb_checkin.py --inspect
```

Windows 用户也可双击 `test_local.bat`，按提示输入账号密码（密码不会被写入文件）。

登录成功后会在当前目录生成 `cookies.json`，下次运行优先复用，**无需重复输入密码**。


## 安全建议（强烈推荐 Fork 后改为私有）

Cookie 持久化依赖 `actions/cache`，而 cache 里存的是含登录会话令牌（`auth`）的 `cookies.json`。

**为什么必须私有**：GitHub 官方文档原文——*"Anyone with read access can create a pull request on a repository and access the contents of a cache."*
即**公开仓库中任何人都能通过 fork 你的仓库并发起 PR 来读取 cache 内容**。所以公开仓库用 cache 存登录态 = 把账号会话令牌暴露给所有人。
（日志本身已不再打印令牌，但 cache 这份副本是另一处泄漏面，只有私有能根治。）

**怎么改成私有（3 步）**：

1. 进入本仓库页面，点右上角 **⚙️ Settings（设置）**；
2. 拉到页面**最底部**的 **⚠️ Danger Zone（危险区域）**，点 **Change repository visibility（更改仓库可见性）**；
3. 在弹出框里选 **Private（私有）**，按提示输入仓库名 `wnflb-checkin` 确认。

> 若你是从公开仓库 **Fork** 来的，Fork 默认也是**公开**的，按上面 3 步改一次即可。
> 私有后的 Fork 不影响你之后从上游（`appcctv/wnflb-checkin`）同步代码更新。

改完后：cache 只有你和协作者可见，自动刷新、零维护，是最省心的自用方案。

**其他可选方案（如坚持公开仓库）**：

- **用 `FORUM_COOKIE` secret 替代 cache**：手动把 Cookie 字符串填进 Repository secret（优先级高于 cache），
  secret 加密存储、日志自动打码、fork/PR 读不到；缺点是不自动刷新，cookie 过期需你手动去 Settings 改一次。
- **固定 IP 跳过验证码**：用本地运行或自建国内 runner，cookie 存本地文件长期复用，连 cache 都不需要。


## 说明 / 注意

- 论坛页面为 GBK 编码，脚本已做解码兼容。
- 验证码识别率依赖 ddddocr，极端情况下可能失败；脚本会重试 3 次，仍失败则报错退出。
- 若论坛改版（formhash 字段名、签到插件变动），先看 `--inspect` 输出，再相应调整正则。
