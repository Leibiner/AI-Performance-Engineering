// Flow 解释器：按顺序执行 plan 里用数据定义的步骤。
//
// 每一步：{{变量}} 替换 → 发请求 → check → 提取变量 → 等待 thinkTimeMs。
// 变量的作用域是一次迭代；某一步的 check 没通过时，本次迭代剩下的步骤不再执行
// （后面的步骤通常依赖前面提取到的变量，继续发只会产生无意义的请求）。

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
    thinkSec: typeof step.thinkTimeMs === 'number' && step.thinkTimeMs > 0 ? step.thinkTimeMs / 1000 : 0,
    // 以下对象每次请求复用，不含每次迭代才知道的内容
    tags: { flow: flow.key, step: step.key, name: `${method} ${step.path}` },
    // 让 http_req_failed 按期望状态码判断，而不是默认的 "2xx/3xx 算成功"。
    // k6 对重定向链上的每一跳都会调用这个回调，所以要把会被自动跟随的重定向状态码也算作"符合预期"，
    // 否则 "期望 200、中途 302" 的请求会被记成一次失败。最终状态码是否正确由 check 把关。
    responseCallback: http.expectedStatuses.apply(null, expected.concat(REDIRECT_STATUSES)),
    // 用不到响应体时不保留，省内存
    responseType: needsBody ? 'text' : 'none',
  };
}

/** init 阶段调用一次。返回 { [flow.key]: 已编译的 flow }。 */
export function compileFlows(plan) {
  const compiled = {};
  for (const flow of plan.flows) {
    compiled[flow.key] = {
      key: flow.key,
      name: flow.name,
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

function runStep(step, vars) {
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

  const checks = {};
  checks[step.statusCheckName] = (r) => step.expected.indexOf(r.status) !== -1;
  if (step.contains !== null) {
    checks[step.containsCheckName] = (r) => typeof r.body === 'string' && r.body.indexOf(step.contains) !== -1;
  }
  for (const ex of step.extracts) {
    let value;
    try {
      value = extractValue(ex, res);
    } catch (e) {
      value = undefined; // 响应不是 JSON、网络错误等
    }
    const found = value !== undefined && value !== null;
    if (found) vars[ex.name] = typeof value === 'object' ? JSON.stringify(value) : String(value);
    checks[ex.checkName] = () => found;
  }
  return check(res, checks, { flow: step.tags.flow, step: step.key });
}

/** 执行一次迭代。 */
export function executeFlow(flow) {
  const vars = {};
  for (const step of flow.steps) {
    const ok = runStep(step, vars);
    // 失败时也照常等待，避免 closed 模型下失败的迭代空转、对目标形成无间隔的请求
    if (step.thinkSec > 0) sleep(step.thinkSec);
    if (!ok) return;
  }
}
