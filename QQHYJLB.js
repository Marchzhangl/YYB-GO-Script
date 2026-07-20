// name: 洽洽会员俱乐部
// cron: 24 9 * * *
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

const MINI_APP_ID = "wxc72491b6cd007333";
const PAGE_VERSION = "516";
const TENANT_ID = "1";
const USER_ID = "c10cff02123a9e2697d875262612399d";
const VIP_BASE = "https://vip.qiaqiafood.com";
const MOBILE_BASE = "https://qq-tasting-hall.qiaqiafood.com/mobile";
const TOKEN_CACHE_FILE = path.join(__dirname, "token_caches", "qiaqia_token_cache.json");
try { fs.mkdirSync(path.dirname(TOKEN_CACHE_FILE), { recursive: true }); } catch (e) {}
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) MicroMessenger/3.9.12 MiniProgramEnv/Windows WindowsWechat/WMPF";

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

function getSessionId(headers = {}) {
    const cookies = headers["set-cookie"] || headers["Set-Cookie"] || headers["set-Cookie"];
    const list = Array.isArray(cookies) ? cookies : (cookies ? [cookies] : []);
    for (const cookie of list) {
        const match = String(cookie).match(/(?:^|;\s*)SESSION=([^;]+)/);
        if (match) return match[1];
    }
    return "";
}

function formBody(data = {}) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(data)) {
        if (value !== undefined && value !== null) params.append(key, String(value));
    }
    return params;
}

function today() {
    const date = new Date();
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

function isLoginError(message) {
    return /登录|授权|SESSION|token|-2|401|403|expire|过期|失效/i.test(String(message || ""));
}

class Task {
    constructor(openid) {
        this.server = openid;
        const _yyb = parseYybGoEntry(this.server);
        this.ref = _yyb.ref;
        this.openid = _yyb.ref;
        this.index = userIdx++;
        this.openid = String(openid || "").trim();
        this.session = {};
    }

    async run() {
        const cached = this.getCachedToken();
        if (cached) {
            this.session = cached;
            console.log(`账号[${this.index}] 使用缓存登录态`);
            if (!(await this.checkSession())) {
                this.removeCachedToken();
                console.log(`账号[${this.index}] 缓存登录态失效，重新登录`);
            }
        }

        if (!this.session.sessionId) {
            await this.login();
            if (!this.session.sessionId) return;
        }

        await this.doSign();
        this.saveCachedToken();
    }

    getCachedToken() {
        const cache = readTokenCache();
        return cache[this.openid] || null;
    }

    saveCachedToken() {
        if (!this.session.sessionId) return;
        const cache = readTokenCache();
        cache[this.openid] = {
            sessionId: this.session.sessionId,
            token: this.session.token || "",
            loginId: this.session.loginId || "",
            customerId: this.session.customerId || "",
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
        this.session = {};
    }

    async getLoginCode() {
        return await getCode(this.server);
    }

    commonHeaders(extra = {}) {
        return {
            "User-Agent": USER_AGENT,
            "Referer": `https://servicewechat.com/${MINI_APP_ID}/${PAGE_VERSION}/page-frame.html`,
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "from_env": "app",
            ...extra,
        };
    }

    async login() {
        try {
            await this.loginUpms();
            await this.loginMobile();
            this.saveCachedToken();
            console.log(`账号[${this.index}] 登录成功`);
        } catch (e) {
            console.log(`账号[${this.index}] 登录失败: ${e.message || e}`);
        }
    }

    async loginUpms() {
        const code = await this.getLoginCode();
        const res = await axios.post(`${VIP_BASE}/upms/wechat/login/code`, formBody({
            code,
            tenantId: TENANT_ID,
            appId: MINI_APP_ID,
            componentAppId: MINI_APP_ID,
        }), {
            headers: this.commonHeaders({ Authorization: this.session.token || "" }),
            timeout: 20000,
            validateStatus: () => true,
        });

        if (res.status !== 200 || String(res.data?.status) !== "0") {
            throw new Error(res.data?.msg || `upms登录失败 HTTP ${res.status}`);
        }

        const payload = res.data?.data?.data || res.data?.data || {};
        this.session.token = payload.token || this.session.token || "";
        this.session.loginId = payload.loginId || payload.account?.loginId || this.session.loginId || "";
        const upmsSession = getSessionId(res.headers);
        if (upmsSession) this.session.sessionId = upmsSession;
    }

    async loginMobile() {
        const code = await this.getLoginCode();
        const res = await axios.post(`${MOBILE_BASE}/wechat/login`, formBody({
            code,
            userId: USER_ID,
        }), {
            headers: this.commonHeaders(),
            timeout: 20000,
            validateStatus: () => true,
        });

        if (res.status !== 200 || String(res.data?.status) !== "0") {
            throw new Error(res.data?.msg || `mobile登录失败 HTTP ${res.status}`);
        }

        const mobileSession = getSessionId(res.headers);
        if (mobileSession) this.session.sessionId = mobileSession;
        this.session.customerId = res.data?.customer?.id || this.session.customerId || "";
    }

    async mobilePost(apiPath, data = {}) {
        if (!this.session.sessionId) throw new Error("缺少SESSION");
        const res = await axios.post(`${MOBILE_BASE}${apiPath}`, formBody({
            ...(data || {}),
            userId: USER_ID,
        }), {
            headers: this.commonHeaders({
                Cookie: `SESSION=${this.session.sessionId}`,
                Authorization: this.session.token || "",
            }),
            timeout: 20000,
            validateStatus: () => true,
        });

        const newSession = getSessionId(res.headers);
        if (newSession) this.session.sessionId = newSession;

        if (res.status !== 200) throw new Error(`HTTP ${res.status}`);
        if (String(res.data?.status) === "-2") throw new Error("登录态失效(-2)");
        if (String(res.data?.status) !== "0") {
            throw new Error(res.data?.msg || `接口异常: ${res.data?.status || "unknown"}`);
        }
        return res.data;
    }

    async checkSession() {
        try {
            await this.mobilePost("/promotion/sign/list");
            return true;
        } catch (e) {
            return false;
        }
    }

    async getSignList() {
        const data = await this.mobilePost("/promotion/sign/list");
        return data?.data || [];
    }

    async getSignConfig() {
        try {
            const data = await this.mobilePost("/uc/sign/getConfigByUserId");
            return data?.data || {};
        } catch (e) {
            return {};
        }
    }

    async doSign() {
        try {
            const signList = await this.getSignList();
            const signedToday = Array.isArray(signList) && signList.some((item) => String(item?.signTime || "").slice(0, 10) === today());
            const config = await this.getSignConfig();
            if (signedToday) {
                console.log(`账号[${this.index}] 今日已签到，连续${signList[signList.length - 1]?.signContinuousDay || 0}天`);
                return;
            }

            const res = await this.mobilePost("/promotion/sign/sign");
            const point = res?.data?.point || config?.point || "";
            console.log(`账号[${this.index}] 签到成功${point ? `，积分+${point}` : ""}`);
        } catch (e) {
            const message = e.message || e;
            if (/已签到|每天只能签到一次|重复|今日已/.test(String(message))) {
                console.log(`账号[${this.index}] 今日已签到`);
                return;
            }
            console.log(`账号[${this.index}] 签到失败: ${message}`);
            if (isLoginError(message)) this.removeCachedToken();
        }
    }
}

!(async () => {
    
    for (const openid of SERVERS) {
        await new Task(openid).run();
    }
})()
    .catch((e) => console.log(e.message || e))
