// Composer：plan（业务 + 负载 + SLO）→ k6 options。
//
// 每个 flow 编译成一个 k6 scenario，scenario 名 = flow.key。
// 施压配置的四种形态（契约 §3.1）：
//   closed + iterations            → shared-iterations
//   closed + durationSec           → constant-vus
//   open   + rate                  → constant-arrival-rate
//   open   + startRate + stages    → ramping-arrival-rate
// 多个 flow 时按 weight 拆分并发 / 迭代数 / 到达率，拆分后的总量不超过 plan 里的设定值。

import { buildThresholds } from './thresholds.js';

export const EXEC_FN = 'runFlow';
export const TREND_STATS = ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'];

// k6 默认的 gracefulStop 是 30s。目标可能是第三方站点，时长上限是硬性护栏，所以收紧。
const GRACEFUL_STOP = '5s';

const KEY_PATTERN = /^[A-Za-z0-9_]+$/;
const PICKS = ['sequential', 'random', 'perVu'];
const BODY_TYPES = ['raw', 'form', 'multipart'];

function fail(msg) {
  throw new Error(`plan 无效：${msg}`);
}

function isPos(v) {
  return typeof v === 'number' && isFinite(v) && v > 0;
}

function isPosInt(v) {
  return isPos(v) && Math.floor(v) === v;
}

export function validatePlan(plan) {
  if (!plan || typeof plan !== 'object') fail('不是 JSON 对象');
  if (plan.schemaVersion !== 1) fail(`不支持的 schemaVersion：${plan.schemaVersion}`);
  if (!plan.env || typeof plan.env.baseUrl !== 'string' || !/^https?:\/\//.test(plan.env.baseUrl)) {
    fail('env.baseUrl 必须是 http(s) 地址');
  }
  if (!plan.profile || !plan.profile.config) fail('缺少 profile.config');
  if (plan.profile.model !== 'open' && plan.profile.model !== 'closed') {
    fail(`profile.model 必须是 open 或 closed，实际为 ${plan.profile.model}`);
  }
  if (!Array.isArray(plan.flows) || plan.flows.length === 0) fail('flows 不能为空');
  const seen = {};
  const datasets = {};
  for (const ds of plan.datasets || []) {
    if (!KEY_PATTERN.test(ds.key || '') || datasets[ds.key]) fail(`数据集 key 无效或重复：${ds.key}`);
    if (!Array.isArray(ds.columns) || ds.columns.length === 0) fail(`数据集 ${ds.key} 没有列`);
    if (typeof ds.file !== 'string' || ds.file === '') fail(`数据集 ${ds.key} 缺少 file`);
    datasets[ds.key] = ds;
  }
  const files = {};
  for (const f of plan.files || []) {
    if (!KEY_PATTERN.test(f.key || '') || files[f.key]) fail(`文件 key 无效或重复：${f.key}`);
    if (typeof f.file !== 'string' || f.file === '') fail(`文件 ${f.key} 缺少 file`);
    files[f.key] = f;
  }
  const checkStep = (step) => {
    if (!KEY_PATTERN.test(step.key || '')) fail(`step.key 只能用 ASCII 字母、数字、下划线：${step.key}`);
    if (seen[step.key]) fail(`key 重复：${step.key}`);
    seen[step.key] = true;
    if (typeof step.method !== 'string') fail(`step ${step.key} 缺少 method`);
    if (typeof step.path !== 'string' || step.path[0] !== '/') fail(`step ${step.key} 的 path 必须以 / 开头`);
    const bodyType = step.bodyType || 'raw';
    if (BODY_TYPES.indexOf(bodyType) === -1) fail(`step ${step.key} 的 bodyType 无效：${bodyType}`);
    if (bodyType !== 'raw') {
      if (!Array.isArray(step.form)) fail(`step ${step.key} 的 form 必须是数组`);
      for (const item of step.form) {
        if (typeof item.name !== 'string') fail(`step ${step.key} 的 form 项缺少 name`);
        if (item.type === 'file') {
          if (bodyType !== 'multipart') fail(`step ${step.key} 的 x-www-form-urlencoded 请求体不能带文件`);
          if (!files[item.fileKey]) fail(`step ${step.key} 引用的文件 ${item.fileKey} 不在 plan.files 里`);
        }
      }
    }
  };
  for (const flow of plan.flows) {
    if (!KEY_PATTERN.test(flow.key || '')) fail(`flow.key 只能用 ASCII 字母、数字、下划线：${flow.key}`);
    if (seen[flow.key]) fail(`key 重复：${flow.key}`);
    seen[flow.key] = true;
    if (!isPos(flow.weight)) fail(`flow ${flow.key} 的 weight 必须是正数`);
    if (!Array.isArray(flow.steps) || flow.steps.length === 0) fail(`flow ${flow.key} 没有步骤`);
    for (const b of flow.datasets || []) {
      if (!datasets[b.key]) fail(`flow ${flow.key} 绑定的数据集 ${b.key} 不在 plan.datasets 里`);
      if (PICKS.indexOf(b.pick) === -1) fail(`flow ${flow.key} 的数据集取法无效：${b.pick}`);
      if (b.onExhausted !== 'recycle' && b.onExhausted !== 'stop') fail(`flow ${flow.key} 的 onExhausted 无效：${b.onExhausted}`);
      const stride = b.stride === undefined ? 1 : b.stride;
      const offset = b.offset === undefined ? 0 : b.offset;
      if (!isPosInt(stride) || !(offset >= 0 && Math.floor(offset) === offset && offset < stride)) {
        fail(`flow ${flow.key} 的数据集 stride / offset 无效：${stride} / ${offset}`);
      }
    }
    for (const v of flow.variables || []) {
      if (typeof v.name !== 'string' || typeof v.value !== 'string') fail(`flow ${flow.key} 的流程变量必须是 { name, value } 字符串`);
    }
    if (flow.reinitSec !== undefined && flow.reinitSec !== null && !isPos(flow.reinitSec)) {
      fail(`flow ${flow.key} 的 reinitSec 必须是正数或 null`);
    }
    for (const step of flow.initSteps || []) checkStep(step);
    for (const step of flow.steps) checkStep(step);
  }
}


