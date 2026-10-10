// handleSummary 的实现：k6 的 summary 数据 → run-record.json（契约 §5）+ k6-summary.json + 标准输出摘要。
//
// 依赖的 data 结构（k6 v2.3.0 实测，未开启 --new-machine-readable-summary）：
//   data.metrics[<指标名>] = { type, contains, values: {...}, thresholds?: { "<表达式>": { ok: boolean } } }
//     trend   values: avg / min / med / max / p(90) / p(95) / p(99)（由 summaryTrendStats 决定）
//     counter values: count / rate
//     rate    values: rate / passes / fails
//     gauge   values: value / min / max
//   data.state.testRunDurationMs
//   子指标的名称形如 "http_req_duration{step:f1s1}"，只有被阈值引用过才会出现

import { KIND_SLO, KIND_VALIDITY, KIND_PLACEHOLDER, stepDurationMetric, stepFailedMetric, hasInitSteps, overallMetric } from './thresholds.js';

function num(metrics, name, key) {
  const m = metrics[name];
  if (!m || !m.values) return null;
  const v = m.values[key];
  return typeof v === 'number' && isFinite(v) ? v : null;
}

function round(v, digits) {
  if (v === null) return null;
  const f = Math.pow(10, digits);
  return Math.round(v * f) / f;
}

const ms = (v) => round(v, 2);

function thresholdResults(data, thresholdMeta) {
  const out = [];
  for (const t of thresholdMeta) {
    if (t.kind === KIND_PLACEHOLDER) continue;
    const m = data.metrics[t.metric];
    const result = m && m.thresholds ? m.thresholds[t.expr] : undefined;
    // 指标不在 summary 里（理论上不会发生：k6 会为被阈值引用的指标输出结果）时按未通过处理
    const ok = result ? result.ok === true : false;
    out.push({ metric: t.metric, expr: t.expr, kind: t.kind, ok, label: t.label });
  }
  return out;
}

export function computeVerdict(thresholds) {
  if (thresholds.some((t) => t.kind === KIND_VALIDITY && !t.ok)) return 'invalid';
  if (thresholds.some((t) => t.kind === KIND_SLO && !t.ok)) return 'failed';
  return 'passed';
}

// 有初始化段时，请求数、响应时间、错误率只算每次迭代的步骤（契约 §5）；迭代、检查、流量始终按全部
function overallMetrics(metrics, plan) {
  const vusMax = num(metrics, 'vus_max', 'max');
  const reqs = overallMetric(plan, 'http_reqs');
  const d = overallMetric(plan, 'http_req_duration');
  const f = overallMetric(plan, 'http_req_failed');
  const count = num(metrics, reqs, 'count') || 0;
  // 被阈值引用的指标没有样本时 k6 给出的是 0，这里改成 null，避免被当成"响应时间 0 ms""错误率 0"
  const has = count > 0;
  const hasChecks = (num(metrics, 'checks', 'passes') || 0) + (num(metrics, 'checks', 'fails') || 0) > 0;
  return {
    scope: hasInitSteps(plan) ? 'main' : 'all',
    reqs: count,
    rps: round(num(metrics, reqs, 'rate') || 0, 3),
    iterations: num(metrics, 'iterations', 'count') || 0,
    droppedIterations: num(metrics, 'dropped_iterations', 'count') || 0,
    vusMax: vusMax !== null ? vusMax : num(metrics, 'vus_max', 'value'),
    avg: has ? ms(num(metrics, d, 'avg')) : null,
    p50: has ? ms(num(metrics, d, 'med')) : null,
    p90: has ? ms(num(metrics, d, 'p(90)')) : null,
    p95: has ? ms(num(metrics, d, 'p(95)')) : null,
    p99: has ? ms(num(metrics, d, 'p(99)')) : null,
    max: has ? ms(num(metrics, d, 'max')) : null,
    errorRate: has ? round(num(metrics, f, 'rate'), 6) : null,
    checksRate: hasChecks ? round(num(metrics, 'checks', 'rate'), 6) : null,
    dataReceived: num(metrics, 'data_received', 'count') || 0,
    dataSent: num(metrics, 'data_sent', 'count') || 0,
  };
}

