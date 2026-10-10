// Flow 解释器：按顺序执行 plan 里用数据定义的步骤。
//
// 一次迭代：取数据集的行 → 求流程变量 → （需要时）执行初始化段 → 执行每次迭代的步骤。
// 每一步：{{变量}} 替换 → 发请求 → check → 提取变量 → 等待 thinkTimeMs。
// 变量按求值顺序分层，后写的覆盖先写的（契约 §3.1「变量」）：
//   环境变量 → 数据集的行 → 流程变量 → 初始化段的输出（每个 VU 保留） → 步骤提取（本次迭代）
// 某一步的 check 没通过时，本次迭代剩下的步骤不再执行
// （后面的步骤通常依赖前面提取到的变量，继续发只会产生无意义的请求）。
//
// 调试模式（plan.debug 存在，契约 §3.5、§4、§5.1）走的是同一套代码，只多做三件事：
// 不等待 thinkTime、保留响应体、把每一步的请求 / 响应 / 检查 / 变量记录下来交给 runner 输出。

import http from 'k6/http';
import exec from 'k6/execution';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

// {{名称}} 或 {{$动态变量(参数)}}；名称两侧允许空格，参数里不能有花括号和括号（契约 §3.1「变量」）
const VAR_PATTERN = /\{\{\s*(\$?[^{}\s()]+(?:\([^{}()]*\))?)\s*\}\}/g;
const DYNAMIC_PATTERN = /^\$([A-Za-z]+)(?:\(([^{}()]*)\))?$/;
const REDIRECT_STATUSES = [301, 302, 303, 307, 308];
const ALNUM = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';

// 每个 VU 一份（模块级状态）：流程 key → { vars: 初始化段提取到的变量, at: 初始化成功的时间, jar: 这个流程的 Cookie 罐 }。
// 按流程分开存：时间上不重叠的 scenario 会复用 VU，不分开会把上一个流程的 token 带进下一个
const vuState = {};

function pad(n, width) {
  let s = String(n);
  while (s.length < width) s = `0${s}`;
  return s;
}

function formatDate(d, fmt) {
  return fmt.replace(/yyyy|MM|dd|HH|mm|ss|SSS/g, (t) => {
    if (t === 'yyyy') return pad(d.getFullYear(), 4);
    if (t === 'MM') return pad(d.getMonth() + 1, 2);
    if (t === 'dd') return pad(d.getDate(), 2);
    if (t === 'HH') return pad(d.getHours(), 2);
    if (t === 'mm') return pad(d.getMinutes(), 2);
    if (t === 'ss') return pad(d.getSeconds(), 2);
    return pad(d.getMilliseconds(), 3);
  });
}

function intArg(s) {
  if (!/^-?\d+$/.test(s)) return null;
  const n = parseInt(s, 10);
  return Number.isSafeInteger(n) ? n : null;
}

function uuid() {
  // 全局 webcrypto；不要 import 'k6/crypto' 成 crypto，会把全局的遮住
  return crypto.randomUUID();
}

// 返回 null 表示写法不认识：保留原样，和未定义的变量一样能从请求里看出来。
// 参数规则和后端预检（server/variables.py）一致
const DYNAMIC = {
  timestamp: (args) => (args.length === 0 ? String(Math.floor(Date.now() / 1000)) : null),
  timestampMs: (args) => (args.length === 0 ? String(Date.now()) : null),
  isoTimestamp: (args) => (args.length === 0 ? new Date().toISOString() : null),
  // 格式里可能有逗号，括号里的全部内容都是格式
  date: (args, ctx, raw) => formatDate(new Date(), raw || 'yyyy-MM-dd'),
  uuid: (args) => (args.length === 0 ? uuid() : null),
  guid: (args) => (args.length === 0 ? uuid() : null),
  randomUUID: (args) => (args.length === 0 ? uuid() : null),
  randomInt: (args) => {
    if (args.length !== 0 && args.length !== 2) return null;
    const min = args.length ? intArg(args[0]) : 0;
    const max = args.length ? intArg(args[1]) : 1000;
    if (min === null || max === null || min > max) return null;
    return String(min + Math.floor(Math.random() * (max - min + 1)));
  },
  randomString: (args) => {
    if (args.length > 1) return null;
    const len = args.length ? intArg(args[0]) : 8;
    if (len === null || len < 1 || len > 256) return null;
    let s = '';
    for (let i = 0; i < len; i++) s += ALNUM[Math.floor(Math.random() * ALNUM.length)];
    return s;
  },
  vu: (args) => (args.length === 0 ? String(exec.vu.idInTest) : null),
  iteration: (args) => (args.length === 0 ? String(exec.vu.iterationInScenario) : null),
  runId: (args, ctx) => (args.length === 0 ? String(ctx.runId) : null),
};

