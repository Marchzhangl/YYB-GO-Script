/*
------------------------------------------
@Author: anonymous
@Date: 2026.07.15
@Description: 顾家小程序签到
cron: 48 14 * * *
------------------------------------------
顾家小程序签到 v1.1.0

功能：自动执行顾家（顾家家居）小程序每日签到并查询积分/会员信息，支持多账号执行。

配置说明：
1. 微信 code 网关：
   wx_server_url                                       必填，自建授权服务器域名
   - 示例：http://127.0.0.1:8000
   - 脚本会自动拼接 /wxapp/getCode
   - 请求格式：POST {网关}/wxapp/getCode
   - 请求体：{"app_id": "wx0770280d160f09fe", "ref": "openid"}

2. 账号变量：
   gjjj_openid                                         推荐，顾家小程序专属账号变量
   - 多账号支持使用 &、英文逗号、中文逗号或换行分隔
   - 示例：openid_a&openid_b 或 openid_a,openid_b

3. 依赖安装：
   axios 
   - 安装命令：npm install axios
   - 若使用青龙面板，在依赖管理处添加 axios 安装即可。

4. 青龙任务建议：
   名称：顾家小程序签到
   命令：node gjjj.js
   定时：每天运行 1 次即可，具体时间自行调整
------------------------------------------
*/

const axios = require("axios");
const crypto = require("crypto");

const MINI_APP_ID = "wx0770280d160f09fe";
const PAGE_VERSION = "293";
const API_BASE = "https://mc.kukahome.com/club-server";
const INTEGRAL_BASE = "https://mc.kukahome.com/integral-server";
const BRAND_CODE = "K001";
const SMALL_APPLICATION_ID = "667516";
const SMALL_CRYPTO = "FH3yRrHG2RfexND8";
const VERSION_NUMBER = "2.0.184";
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";
// ====================== YYB Go 账号（环境变量 YYB_GO = 地址@微信账号标识，多行） ======================
const SERVERS = (process.env.YYB_GO || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("未配置环境变量 YYB_GO，请设置后重试（格式：地址@微信账号标识，多行换行）");
    process.exit(1);
}
function parseYybGoEntry(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "" };
    const atIndex = value.indexOf("@");
    if (atIndex === -1) {
        console.log("YYB_GO 格式应为 地址@微信账号标识，当前值: " + value);
        return { server: "", ref: "" };
    }
    let server = value.slice(0, atIndex).trim();
    const ref = value.slice(atIndex + 1).trim();
    if (server.startsWith("http://")) server = server.slice(7);
    else if (server.startsWith("https://")) server = server.slice(8);
    server = server.replace(/\/+$/, "");
    if (!server || !ref) return { server: "", ref: "" };
    return { server, ref };
}

// ---- 运行环境 ----
class Env {
  constructor(name) {
    this.name = name;
    this.userIdx = 1;
    this.userList = [];
    this.startTime = Date.now();
    this.log(`============ ${name} ============`);
  }

  log(...args) {
    console.log(args.join(" "));
  }

  checkEnv(name) {
    const raw = process.env[name] || "";
    this.userList = raw
      .split(/[\n&,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!this.userList.length) {
      this.log(`未找到环境变量 [${name}]，请先配置账号`);
      process.exit(0);
    }
    this.log(`共 ${this.userList.length} 个账号`);
  }

  done() {
    const cost = ((Date.now() - this.startTime) / 1000).toFixed(2);
    this.log(`============ ${this.name} 执行结束，耗时 ${cost}s ============`);
  }
}

const $ = new Env("顾家小程序签到");

function md5(input) {
  return crypto.createHash("md5").update(String(input)).digest("hex");
}

function isObject(val) {
  return Object.prototype.toString.call(val) === "[object Object]";
}

function buildParameterBase(data) {
  if (!data) return null;
  if (Array.isArray(data) || typeof data === "string") return null;
  if (!isObject(data)) return null;
  const keys = Object.keys(data).sort((a, b) => {
    const ac = [...a].map((ch) => ch.charCodeAt(0));
    const bc = [...b].map((ch) => ch.charCodeAt(0));
    for (let i = 0; i < Math.min(ac.length, bc.length); i++) {
      if (ac[i] !== bc[i]) return ac[i] - bc[i];
    }
    return ac.length - bc.length;
  });
  const pairs = [];
  for (const key of keys) {
    const value = data[key];
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) continue;
    if (typeof value === "object" && value !== null) {
      pairs.push(`${key}=${JSON.stringify(value)}`);
      continue;
    }
    if (typeof value === "number" && value === 0) {
      pairs.push(`${key}=0`);
      continue;
    }
    pairs.push(`${key}=${value}`);
  }
  return pairs.length ? pairs.join("&") : null;
}

function buildParameterSign(data, timestamp) {
  const base = buildParameterBase(data);
  if (!base) return "";
  const salt = String(timestamp).substring(4, 10);
  return md5(md5(base) + salt);
}