function stepMetrics(metrics, plan) {
  const steps = [];
  for (const flow of plan.flows) {
    const all = (flow.initSteps || []).map((step) => [step, 'init']).concat(flow.steps.map((step) => [step, 'main']));
    for (const [step, phase] of all) {
      const d = stepDurationMetric(step.key);
      const f = stepFailedMetric(step.key);
      // rate 指标的 passes + fails = 样本数 = 这一步发出的请求数
      const count = (num(metrics, f, 'passes') || 0) + (num(metrics, f, 'fails') || 0);
      const has = count > 0;
      steps.push({
        flowKey: flow.key,
        flowName: flow.name,
        stepKey: step.key,
        stepName: step.name,
        phase,
        count,
        // 没有样本时 k6 给出的是 0，这里改成 null，避免被当成"响应时间 0 ms"
        avg: has ? ms(num(metrics, d, 'avg')) : null,
        p50: has ? ms(num(metrics, d, 'med')) : null,
        p95: has ? ms(num(metrics, d, 'p(95)')) : null,
        p99: has ? ms(num(metrics, d, 'p(99)')) : null,
        max: has ? ms(num(metrics, d, 'max')) : null,
        errorRate: has ? round(num(metrics, f, 'rate'), 6) : null,
      });
    }
  }
  return steps;
}

export function buildRunRecord(data, plan, thresholdMeta) {
  const thresholds = thresholdResults(data, thresholdMeta);
  return {
    schemaVersion: 1,
    runId: plan.runId,
    k6Verdict: computeVerdict(thresholds),
    thresholds,
    metrics: {
      overall: overallMetrics(data.metrics, plan),
      steps: stepMetrics(data.metrics, plan),
    },
    testDurationMs: data.state && typeof data.state.testRunDurationMs === 'number' ? Math.round(data.state.testRunDurationMs) : null,
  };
}

const VERDICT_TEXT = {
  passed: 'passed（通过）',
  failed: 'failed（系统不达标）',
  invalid: 'invalid（本次测试不可信）',
};

function fmt(v, unit) {
  return v === null || v === undefined ? '-' : `${v}${unit || ''}`;
}

function pct(v) {
  return v === null || v === undefined ? '-' : `${+(v * 100).toFixed(2)}%`;
}

function textSummary(record, plan) {
  const o = record.metrics.overall;
  const lines = [
    '',
    `运行 ${record.runId}｜测试：${plan.test ? plan.test.name : '-'}｜负载：${plan.profile.name || '-'}（${plan.profile.model}）`,
    `k6 判定：${VERDICT_TEXT[record.k6Verdict]}`,
    `${o.scope === 'main' ? '业务请求（不含初始化段）' : '请求'} ${o.reqs} 次（${fmt(o.rps)} 次/秒），迭代 ${o.iterations} 次，丢弃 ${o.droppedIterations} 次，错误率 ${pct(o.errorRate)}，检查通过率 ${pct(o.checksRate)}`,
    `响应时间 avg ${fmt(o.avg, ' ms')}｜p95 ${fmt(o.p95, ' ms')}｜p99 ${fmt(o.p99, ' ms')}｜max ${fmt(o.max, ' ms')}`,
  ];
  for (const t of record.thresholds) {
    lines.push(`  [${t.ok ? '通过' : '未通过'}] ${t.kind === KIND_SLO ? 'SLO' : '有效性'}：${t.label}`);
  }
  for (const s of record.metrics.steps) {
    lines.push(`  ${s.phase === 'init' ? '初始化' : '步骤'} ${s.stepKey} ${s.stepName}：${s.count} 次，p95 ${fmt(s.p95, ' ms')}，错误率 ${pct(s.errorRate)}`);
  }
  lines.push('');
  return lines.join('\n');
}

/**
 * @param data      k6 传给 handleSummary 的数据
 * @param ctx       { plan, thresholdMeta, outputDir }
 * @returns k6 要求的 { 路径或 stdout: 内容 } 映射
 */
export function summarize(data, ctx) {
  const out = {};
  const dir = ctx.outputDir ? String(ctx.outputDir).replace(/\/+$/, '') : null;
  if (dir) out[`${dir}/k6-summary.json`] = JSON.stringify(data, null, 2);

  try {
    const record = buildRunRecord(data, ctx.plan, ctx.thresholdMeta);
    if (dir) out[`${dir}/run-record.json`] = JSON.stringify(record, null, 2);
    out.stdout = textSummary(record, ctx.plan) + (dir ? '' : '（未设置 OUTPUT_DIR，没有写入 run-record.json）\n');
  } catch (e) {
    // 不写 run-record.json，后端会把这次运行判为 error；原始数据仍然保留在 k6-summary.json
    out.stdout = `\n生成 run-record.json 失败：${e && e.stack ? e.stack : e}\n`;
  }
  return out;
}