function dynamicValue(ref, ctx) {
  const m = DYNAMIC_PATTERN.exec(ref);
  if (!m || !Object.prototype.hasOwnProperty.call(DYNAMIC, m[1])) return null;
  const raw = m[2] === undefined ? '' : m[2].trim();
  const args = raw === '' ? [] : raw.split(',').map((a) => a.trim());
  return DYNAMIC[m[1]](args, ctx, raw);
}

/** 替换 {{变量}} 和 {{$动态变量}}；不存在时保留原样，方便在日志和目标端看出问题。 */
export function render(template, vars, ctx) {
  if (typeof template !== 'string' || template.indexOf('{{') === -1) return template;
  return template.replace(VAR_PATTERN, (whole, ref) => {
    if (ref[0] === '$') {
      const v = dynamicValue(ref, ctx);
      return v === null ? whole : v;
    }
    return Object.prototype.hasOwnProperty.call(vars, ref) ? vars[ref] : whole;
  });
}

function hasVar(s) {
  return typeof s === 'string' && s.indexOf('{{') !== -1;
}

/**
 * 把 URL 里的非 ASCII 字符和空白按 UTF-8 百分号编码（和 Postman / Apifox 一致）。
 * k6 不会替我们编码，原样发出去的中文 query 会被 uvicorn 等服务直接以 400 拒绝。
 * 已经写好的 %XX 和 ASCII 符号原样保留，不会二次编码。
 */
export function encodeUrl(url) {
  return url.replace(/[^\x21-\x7E]/gu, (c) => encodeURIComponent(c));
}