function normalizedWeights(flows) {
  const sum = flows.reduce((acc, f) => acc + f.weight, 0);
  return flows.map((f) => f.weight / sum);
}

/**
 * 把整数 total 按权重拆成 n 个整数，每份至少为 1，总和等于 total（最大余数法）。
 */
function apportion(total, weights, what) {
  const n = weights.length;
  if (!isPosInt(total)) fail(`${what} 必须是正整数，实际为 ${total}`);
  if (total < n) fail(`${what}（${total}）小于业务流程数量（${n}），无法给每个流程至少分配 1`);
  const ideal = weights.map((w) => w * total);
  const parts = ideal.map((v) => Math.max(1, Math.floor(v + 1e-9)));
  let sum = parts.reduce((a, b) => a + b, 0);
  while (sum !== total) {
    let pick = -1;
    for (let i = 0; i < n; i++) {
      if (sum > total && parts[i] <= 1) continue;
      const gap = sum > total ? parts[i] - ideal[i] : ideal[i] - parts[i];
      if (pick === -1 || gap > (sum > total ? parts[pick] - ideal[pick] : ideal[pick] - parts[pick])) pick = i;
    }
    parts[pick] += sum > total ? -1 : 1;
    sum += sum > total ? -1 : 1;
  }
  return parts;
}

/**
 * k6 的到达率必须是整数。把一组"每秒 N 次"（可以是小数）换算成同一个 timeUnit 下的整数。
 * 例：0.5/s → 每 2s 1 次；[0.3, 0.6]/s → 每 10s [3, 6] 次。
 * 找不到精确的 timeUnit 时用 60s 并向下取整，保证不超过设定值。
 */
function toIntegerRates(perSecond, requirePositive) {
  const TOLERANCE = 1e-3;
  for (let t = 1; t <= 60; t++) {
    const scaled = perSecond.map((r) => r * t);
    const exact = scaled.every((v) => Math.abs(v - Math.round(v)) <= TOLERANCE);
    const positive = !requirePositive || scaled.every((v) => Math.round(v) >= 1);
    if (exact && positive) return { timeUnitSec: t, rates: scaled.map((v) => Math.round(v)) };
  }
  let t = 60;
  if (requirePositive) {
    const min = Math.min.apply(null, perSecond);
    if (min * t < 1) t = Math.ceil(1 / min);
  }
  return { timeUnitSec: t, rates: perSecond.map((r) => Math.floor(r * t + TOLERANCE)) };
}

