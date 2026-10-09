// Flow 解释器：按顺序执行 plan 里用数据定义的步骤。
//
// 每一步：{{变量}} 替换 → 发请求 → check → 提取变量 → 等待 thinkTimeMs。
// 变量的作用域是一次迭代；某一步的 check 没通过时，本次迭代剩下的步骤不再执行
// （后面的步骤通常依赖前面提取到的变量，继续发只会产生无意义的请求）。
//
// 调试模式（plan.debug 存在，契约 §3.5、§4、§5.1）走的是同一套代码，只多做三件事：
// 不等待 thinkTime、保留响应体、把每一步的请求 / 响应 / 检查 / 变量记录下来交给 runner 输出。

import http from 'k6/http';
import { check, sleep } from 'k6';

const VAR_PATTERN = /\{\{\s*([^{}\s]+)\s*\}\}/g;
const REDIRECT_STATUSES = [301, 302, 303, 307, 308];

/** 替换 {{变量}}；变量不存在时保留原样，方便在日志和目标端看出问题。 */
export function render(template, vars) {
  if (typeof template !== 'string' || template.indexOf('{{') === -1) return template;
  return template.replace(VAR_PATTERN, (whole, name) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? vars[name] : whole,
  );
}

function hasVar(s) {
  return typeof s === 'string' && s.indexOf('{{') !== -1;
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
  return { headers: out, hasContentType: index['content-type'] !== undefined };
}

function looksLikeJson(body) {
  const c = body.trim()[0];
  return c === '{' || c === '[';
}