/** application/x-www-form-urlencoded 的编码（WHATWG）：除字母数字和 *-._ 外都编码，空格为 +。 */
function encodeFormComponent(s) {
  return encodeURIComponent(s)
    .replace(/[!'()~]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)
    .replace(/%20/g, '+');
}

/** multipart 里 name / filename 的转义（和浏览器一致）。 */
function escapeQuoted(s) {
  return s.replace(/"/g, '%22').replace(/\r/g, '%0D').replace(/\n/g, '%0A');
}

/**
 * 把 JSON 路径换成 k6 res.json() 认的 GJSON 写法：$.a.b[0]['c.d'] → a.b.0.c\.d。
 * 只有 $ / $. / $[ 开头才是 JSONPath 的根（$id、$ref 这种键名本身就以 $ 开头）；
 * GJSON 的条件查询 #(...) 里可能出现 [，那种写法原样交给 GJSON。
 */
export function toGjsonPath(expr) {
  let p = String(expr).trim();
  const jsonPath = p === '$' || p.indexOf('$.') === 0 || p.indexOf('$[') === 0;
  if (jsonPath) p = p.slice(1);
  if (jsonPath || (p.indexOf('[') !== -1 && p.indexOf('#(') === -1)) {
    p = p
      .replace(/\[\s*(\d+)\s*\]/g, '.$1')
      .replace(/\[\s*'([^']*)'\s*\]|\[\s*"([^"]*)"\s*\]/g, (m, a, b) => `.${(a !== undefined ? a : b).replace(/[\\.*?|#@!]/g, '\\$&')}`);
  }
  // 旧引擎按点切分后丢掉空段，所以 a..b、a.b. 这种写法以前也能用
  if (!/[\\"'(]/.test(p)) return p.split('.').filter((part) => part !== '').join('.');
  return p.replace(/^\./, '');
}

/** 合并请求头，名称不区分大小写，后者覆盖前者。 */
function mergeHeaders(envHeaders, stepHeaders) {
  const out = {};
  const index = {};
  for (const src of [envHeaders || {}, stepHeaders || {}]) {
    for (const name of Object.keys(src)) {
      const lower = name.toLowerCase();
      if (index[lower] !== undefined) delete out[index[lower]];
      index[lower] = name;
      out[name] = String(src[name]);
    }
  }
  return { headers: out, index };
}

function looksLikeJson(body) {
  const c = body.trim()[0];
  return c === '{' || c === '[';
}

function short(text, max) {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function randomHex(len) {
  let s = '';
  for (let i = 0; i < len; i++) s += Math.floor(Math.random() * 16).toString(16);
  return s;
}

function compileStep(plan, flow, step, phase, assets) {
  const debug = !!plan.debug;
  const baseUrl = plan.env.baseUrl.replace(/\/+$/, '');
  const method = step.method.toUpperCase();
  const bodyType = step.bodyType || 'raw';
  const merged = mergeHeaders(plan.env.headers, step.headers);
  const contentTypeName = merged.index['content-type'];
  const body = bodyType === 'raw' && typeof step.body === 'string' && step.body !== '' ? step.body : null;

  let boundary = null;
  if (bodyType === 'raw') {
    if (body !== null && contentTypeName === undefined && looksLikeJson(body)) {
      merged.headers['Content-Type'] = 'application/json';
    }
  } else if (bodyType === 'form') {
    // 环境的公共 Content-Type（常见的是 application/json）是给所有接口的默认值，不能压过接口选的表单类型；
    // 只有接口自己写的 Content-Type 才保留
    const own = Object.keys(step.headers || {}).some((n) => n.toLowerCase() === 'content-type');
    if (!own) {
      if (contentTypeName !== undefined) delete merged.headers[contentTypeName];
      merged.headers['Content-Type'] = 'application/x-www-form-urlencoded';
    }
  } else {
    // 显式的 Content-Type（含环境的公共请求头）会让服务端拿不到 boundary，必须换掉
    if (contentTypeName !== undefined) delete merged.headers[contentTypeName];
    boundary = `----k6perf${randomHex(24)}`;
    merged.headers['Content-Type'] = `multipart/form-data; boundary=${boundary}`;
  }

  const form = bodyType === 'raw' ? null : (step.form || []).map((item) => {
    if (item.type === 'file') {
      const meta = assets.fileMeta[item.fileKey];
      // 类型会原样拼进分段头，去掉换行防止注入（后端也校验）
      const contentType = String(meta.contentType || 'application/octet-stream').replace(/[\r\n]/g, '');
      return { name: item.name, type: 'file', bytes: new Uint8Array(assets.files[item.fileKey]), fileName: meta.name, contentType };
    }
    return { name: item.name, type: 'text', value: typeof item.value === 'string' ? item.value : '' };
  });

  const expected = (Array.isArray(step.expectStatus) ? step.expectStatus : [step.expectStatus === undefined || step.expectStatus === null ? 200 : step.expectStatus]).map(Number);
  const contains = typeof step.expectBodyContains === 'string' && step.expectBodyContains !== '' ? step.expectBodyContains : null;

  const extracts = (step.extracts || []).map((ex) => ({
    name: ex.var,
    from: ex.from,
    expr: ex.expr,
    regex: ex.from === 'regex' ? new RegExp(ex.expr) : null,
    path: ex.from === 'json' ? toGjsonPath(ex.expr) : null,
    // 旧引擎逐级取 JS 属性，数组的 .length 也能取到；GJSON 里数组长度写作 .#
    lengthPath: ex.from === 'json' && /(^|\.)length$/.test(toGjsonPath(ex.expr)) ? toGjsonPath(ex.expr).replace(/length$/, '#') : null,
    lower: ex.from === 'header' ? String(ex.expr).toLowerCase() : null,
    checkName: `[${step.key}] 提取变量 ${ex.var}`,
  }));
  const needsBody = contains !== null || extracts.some((ex) => ex.from === 'json' || ex.from === 'regex');

  const headerNames = Object.keys(merged.headers);
  return {
    key: step.key,
    name: step.name,
    phase,
    method,
    urlTemplate: baseUrl + step.path,
    urlHasVar: hasVar(step.path),
    urlStatic: encodeUrl(baseUrl + step.path),
    headers: merged.headers,
    headerVarNames: headerNames.filter((n) => hasVar(merged.headers[n])),
    bodyType,
    body,
    bodyHasVar: hasVar(body),
    form,
    boundary,
    expected,
    contains,
    containsHasVar: hasVar(contains),
    statusCheckName: `[${step.key}] 状态码为 ${expected.join(' / ')}`,
    containsCheckName: contains === null ? null : `[${step.key}] 响应包含「${short(contains, 30)}」`,
    extracts,
    // 调试只跑一次迭代，等待时间对结果没有意义，不等
    thinkSec: !debug && typeof step.thinkTimeMs === 'number' && step.thinkTimeMs > 0 ? step.thinkTimeMs / 1000 : 0,
    // 以下对象每次请求复用，不含每次迭代才知道的内容
    tags: { flow: flow.key, step: step.key, name: `${method} ${step.path}`, phase },
    // 让 http_req_failed 按期望状态码判断，而不是默认的 "2xx/3xx 算成功"。
    // k6 对重定向链上的每一跳都会调用这个回调，所以要把会被自动跟随的重定向状态码也算作"符合预期"，
    // 否则 "期望 200、中途 302" 的请求会被记成一次失败。最终状态码是否正确由 check 把关。
    responseCallback: http.expectedStatuses.apply(null, expected.concat(REDIRECT_STATUSES)),
    // 用不到响应体时不保留，省内存；调试时总是保留，页面要显示
    responseType: debug || needsBody ? 'text' : 'none',
  };
}

/**
 * init 阶段调用一次。返回 { [flow.key]: 已编译的 flow }。
 * @param assets { datasets: { [key]: SharedArray }, files: { [key]: ArrayBuffer } }，由 runner 在 init 阶段加载
 */
export function compileFlows(plan, assets) {
  const loaded = assets || { datasets: {}, files: {} };
  const dsMeta = {};
  for (const ds of plan.datasets || []) dsMeta[ds.key] = ds;
  const fileMeta = {};
  for (const f of plan.files || []) fileMeta[f.key] = f;
  const stepAssets = { files: loaded.files, fileMeta };

  // 环境变量的初始值：每次迭代开始时的变量（契约 §4 env.variables）
  const initialVars = plan.env && plan.env.variables && typeof plan.env.variables === 'object' ? plan.env.variables : {};
  const anyStop = plan.flows.some((f) => (f.datasets || []).some((b) => b.onExhausted === 'stop'));
  // 自定义指标只能在 init 阶段创建；阈值在 thresholds.js 里按同一个条件附加
  const exhausted = anyStop ? new Counter('data_exhausted') : null;
  const ctx = { runId: plan.runId };

  const compiled = {};
  for (const flow of plan.flows) {
    const initSteps = (flow.initSteps || []).map((step) => compileStep(plan, flow, step, 'init', stepAssets));
    compiled[flow.key] = {
      key: flow.key,
      name: flow.name,
      ctx,
      initialVars,
      datasets: (flow.datasets || []).map((b) => ({
        rows: loaded.datasets[b.key],
        columns: dsMeta[b.key].columns,
        pick: b.pick,
        stop: b.onExhausted === 'stop',
        stride: b.stride || 1,
        offset: b.offset || 0,
      })),
      variables: (flow.variables || []).map((v) => ({ name: v.name, value: v.value })),
      initSteps,
      steps: flow.steps.map((step) => compileStep(plan, flow, step, 'main', stepAssets)),
      reinitMs: typeof flow.reinitSec === 'number' && flow.reinitSec > 0 ? flow.reinitSec * 1000 : null,
      closed: plan.profile.model === 'closed',
      exhausted,
    };
  }
  return compiled;
}

/** 按绑定的取法把每个数据集的一行写进 vars。有数据集用完（stop）时返回 false。 */
function pickRows(flow, vars) {
  for (const b of flow.datasets) {
    const n = b.rows.length;
    let i;
    if (b.pick === 'random') {
      i = Math.floor(Math.random() * n);
    } else {
      // 只用 *InTest 字段选数据（ADR-002 决定 8）：iterationInTest 按 scenario 各自从 0 开始，
      // 多个流程共用一个数据集时由后端给出 stride / offset 错开
      i = b.pick === 'perVu' ? exec.vu.idInTest - 1 : exec.scenario.iterationInTest * b.stride + b.offset;
      if (i >= n) {
        if (b.stop) return false;
        i %= n;
      }
    }
    const row = b.rows[i];
    for (let c = 0; c < b.columns.length; c++) vars[b.columns[c]] = row[c];
  }
  return true;
}

function extractValue(ex, res, url, jar) {
  if (ex.from === 'json') {
    // GJSON（k6 内置）：支持 a.b.0.c、a.#、a.#(k=="v").id；响应不是 JSON 时得到 undefined
    if (ex.path === '') return res.json();
    const v = res.json(ex.path);
    return v === undefined && ex.lengthPath ? res.json(ex.lengthPath) : v;
  }
  if (ex.from === 'regex') {
    const m = ex.regex.exec(res.body);
    if (!m) return undefined;
    return m.length > 1 ? m[1] : m[0];
  }
  if (ex.from === 'header') {
    for (const name of Object.keys(res.headers)) {
      if (name.toLowerCase() === ex.lower) return res.headers[name];
    }
    return undefined;
  }
  if (ex.from === 'cookie') {
    // res.cookies 只有最后一跳设置的 Cookie；重定向链上设置的去罐里找，先按这次请求的地址，再按最终地址
    const own = res.cookies ? res.cookies[ex.expr] : undefined;
    if (own && own.length > 0) return own[0].value;
    const box = jar || http.cookieJar();
    for (const u of [url, res.url]) {
      if (!u) continue;
      const found = box.cookiesForURL(u)[ex.expr];
      if (found && found.length > 0) return found[0];
    }
    return undefined;
  }
  return undefined;
}

// ---------- 请求体 ----------

function concatBytes(chunks) {
  let total = 0;
  for (const c of chunks) total += c.length;
  const out = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

/** 手工拼 multipart：k6 的对象写法字段顺序随机，这里按 form 的顺序。 */
function multipartBody(step, items) {
  const enc = new TextEncoder();
  const chunks = [];
  for (const item of items) {
    if (item.type === 'file') {
      chunks.push(enc.encode(`--${step.boundary}\r\nContent-Disposition: form-data; name="${escapeQuoted(item.name)}"; filename="${escapeQuoted(item.fileName)}"\r\nContent-Type: ${item.contentType}\r\n\r\n`));
      chunks.push(item.bytes);
      chunks.push(enc.encode('\r\n'));
    } else {
      chunks.push(enc.encode(`--${step.boundary}\r\nContent-Disposition: form-data; name="${escapeQuoted(item.name)}"\r\n\r\n${item.value}\r\n`));
    }
  }
  chunks.push(enc.encode(`--${step.boundary}--\r\n`));
  return concatBytes(chunks).buffer;
}

/** 返回 { payload: 交给 http.request 的请求体, body: 调试记录里的 body, form: 调试记录里的 form }。 */
function buildBody(step, vars, ctx, debug) {
  if (step.bodyType === 'raw') {
    const body = step.bodyHasVar ? render(step.body, vars, ctx) : step.body;
    return { payload: body, body, form: null };
  }
  const items = step.form.map((item) =>
    item.type === 'file'
      ? Object.assign({}, item, { name: render(item.name, vars, ctx) })
      : { name: render(item.name, vars, ctx), type: 'text', value: render(item.value, vars, ctx) },
  );
  const form = debug
    ? items.map((item) =>
        item.type === 'file'
          ? { name: item.name, type: 'file', fileName: item.fileName, contentType: item.contentType, size: item.bytes.length }
          : { name: item.name, type: 'text', value: item.value },
      )
    : null;
  if (step.bodyType === 'form') {
    const body = items.map((item) => `${encodeFormComponent(item.name)}=${encodeFormComponent(item.value)}`).join('&');
    return { payload: body, body, form };
  }
  return { payload: multipartBody(step, items), body: null, form };
}

// ---------- 调试记录 ----------

function round2(v) {
  return typeof v === 'number' && isFinite(v) ? Math.round(v * 100) / 100 : null;
}

function headerValue(headers, nameLower) {
  for (const name of Object.keys(headers || {})) {
    if (name.toLowerCase() === nameLower) return headers[name];
  }
  return null;
}

/** 响应体像文本才返回给页面；图片、压缩包之类只给长度。没有 Content-Type 时按文本处理。 */
function isTextual(contentType) {
  if (!contentType) return true;
  const ct = String(contentType).toLowerCase();
  return ct.indexOf('text/') === 0 || /json|xml|javascript|ecmascript|x-www-form-urlencoded/.test(ct);
}

function describeResponse(res, bodyLimit) {
  const contentType = headerValue(res.headers, 'content-type');
  const raw = typeof res.body === 'string' ? res.body : res.body === null || res.body === undefined ? '' : String(res.body);
  const omitted = !isTextual(contentType);
  const truncated = !omitted && raw.length > bodyLimit;
  return {
    status: res.status,
    statusText: res.status_text || null,
    finalUrl: res.url || null,
    headers: res.headers || {},
    contentType: contentType,
    bodyLength: raw.length,
    body: omitted ? null : truncated ? raw.slice(0, bodyLimit) : raw,
    bodyTruncated: truncated,
    bodyOmitted: omitted,
  };
}

function describeTimings(res) {
  const t = res.timings || {};
  return {
    durationMs: round2(t.duration),
    blockedMs: round2(t.blocked),
    lookingUpMs: round2(t.looking_up),
    connectingMs: round2(t.connecting),
    tlsMs: round2(t.tls_handshaking),
    sendingMs: round2(t.sending),
    waitingMs: round2(t.waiting),
    receivingMs: round2(t.receiving),
  };
}

function describeError(res) {
  if (!res.error) return null;
  return res.error_code ? `${res.error}（error_code ${res.error_code}）` : String(res.error);
}

function idleRecord(step, status, error, vars) {
  return {
    key: step.key, name: step.name, phase: step.phase, status,
    request: null, response: null, timings: null, error,
    checks: [], extracted: [], vars: Object.assign({}, vars),
  };
}

// ---------- 执行 ----------

/**
 * 执行一步。debug 为 null 时和压测完全一致；否则把这一步的记录 push 进 debug.steps。
 * produced 不为 null 时，把这一步提取到的变量也记进去（初始化段要据此保留输出）。
 * 返回这一步的检查是否全部通过。
 */
function runStep(step, vars, ctx, debug, produced, jar) {
  const url = step.urlHasVar ? encodeUrl(render(step.urlTemplate, vars, ctx)) : step.urlStatic;
  let headers = step.headers;
  if (step.headerVarNames.length > 0) {
    headers = Object.assign({}, step.headers);
    for (const name of step.headerVarNames) headers[name] = render(headers[name], vars, ctx);
  }
  const built = buildBody(step, vars, ctx, !!debug);

  const params = {
    headers,
    tags: step.tags,
    responseCallback: step.responseCallback,
    responseType: step.responseType,
  };
  if (jar) params.jar = jar;
  const res = http.request(step.method, url, built.payload, params);

  // 每条检查的结果单独记一份：check() 只返回总的布尔值
  const results = {};
  const checks = {};
  const add = (name, predicate) => {
    checks[name] = (r) => {
      const ok = predicate(r);
      results[name] = ok;
      return ok;
    };
  };
  add(step.statusCheckName, (r) => step.expected.indexOf(r.status) !== -1);
  if (step.contains !== null) {
    // 期望文本里也可以引用变量，例如期望响应里出现登录用的 {{username}}
    const expected = step.containsHasVar ? render(step.contains, vars, ctx) : step.contains;
    add(step.containsCheckName, (r) => typeof r.body === 'string' && r.body.indexOf(expected) !== -1);
  }
  const extracted = [];
  for (const ex of step.extracts) {
    let value;
    try {
      value = extractValue(ex, res, url, jar);
    } catch (e) {
      value = undefined; // 响应不是 JSON、网络错误等
    }
    const found = value !== undefined && value !== null;
    const stored = found ? (typeof value === 'object' ? JSON.stringify(value) : String(value)) : null;
    if (found) {
      vars[ex.name] = stored;
      if (produced) produced[ex.name] = stored;
    }
    add(ex.checkName, () => found);
    if (debug) extracted.push({ var: ex.name, from: ex.from, expr: ex.expr, ok: found, value: stored });
  }
  const ok = check(res, checks, { flow: step.tags.flow, step: step.key });

  if (debug) {
    debug.steps.push({
      key: step.key,
      name: step.name,
      phase: step.phase,
      status: ok ? 'passed' : 'failed',
      request: { method: step.method, url, headers, bodyType: step.bodyType, body: built.body, form: built.form },
      response: describeResponse(res, debug.bodyLimit),
      timings: describeTimings(res),
      error: describeError(res),
      checks: Object.keys(checks).map((name) => ({ name, ok: results[name] === true })),
      extracted,
      vars: Object.assign({}, vars),
    });
  }
  return ok;
}

/**
 * 按顺序执行一段步骤，返回是否全部通过。某一步没通过时余下的步骤不执行：
 * 压测时直接返回；调试时把它们记成 skipped，页面上看得出"从哪一步开始没跑"。
 */
function runSequence(steps, vars, ctx, rec, produced, jar) {
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    let ok;
    if (rec) {
      // 调试时把脚本异常（例如地址非法）当成这一步的错误记下来，而不是让整次调试没有结果
      try {
        ok = runStep(step, vars, ctx, rec, produced, jar);
      } catch (e) {
        rec.steps.push(idleRecord(step, 'error', e && e.message ? String(e.message) : String(e), vars));
        ok = false;
      }
    } else {
      ok = runStep(step, vars, ctx, null, produced, jar);
    }
    // 失败时也照常等待，避免 closed 模型下失败的迭代空转、对目标形成无间隔的请求
    if (step.thinkSec > 0) sleep(step.thinkSec);
    if (!ok) {
      if (rec) skipAll(steps.slice(i + 1), vars, rec);
      return false;
    }
  }
  return true;
}

function skipAll(steps, vars, rec) {
  for (const step of steps) {
    rec.steps.push(idleRecord(step, 'skipped', '前面的步骤检查未通过，本次迭代余下的步骤不执行（压测时也是这样）', vars));
  }
}

/**
 * 执行一次迭代。
 * @param flow   compileFlows 的产物之一
 * @param debug  调试配置 { vars, bodyLimit }；压测时不传
 * @returns 调试时返回 { steps, vars }（契约 §5.1）；压测时无返回值
 */
export function executeFlow(flow, debug) {
  // 环境变量打底，调试单个接口时页面上的当前值覆盖同名项
  const vars = Object.assign({}, flow.initialVars || {}, debug && debug.vars ? debug.vars : {});
  const rec = debug ? { steps: [], bodyLimit: debug.bodyLimit } : null;
  const ctx = flow.ctx;
  const done = () => (rec ? { steps: rec.steps, vars } : undefined);

  if (!pickRows(flow, vars)) {
    // 数据用完：不发请求，计数交给 validity 阈值（abortOnFail）结束测试并判 invalid。
    // closed 模型下 VU 会立刻开始下一次迭代，等 1 秒避免空转；open 模型的迭代由到达率驱动，直接返回
    flow.exhausted.add(1);
    if (flow.closed) sleep(1);
    return done();
  }
  for (const v of flow.variables) vars[v.name] = render(v.value, vars, ctx);

  // 有初始化段的流程用自己的 Cookie 罐，存在 VU 状态里跨迭代保留，重新初始化时换新的（旧会话的 Cookie 全部丢弃）。
  // 没有初始化段的流程不传 jar，用 k6 默认的罐，每次迭代清空，和以前一样。
  // 不用 noCookiesReset + jar.clear(url)：clear 只删这个地址的主机和默认路径下的 Cookie，带 Domain、非根路径、重定向到别的主机设置的都会漏掉
  let jar = null;
  if (flow.initSteps.length > 0) {
    let state = vuState[flow.key];
    if (state && flow.reinitMs !== null && Date.now() - state.at >= flow.reinitMs) state = null;
    if (!state) {
      const fresh = new http.CookieJar();
      const produced = {};
      if (!runSequence(flow.initSteps, vars, ctx, rec, produced, fresh)) {
        // 下一次迭代重新执行初始化段（状态为空即重试；不用 iterationInInstance === 0 判断首次，失败后就再也不会重试）
        vuState[flow.key] = null;
        if (rec) {
          skipAll(flow.steps, vars, rec);
        } else if (flow.closed) {
          // 登录接口很快失败、等待时间又是 0 时，closed 模型会无间隔地反复登录
          sleep(1);
        }
        return done();
      }
      state = { vars: produced, at: Date.now(), jar: fresh };
      vuState[flow.key] = state;
    }
    Object.assign(vars, state.vars);
    jar = state.jar;
  }

  runSequence(flow.steps, vars, ctx, rec, null, jar);
  return done();
}
