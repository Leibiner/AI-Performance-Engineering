// plan.slo → k6 thresholds，并给每条阈值打上分类。
//
// kind 的含义（契约 §5）：
//   slo          系统是否达标，来自 plan.slo
//   validity     本次测试是否可信（checks 通过率；open 模型下没有被丢弃的迭代）
//   placeholder  永远为真的占位阈值。k6 只在 summary 里输出"被阈值引用过"的子指标，
//                所以要靠它拿到按 step 拆分的 http_req_duration / http_req_failed。
//                占位阈值不参与判定，也不写进 run-record.json。

export const KIND_SLO = 'slo';
export const KIND_VALIDITY = 'validity';
export const KIND_PLACEHOLDER = 'placeholder';

// plan.slo.checksRate 为 null 时使用的默认检查通过率下限
const DEFAULT_CHECKS_RATE = 0.99;

function isNum(v) {
  return typeof v === 'number' && isFinite(v);
}

function percent(ratio) {
  return `${+(ratio * 100).toFixed(4)}%`;
}

export function stepDurationMetric(stepKey) {
  return `http_req_duration{step:${stepKey}}`;
}

export function stepFailedMetric(stepKey) {
  return `http_req_failed{step:${stepKey}}`;
}

/** plan 里是否有流程带初始化段（契约 §4、§5）。 */
export function hasInitSteps(plan) {
  return (plan.flows || []).some((f) => Array.isArray(f.initSteps) && f.initSteps.length > 0);
}

/**
 * 总体指标和 SLO 用的指标名。有初始化段时只算每次迭代的步骤（phase:main），
 * 登录这类初始化请求不计入业务 SLO（契约 §5，ADR-006 决定 4）。
 */
export function overallMetric(plan, name) {
  return hasInitSteps(plan) ? `${name}{phase:main}` : name;
}

/**
 * @returns {{ thresholds: Record<string, Array<string|object>>, meta: Array<{metric: string, expr: string, kind: string, label: string}> }}
 *   thresholds 直接放进 options.thresholds；meta 与之一一对应，供 handleSummary 分类。
 */
export function buildThresholds(plan) {
  const thresholds = {};
  const meta = [];
  const add = (metric, expr, kind, label, abortOnFail) => {
    if (!thresholds[metric]) thresholds[metric] = [];
    if (meta.some((m) => m.metric === metric && m.expr === expr)) return;
    thresholds[metric].push(abortOnFail ? { threshold: expr, abortOnFail: true } : expr);
    meta.push({ metric, expr, kind, label });
  };

  const slo = plan.slo || {};
  const scoped = hasInitSteps(plan);
  const duration = overallMetric(plan, 'http_req_duration');
  const failed = overallMetric(plan, 'http_req_failed');
  const who = scoped ? '业务请求' : '全部请求';

  // ---- SLO ----
  if (isNum(slo.p95Ms)) {
    add(duration, `p(95)<${slo.p95Ms}`, KIND_SLO, `${who} p95 < ${slo.p95Ms} ms`);
  }
  if (isNum(slo.p99Ms)) {
    add(duration, `p(99)<${slo.p99Ms}`, KIND_SLO, `${who} p99 < ${slo.p99Ms} ms`);
  }
  if (isNum(slo.errorRate)) {
    const prefix = scoped ? '业务请求错误率' : '错误率';
    if (slo.errorRate > 0) {
      add(failed, `rate<${slo.errorRate}`, KIND_SLO, `${prefix} < ${percent(slo.errorRate)}`);
    } else {
      // "rate<0" 永远不成立，错误率上限为 0 时改用 <=
      add(failed, 'rate<=0', KIND_SLO, `${prefix} = 0`);
    }
  }

  // ---- 有效性 ----
  const checksRate = isNum(slo.checksRate) ? slo.checksRate : DEFAULT_CHECKS_RATE;
  add('checks', `rate>=${checksRate}`, KIND_VALIDITY, `检查通过率 ≥ ${percent(checksRate)}`);

  if (plan.profile && plan.profile.model === 'open') {
    // 到达率模型下 VU 不够用时 k6 会丢弃迭代，实际负载低于设定值，结果不可信
    add('dropped_iterations', 'count==0', KIND_VALIDITY, '没有被丢弃的迭代（预分配 VU 足够）');
  }

  if ((plan.flows || []).some((f) => (f.datasets || []).some((b) => b.onExhausted === 'stop'))) {
    // 数据用完时 interp.js 计数；abortOnFail 让 k6 约 2 秒内停下并以 99 退出，判 invalid。
    // 不用 test.abort()：它的退出码 108 会被后端判成 aborted，看起来像有人点了停止
    add('data_exhausted', 'count==0', KIND_VALIDITY, '测试数据没有用完', true);
  }

  // ---- 占位：按 step 拆分；有初始化段时还要拿到 phase:main 的子指标 ----
  if (scoped) {
    add(duration, 'max>=0', KIND_PLACEHOLDER, '业务请求响应时间（占位）');
    add(failed, 'rate>=0', KIND_PLACEHOLDER, '业务请求错误率（占位）');
    add(overallMetric(plan, 'http_reqs'), 'count>=0', KIND_PLACEHOLDER, '业务请求数（占位）');
  }
  for (const flow of plan.flows || []) {
    for (const step of (flow.initSteps || []).concat(flow.steps || [])) {
      add(stepDurationMetric(step.key), 'max>=0', KIND_PLACEHOLDER, `${step.key} 响应时间（占位）`);
      add(stepFailedMetric(step.key), 'rate>=0', KIND_PLACEHOLDER, `${step.key} 错误率（占位）`);
    }
  }

  return { thresholds, meta };
}
