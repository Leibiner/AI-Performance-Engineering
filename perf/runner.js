// 通用 k6 脚本：读取后端生成的 plan.json 并解释执行（契约 §4、§5）。
//
// 用法（工作目录为仓库根目录，路径用绝对路径）：
//   k6 run perf/runner.js -e PLAN_FILE=/abs/plan.json -e OUTPUT_DIR=/abs/out --tag testid=<runId>
// 只看生成的 options、不发请求：
//   k6 inspect perf/runner.js -e PLAN_FILE=/abs/plan.json
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

export const options = built.options;

export function runFlow() {
  const flow = flows[exec.scenario.name];
  if (!flow) throw new Error(`找不到 scenario ${exec.scenario.name} 对应的 flow`);
  executeFlow(flow);
}

export function handleSummary(data) {
  return summarize(data, { plan, thresholdMeta: built.meta.thresholds, outputDir: __ENV.OUTPUT_DIR });
}
