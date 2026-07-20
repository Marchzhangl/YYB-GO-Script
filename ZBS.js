// name: 植白说
// cron: 32 6 * * *
const axios = require("axios");
const fs = require("fs");
const path = require("path");
// ====================== YYB Go 账号（环境变量 YYB_SERVER = 地址@微信账号标识，多行） ======================
const SERVERS = (process.env.YYB_SERVER || "")
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
if (!SERVERS.length) {
    console.error("未配置环境变量 YYB_SERVER，请设置后重试（格式：地址@微信账号标识，多行换行）");
    process.exit(1);
}
function parseYybGoEntry(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return { server: "", ref: "" };
    const atIndex = value.indexOf("@");
    if (atIndex === -1) {
        console.log("YYB_SERVER 格式应为 地址@微信账号标识，当前值: " + value);
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
async function getCode(server) {
    const { server: parsedServer, ref } = parseYybGoEntry(server);
    if (!parsedServer || !ref) return null;
    const url = "http://" + parsedServer + "/wxapp/getCode";
    try {
        const { data } = await axios.post(url, { ref, app_id: MINI_APP_ID }, { timeout: 20000, proxy: false });
        const code = data && data.data && data.data.result && data.data.result.code;
        if (!data || data.code !== 0 || !code) {
            console.log(parsedServer + " 获取code失败: " + JSON.stringify(data));
            return null;
        }
        console.log(parsedServer + " 获取code成功");
        return code;
    } catch (e) {
        console.log(parsedServer + " 获取code异常: " + e.message);
        return null;
    }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
let userIdx = 1;

// 直接通过 YYB Go 获取微信小程序 code

const MINI_APP_ID = "wx6b6c5243359fe265";
const API_BASE = "https://www.kozbs.com/demo/wx/";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "zbs_token_cache.json");
try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (e) {}
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254173b) XWEB/19027";
const defaultUserAgent = USER_AGENT;

function readTokenCache() {
    try {
        if (!fs.existsSync(TOKEN_CACHE_FILE)) return {};
        return JSON.parse(fs.readFileSync(TOKEN_CACHE_FILE, "utf8")) || {};
    } catch (e) {
        return {};
    }
}

function writeTokenCache(cache) {
    try {
        fs.writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2), "utf8");
    } catch (e) {
        console.log(`写入token缓存失败: ${e.message || e}`);
    }
}

function shortToken(token = "") {
    const value = String(token);
    return value ? `${value.slice(0, 6)}***${value.slice(-6)}` : "";
}

function maskPhone(phone = "") {
    return String(phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
}

function isTokenError(message) {
    return /(^|[^0-9])501([^0-9]|$)|token|登录|授权|未登录|失效|过期/i.test(String(message || ""));
}

class Task {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++;
        this.openid = String(openid || "").trim();
        this.token = "";
        this.userInfo = {};
    }

    async run() {
        const cached = this.getCachedToken();
        if (cached?.token) {
            this.token = cached.token;
            this.userInfo = cached.userInfo || {};
            console.log(`账号[${this.index}] 使用缓存token: ${shortToken(this.token)}`);
            if (!(await this.checkToken())) {
                this.removeCachedToken();
                console.log(`账号[${this.index}] 缓存token失效，重新登录`);
            }
        }

        if (!this.token) {
            await this.loginByWxCode();
            if (!this.token) return;
        }

        await this.getPoints("当前");
        await this.signIn();
        await this.getPoints("签到后");
    }

    get userId() {
        return this.userInfo?.userId || this.userInfo?.id || 1;
    }

    getCachedToken() {
        const cache = readTokenCache();
        return cache[this.openid] || null;
    }

    saveCachedToken() {
        if (!this.token) return;
        const cache = readTokenCache();
        cache[this.openid] = {
            token: this.token,
            userInfo: this.userInfo,
            updatedAt: new Date().toISOString(),
        };
        writeTokenCache(cache);
    }

    removeCachedToken() {
        const cache = readTokenCache();
        if (cache[this.openid]) {
            delete cache[this.openid];
            writeTokenCache(cache);
        }
        this.token = "";
        this.userInfo = {};
    }

    headers(extra = {}) {
        const headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://servicewechat.com/wx6b6c5243359fe265/171/page-frame.html",
            "xweb_xhr": "1",
            ...extra,
        };
        if (this.token) headers["X-Dts-Token"] = this.token;
        return headers;
    }

    async request(apiPath, { method = "GET", data = {}, auth = true } = {}) {
        const options = {
            method,
            url: new URL(apiPath, API_BASE).toString(),
            headers: this.headers(),
            timeout: 15000,
            validateStatus: () => true,
        };
        if (!auth) delete options.headers["X-Dts-Token"];
        if (method.toUpperCase() === "GET") options.params = data;
        else options.data = data;

        const { data: result, status } = await axios.request(options);
        if (status !== 200) throw new Error(`HTTP ${status}: ${JSON.stringify(result)}`);
        if (Number(result?.errno) !== 0) throw new Error(`${result?.errno ?? ""} ${result?.errmsg || result?.message || JSON.stringify(result)}`.trim());
        return result;
    }

    async getLoginCode() {
        return await getCode(this.server);
    }

    async loginByWxCode() {
        try {
            const code = await this.getLoginCode();
            const result = await this.request("auth/login_by_weixin", {
                method: "POST",
                auth: false,
                data: {
                    code,
                    userInfo: {},
                    shareUserId: 1,
                },
            });
            const token = result?.data?.token || "";
            if (!token) throw new Error(`登录响应未返回token: ${JSON.stringify(result)}`);
            this.token = token;
            this.userInfo = result?.data?.userInfo || {};
            this.saveCachedToken();
            console.log(`账号[${this.index}] 登录成功: ${this.userInfo.nickname || maskPhone(this.userInfo.mobile) || this.userId}`);
        } catch (e) {
            console.log(`账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async checkToken() {
        try {
            await this.request("user/getUserIntegral", {
                data: { userId: this.userId },
            });
            return true;
        } catch (e) {
            return false;
        }
    }

    async getPoints(prefix = "当前") {
        try {
            const result = await this.request("user/getUserIntegral", {
                data: { userId: this.userId },
            });
            const integer = result?.data?.integer ?? result?.data?.integral ?? result?.data?.point ?? "未知";
            console.log(`🌸账号[${this.index}] ${prefix}积分: ${integer}🎉`);
        } catch (e) {
            const message = String(e.message || e);
            console.log(`🌸账号[${this.index}] 获取积分失败: ${message}❌`);
            if (isTokenError(message)) this.removeCachedToken();
        }
    }

    async signIn() {
        try {
            const status = await this.request("home/signDay", {
                data: { userId: this.userId },
            });
            if (status?.data?.isSign) {
                console.log(`🌸账号[${this.index}] 今日已签到`);
                return;
            }

            await this.request("home/sign", {
                data: { userId: this.userId },
            });
            console.log(`🌸账号[${this.index}] 签到成功🎉`);
        } catch (e) {
            const message = String(e.message || e);
            if (/已签到|已签|重复/.test(message)) {
                console.log(`🌸账号[${this.index}] 今日已签到`);
                return;
            }
            console.log(`🌸账号[${this.index}] 签到失败: ${message}❌`);
            if (isTokenError(message)) this.removeCachedToken();
        }
    }
}

!(async () => {
    for (const user of SERVERS) {
        await new Task(user).run();
    }
})()
    .catch((e) => console.log(e))
    

