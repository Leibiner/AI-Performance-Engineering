// 通用 k6 脚本：读取后端生成的 plan.json 并解释执行（契约 §4、§5）。
//
// 用法（工作目录为仓库根目录，路径用绝对路径）：
//   k6 run perf/runner.js -e PLAN_FILE=/abs/plan.json -e OUTPUT_DIR=/abs/out --tag testid=<runId>
// 只看生成的 options、不发请求：
//   k6 inspect perf/runner.js -e PLAN_FILE=/abs/plan.json
// 调试（plan 带 debug 段，契约 §3.5）：后端另加 --no-thresholds --log-format=json --console-output=<文件>，
// 迭代结束后本脚本把逐步记录 console.log 成一行 JSON（契约 §5.1）。
//
// 业务流程是数据，不是代码，所以只导出一个执行函数 runFlow：
// 每个 flow 是一个 scenario（名称 = flow.key），运行时用 exec.scenario.name 找回对应的 flow。

import exec from 'k6/execution';
import { compose } from './core/compose.js';
import { compileFlows, executeFlow } from './core/interp.js';
import { summarize } from './core/summary.js';

if (!__ENV.PLAN_FILE) {
  throw new Error('缺少环境变量 PLAN_FILE（plan.json 的绝对路径），用 -e PLAN_FILE=... 传入');
}

// open() 只能在 init 阶段调用；相对路径是相对于本文件所在目录，所以要求传绝对路径
const plan = JSON.parse(open(__ENV.PLAN_FILE));
const built = compose(plan);
const flows = compileFlows(plan);

// 调试模式的配置；压测时为 null
const debug =
  plan.debug && typeof plan.debug === 'object'
    ? {
        vars: plan.debug.vars && typeof plan.debug.vars === 'object' ? plan.debug.vars : {},
        bodyLimit: typeof plan.debug.bodyLimit === 'number' && plan.debug.bodyLimit > 0 ? plan.debug.bodyLimit : 65536,
      }
    : null;

export const options = built.options;

export function runFlow() {
  const flow = flows[exec.scenario.name];
  if (!flow) throw new Error(`找不到 scenario ${exec.scenario.name} 对应的 flow`);
  if (!debug) {
    executeFlow(flow);
    return;
  }
  // handleSummary 在独立的运行时里执行，看不到 VU 里的变量；VU 也不能写文件。
  // 所以调试记录用 console 交出去，由后端从 --console-output 指向的文件里读。
  const trace = executeFlow(flow, debug);
  console.log(JSON.stringify({ debugTrace: trace }));
}

export function handleSummary(data) {
  // 调试没有阈值、判定和 Run Record，也不打印摘要
  if (debug) return {};
  return summarize(data, { plan, thresholdMeta: built.meta.thresholds, outputDir: __ENV.OUTPUT_DIR });
}