class Task {
  constructor(openid) {
    this.index = $.userIdx++;
    this.openid = String(openid || "").trim();
    this.tmpToken = "";
    this.accessToken = "";
    this.memberId = "";
    this.userInfo = {};
  }

  applyToken(data = {}) {
    this.accessToken = data.accessToken || data.token || this.accessToken;
    this.memberId = String(data.memberId || this.memberId || "");
  }

  async request({ method = "POST", url, data = {}, params = {}, withAuth = true, withTmpToken = true }) {
    const timestamp = Date.now();
    const sign = md5(`${SMALL_APPLICATION_ID}${SMALL_CRYPTO}${timestamp}`).toLowerCase();
    const bodyForSign = method.toUpperCase() === "GET" ? params : data;
    const parameterSign = buildParameterSign(bodyForSign, timestamp);
    const headers = {
      "User-Agent": USER_AGENT,
      Referer: `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
      Accept: "application/json, text/plain, */*",
      "Content-Type": "application/json",
      "X-Customer": this.memberId || "",
      brandCode: BRAND_CODE,
      appid: SMALL_APPLICATION_ID,
      "E-Opera": "",
      "xweb_xhr": "1",
      sign,
      timestamp,
      versionNumber: VERSION_NUMBER,
    };
    if (parameterSign) headers.parameterSign = parameterSign;
    if (withAuth && this.accessToken) headers.AccessToken = this.accessToken;
    if (withTmpToken && this.tmpToken) headers.tmpToken = this.tmpToken;

    const res = await axios.request({
      method,
      url,
      data,
      params,
      headers,
      timeout: 20000,
      validateStatus: () => true,
    });

    if (res.status !== 200) {
      throw new Error(`HTTP ${res.status}: ${JSON.stringify(res.data)}`);
    }
    const result = res.data || {};
    if (result.code !== undefined && ![0, 401, 402, 515].includes(Number(result.code))) {
      const err = new Error(result.message || result.msg || JSON.stringify(result));
      err.rawResponse = result;
      throw err;
    }
    return result;
  }

  async getWxCode() {
    const { server, ref } = parseYybGoEntry(SERVERS[this.index - 1] || "");
    if (!server || !ref) throw new Error("YYB_GO 配置解析失败");
    const url = "http://" + server + "/wxapp/getCode";
    const res = await axios.request({
      method: "POST",
      url,
      data: { app_id: MINI_APP_ID, ref },
      headers: { "Content-Type": "application/json" },
      timeout: 20000,
      validateStatus: () => true,
    });
    if (res.status !== 200) {
      throw new Error(`getCode HTTP ${res.status}: ${JSON.stringify(res.data)}`);
    }
    const body = res.data || {};
    if (Number(body.code) !== 0) {
      throw new Error(`getCode失败: ${body.msg || JSON.stringify(body)}`);
    }
    const code = body?.data?.result?.code || body?.data?.code;
    if (!code) throw new Error(`wx_server 未返回 code: ${JSON.stringify(body)}`);
    return code;
  }

  async login() {
    const code = await this.getWxCode();
    const identify = await this.request({
      method: "POST",
      url: `${API_BASE}/api/user/identify`,
      params: { code },
      withAuth: false,
      withTmpToken: false,
    });
    if (identify.code !== 0 || !identify.data) {
      throw new Error(`identify失败: ${identify.message || JSON.stringify(identify)}`);
    }
    if (Number(identify.data.status) !== 4) {
      throw new Error(`登录状态异常: status=${identify.data.status}`);
    }
    this.tmpToken = identify.data.token || "";
    if (!this.tmpToken) throw new Error("identify未返回tmpToken");

    const auth = await this.request({
      method: "POST",
      url: `${API_BASE}/api/user/authorizeLogin`,
      data: { source: "顾家小程序", contentName: "" },
      withAuth: false,
      withTmpToken: true,
    });
    if (auth.code !== 0 || !auth.data?.token) {
      throw new Error(`authorizeLogin失败: ${auth.message || JSON.stringify(auth)}`);
    }
    this.accessToken = auth.data.token;
    this.memberId = String(auth.data.memberId || "");
    this.tmpToken = "";
  }

  async getUserInfo() {
    const info = await this.request({
      method: "POST",
      url: `${API_BASE}/api/user/info`,
      data: {},
      withAuth: true,
      withTmpToken: false,
    });
    if (!info.data) throw new Error("user/info返回为空");
    this.userInfo = info.data;
    this.applyToken(info.data);
    const openidMask = this.openid.length >= 12
      ? this.openid.slice(0, 6) + "..." + this.openid.slice(-6)
      : this.openid;
    const nick = this.userInfo.nickName || this.userInfo.name || "";
    const mobile = this.userInfo.mobile || "";
    let label = `【${openidMask}】`;
    if (nick) label += `(${nick})`;
    if (mobile) label += ` 手机：${mobile}`;
    $.log(`账号[${this.index}] 👤 用户: ${label}`);
  }

  async ensureLogin() {
    await this.login();
    await this.getUserInfo();
    $.log(`账号[${this.index}] ✅ 登录成功`);
  }

  async getPoints() {
    const ret = await this.request({
      method: "POST",
      url: `${API_BASE}/front/member/personalCenter`,
      data: { t: Date.now() },
      withAuth: true,
      withTmpToken: false,
    });
    if (!ret || ret.point === undefined) throw new Error("查询积分失败");
    return Number(ret.point || 0);
  }

  async getSignCalendar() {
    const ret = await this.request({
      method: "GET",
      url: `${INTEGRAL_BASE}/user/sign/calendar`,
      params: {},
      withAuth: true,
      withTmpToken: false,
    });
    if (ret.code !== 0) throw new Error(ret.message || ret.msg || "查询签到日历失败");
    return ret.data || {};
  }

  async sign() {
    let ret;
    try {
      ret = await this.request({
        method: "POST",
        url: `${INTEGRAL_BASE}/scenePoint/scene/point`,
        data: {
          scene: "sign",
          brandCode: BRAND_CODE,
        },
        withAuth: true,
        withTmpToken: false,
      });

      if (ret.code === 0) {
        const gain = typeof ret.data === "number" ? ret.data : null;
        return { status: "success", ret, gain };
      }

      // request() 对 0/401/402/515 不抛异常，但仍需处理非 0 的情况
      const msg = ret.message || ret.msg || JSON.stringify(ret);
      if (/已签|重复|already|今日/.test(msg)) {
        return { status: "already", ret, gain: null };
      }

      throw new Error(msg);
    } catch (e) {
      // request() 对非 0/401/402/515 的 code 会直接 throw，需要在这里兜底判断"已签到"
      const msg = e.message || String(e);
      if (/已签|重复|already|今日/.test(msg)) {
        return { status: "already", ret: e.rawResponse, gain: null };
      }
      $.log(`账号[${this.index}] ❌ 签到接口返回失败: ${msg}`);
      throw e;
    }
  }

  async run() {
    try {
      await this.ensureLogin();
      const before = await this.getPoints().catch(() => null);
      if (before !== null) $.log(`账号[${this.index}] 💰 签到前积分: 【${before}】`);

      const cal = await this.getSignCalendar().catch(() => null);
      if (cal === null) {
        $.log(`账号[${this.index}] ⚠️ 签到日历查询失败，将尝试执行签到`);
      }

      let signRes = null;
      let cal2 = cal;
      const signed = cal ? !!cal.isTodaySigned : null;
      if (signed !== true) {
        // 日历未显示已签到才调用签到接口（正式运行行为）
        signRes = await this.sign();
        // 签到后重新查日历，用最新的 isTodaySigned 验证结果、signCount 展示天数
        cal2 = await this.getSignCalendar().catch(() => null);
      }
      const after = await this.getPoints().catch(() => before);

      // 以接口真实返回为准：接口已签到 / 或日历已签且未调用接口，均判定为今日已签到
      if ((signRes && signRes.status === "already") || (signed === true && !signRes)) {
        $.log(`账号[${this.index}] 📝 每日签到： ⚠️ 今日已签到`);
      } else {
        // 接口返回签到成功，再用日历 isTodaySigned 做一次确认
        const signConfirmed = cal2 ? !!cal2.isTodaySigned : true;
        if (!signConfirmed) {
          if (cal2 === null) {
            $.log(`账号[${this.index}] 📝 每日签到： ⚠️ 签到后日历查询失败，无法确认是否生效`);
          } else {
            $.log(`账号[${this.index}] 📝 每日签到： ❌ 签到接口返回成功但日历未确认`);
          }
        } else if (signRes && typeof signRes.gain === "number" && signRes.gain > 0) {
          // 本次获得积分取自签到接口返回的 data 字段
          $.log(`账号[${this.index}] 📝 每日签到： 🎉 签到成功 (+${signRes.gain}积分)`);
        } else {
          $.log(`账号[${this.index}] 📝 每日签到： 🎉 签到成功`);
        }
      }

      if (after !== null) {
        $.log(`账号[${this.index}] 💰 签到后积分: 【${after}】`);
        $.log(`账号[${this.index}] 💰 总积分: 【${after}】`);
      }
      if (cal2 && cal2.signCount !== undefined && cal2.signCount !== null) {
        $.log(`账号[${this.index}] 📅 累计签到: 【${cal2.signCount}】天`);
      }
    } catch (e) {
      const msg = e.message || String(e);
      $.log(`账号[${this.index}] 执行失败: ${msg}`);
    }
  }
}

!(async () => {
  $.checkEnv(CK_NAME);
  for (const openid of $.userList) {
    await new Task(openid).run();
  }
})()
  .catch((e) => $.log(e.message || e))
  .finally(() => $.done());