function short(text, max) {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function compileStep(plan, flow, step) {
  const debug = !!plan.debug;
  const baseUrl = plan.env.baseUrl.replace(/\/+$/, '');
  const method = step.method.toUpperCase();
  const merged = mergeHeaders(plan.env.headers, step.headers);
  const body = typeof step.body === 'string' && step.body !== '' ? step.body : null;
  if (body !== null && !merged.hasContentType && looksLikeJson(body)) {
    merged.headers['Content-Type'] = 'application/json';
  }

  const expected = (Array.isArray(step.expectStatus) ? step.expectStatus : [step.expectStatus === undefined || step.expectStatus === null ? 200 : step.expectStatus]).map(Number);
  const contains = typeof step.expectBodyContains === 'string' && step.expectBodyContains !== '' ? step.expectBodyContains : null;

  const extracts = (step.extracts || []).map((ex) => ({
    name: ex.var,
    from: ex.from,
    expr: ex.expr,
    regex: ex.from === 'regex' ? new RegExp(ex.expr) : null,
    path: ex.from === 'json' ? String(ex.expr).split('.').filter((p) => p !== '') : null,
    headerLower: ex.from === 'header' ? String(ex.expr).toLowerCase() : null,
    checkName: `[${step.key}] 提取变量 ${ex.var}`,
  }));
  const needsBody = contains !== null || extracts.some((ex) => ex.from === 'json' || ex.from === 'regex');

  const headerNames = Object.keys(merged.headers);
  return {
    key: step.key,
    name: step.name,
    method,
    urlTemplate: baseUrl + step.path,
    urlHasVar: hasVar(step.path),
    headers: merged.headers,
    headerVarNames: headerNames.filter((n) => hasVar(merged.headers[n])),
    body,
    bodyHasVar: hasVar(body),
    expected,
    contains,
    statusCheckName: `[${step.key}] 状态码为 ${expected.join(' / ')}`,
    containsCheckName: contains === null ? null : `[${step.key}] 响应包含「${short(contains, 30)}」`,
    extracts,
    // 调试只跑一次迭代，等待时间对结果没有意义，不等
    thinkSec: !debug && typeof step.thinkTimeMs === 'number' && step.thinkTimeMs > 0 ? step.thinkTimeMs / 1000 : 0,
    // 以下对象每次请求复用，不含每次迭代才知道的内容
    tags: { flow: flow.key, step: step.key, name: `${method} ${step.path}` },
    // 让 http_req_failed 按期望状态码判断，而不是默认的 "2xx/3xx 算成功"。
    // k6 对重定向链上的每一跳都会调用这个回调，所以要把会被自动跟随的重定向状态码也算作"符合预期"，
    // 否则 "期望 200、中途 302" 的请求会被记成一次失败。最终状态码是否正确由 check 把关。
    responseCallback: http.expectedStatuses.apply(null, expected.concat(REDIRECT_STATUSES)),
    // 用不到响应体时不保留，省内存；调试时总是保留，页面要显示
    responseType: debug || needsBody ? 'text' : 'none',
  };
}

/** init 阶段调用一次。返回 { [flow.key]: 已编译的 flow }。 */
export function compileFlows(plan) {
  // 环境变量的初始值：每次迭代开始时的变量（契约 §4 env.variables）
  const initialVars = plan.env && plan.env.variables && typeof plan.env.variables === 'object' ? plan.env.variables : {};
  const compiled = {};
  for (const flow of plan.flows) {
    compiled[flow.key] = {
      key: flow.key,
      name: flow.name,
      initialVars,
      steps: flow.steps.map((step) => compileStep(plan, flow, step)),
    };
  }
  return compiled;
}

function extractValue(ex, res) {
  if (ex.from === 'json') {
    let node = res.json();
    for (const part of ex.path) {
      if (node === null || node === undefined) return undefined;
      node = node[part];
    }
    return node;
  }
  if (ex.from === 'regex') {
    const m = ex.regex.exec(res.body);
    return m ? m[1] : undefined;
  }
  if (ex.from === 'header') {
    for (const name of Object.keys(res.headers)) {
      if (name.toLowerCase() === ex.headerLower) return res.headers[name];
    }
    return undefined;
  }
  return undefined;
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

// ---------- 执行 ----------

/**
 * 执行一步。debug 为 null 时和压测完全一致；否则把这一步的记录 push 进 debug.steps。
 * 返回这一步的检查是否全部通过。
 */
function runStep(step, vars, debug) {
  const url = step.urlHasVar ? render(step.urlTemplate, vars) : step.urlTemplate;
  let headers = step.headers;
  if (step.headerVarNames.length > 0) {
    headers = Object.assign({}, step.headers);
    for (const name of step.headerVarNames) headers[name] = render(headers[name], vars);
  }
  const body = step.bodyHasVar ? render(step.body, vars) : step.body;

  const res = http.request(step.method, url, body, {
    headers,
    tags: step.tags,
    responseCallback: step.responseCallback,
    responseType: step.responseType,
  });

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
    add(step.containsCheckName, (r) => typeof r.body === 'string' && r.body.indexOf(step.contains) !== -1);
  }
  const extracted = [];
  for (const ex of step.extracts) {
    let value;
    try {
      value = extractValue(ex, res);
    } catch (e) {
      value = undefined; // 响应不是 JSON、网络错误等
    }
    const found = value !== undefined && value !== null;
    const stored = found ? (typeof value === 'object' ? JSON.stringify(value) : String(value)) : null;
    if (found) vars[ex.name] = stored;
    add(ex.checkName, () => found);
    if (debug) extracted.push({ var: ex.name, from: ex.from, expr: ex.expr, ok: found, value: stored });
  }
  const ok = check(res, checks, { flow: step.tags.flow, step: step.key });

  if (debug) {
    debug.steps.push({
      key: step.key,
      name: step.name,
      status: ok ? 'passed' : 'failed',
      request: { method: step.method, url, headers, body },
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
 * 执行一次迭代。
 * @param flow   compileFlows 的产物之一
 * @param debug  调试配置 { vars, bodyLimit }；压测时不传
 * @returns 调试时返回 { steps, vars }（契约 §5.1）；压测时无返回值
 */
export function executeFlow(flow, debug) {
  // 环境变量打底，调试时页面上的当前值覆盖同名项
  const vars = Object.assign({}, flow.initialVars || {}, debug && debug.vars ? debug.vars : {});
  const rec = debug ? { steps: [], bodyLimit: debug.bodyLimit } : null;
  let stopped = false;
  for (const step of flow.steps) {
    if (stopped) {
      // 只有调试会走到这里：把没执行的步骤也列出来，页面上看得出"从哪一步开始没跑"
      rec.steps.push({
        key: step.key, name: step.name, status: 'skipped',
        request: null, response: null, timings: null,
        error: '前面的步骤检查未通过，本次迭代余下的步骤不执行（压测时也是这样）',
        checks: [], extracted: [], vars: Object.assign({}, vars),
      });
      continue;
    }
    let ok;
    if (rec) {
      // 调试时把脚本异常（例如地址非法）当成这一步的错误记下来，而不是让整次调试没有结果
      try {
        ok = runStep(step, vars, rec);
      } catch (e) {
        rec.steps.push({
          key: step.key, name: step.name, status: 'error',
          request: null, response: null, timings: null,
          error: e && e.message ? String(e.message) : String(e),
          checks: [], extracted: [], vars: Object.assign({}, vars),
        });
        ok = false;
      }
    } else {
      ok = runStep(step, vars, null);
    }
    // 失败时也照常等待，避免 closed 模型下失败的迭代空转、对目标形成无间隔的请求
    if (step.thinkSec > 0) sleep(step.thinkSec);
    if (!ok) {
      if (!rec) return;
      stopped = true;
    }
  }
  return rec ? { steps: rec.steps, vars } : undefined;
}