function detectShape(profile) {
  const c = profile.config;
  if (profile.model === 'closed') {
    if (c.iterations !== undefined && c.iterations !== null) return 'shared-iterations';
    if (c.durationSec !== undefined && c.durationSec !== null) return 'constant-vus';
  } else {
    if (Array.isArray(c.stages)) return 'ramping-arrival-rate';
    if (c.rate !== undefined && c.rate !== null) return 'constant-arrival-rate';
  }
  fail(`无法识别的施压配置形态：model=${profile.model}，config=${JSON.stringify(c)}`);
}

export function buildScenarios(plan) {
  const flows = plan.flows;
  const c = plan.profile.config;
  const weights = normalizedWeights(flows);
  const executor = detectShape(plan.profile);
  const scenarios = {};

  const base = (flow, extra) =>
    Object.assign({ executor, exec: EXEC_FN, gracefulStop: GRACEFUL_STOP, tags: { flow: flow.key } }, extra);

  if (executor === 'shared-iterations') {
    if (!isPos(c.maxDurationSec)) fail('shared-iterations 需要 maxDurationSec');
    const vus = apportion(c.vus, weights, '并发数 vus');
    const iterations = apportion(c.iterations, weights, '迭代数 iterations');
    flows.forEach((flow, i) => {
      scenarios[flow.key] = base(flow, {
        // k6 要求 iterations >= vus
        vus: Math.min(vus[i], iterations[i]),
        iterations: iterations[i],
        maxDuration: `${c.maxDurationSec}s`,
      });
    });
  } else if (executor === 'constant-vus') {
    if (!isPos(c.durationSec)) fail('constant-vus 需要 durationSec');
    const vus = apportion(c.vus, weights, '并发数 vus');
    flows.forEach((flow, i) => {
      scenarios[flow.key] = base(flow, { vus: vus[i], duration: `${c.durationSec}s` });
    });
  } else if (executor === 'constant-arrival-rate') {
    if (!isPos(c.rate)) fail('constant-arrival-rate 需要正数 rate');
    if (!isPos(c.durationSec)) fail('constant-arrival-rate 需要 durationSec');
    const pre = apportion(c.preAllocatedVus, weights, '预分配 VU 数 preAllocatedVus');
    flows.forEach((flow, i) => {
      // 每个 flow 单独换算，各自取最小的 timeUnit
      const r = toIntegerRates([c.rate * weights[i]], true);
      scenarios[flow.key] = base(flow, {
        rate: r.rates[0],
        timeUnit: `${r.timeUnitSec}s`,
        duration: `${c.durationSec}s`,
        preAllocatedVUs: pre[i],
        maxVUs: pre[i], // 不自动扩容：VU 不够就丢弃迭代，由 validity 阈值暴露
      });
    });
  } else {
    if (typeof c.startRate !== 'number' || c.startRate < 0) fail('ramping-arrival-rate 需要非负的 startRate');
    if (c.stages.length === 0) fail('ramping-arrival-rate 需要至少一个 stage');
    for (const s of c.stages) {
      if (typeof s.target !== 'number' || s.target < 0 || !isPos(s.durationSec)) {
        fail(`stage 无效：${JSON.stringify(s)}`);
      }
    }
    const pre = apportion(c.preAllocatedVus, weights, '预分配 VU 数 preAllocatedVus');
    flows.forEach((flow, i) => {
      // startRate 和所有 stage 的 target 必须共用一个 timeUnit
      const perSecond = [c.startRate].concat(c.stages.map((s) => s.target)).map((v) => v * weights[i]);
      const r = toIntegerRates(perSecond, false);
      scenarios[flow.key] = base(flow, {
        startRate: r.rates[0],
        timeUnit: `${r.timeUnitSec}s`,
        stages: c.stages.map((s, j) => ({ target: r.rates[j + 1], duration: `${s.durationSec}s` })),
        preAllocatedVUs: pre[i],
        maxVUs: pre[i],
      });
    });
  }

  return scenarios;
}

/**
 * @returns {{ options: object, meta: { thresholds: Array<{metric: string, expr: string, kind: string, label: string}> } }}
 */
export function compose(plan) {
  validatePlan(plan);
  const th = buildThresholds(plan);
  return {
    options: {
      scenarios: buildScenarios(plan),
      thresholds: th.thresholds,
      summaryTrendStats: TREND_STATS,
    },
    meta: { thresholds: th.meta },
  };
}
