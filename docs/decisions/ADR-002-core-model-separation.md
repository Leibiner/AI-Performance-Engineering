# ADR-002：核心模型 —— Flow ⟂ Load Profile，Verdict 区分 Invalid

- 状态：**Accepted**
- 日期：2026-09-29
- 相关：`ARCHITECTURE.md`、`research/k6.md` §3、`research/k6-ecosystem.md` §6

---

## Context

k6 的 `options.scenarios.<name>` 同时包含 `exec`（业务函数）与 `executor`（负载模型）。官方建议把 workload 放入 `config/workloads.js`，但只是约定；社区项目普遍把负载写在测试文件中，Open/Closed 模型选择隐式，阈值与 SLO 无追溯，且 k6 exit code 99 无法区分"系统不达标"与"测试本身无效"。

## Decision

1. **术语**：业务流程称为 **Flow**；"Scenario" 仅指 k6 Scenario（Composer 的编译产物）。
2. **分层**：Service（做什么）→ Flow（顺序）→ Flow Mix（比例）；Load Profile（多少/多快/多久/什么模型）独立为纯数据；二者只在 **Composer**（纯函数）交汇。
3. **显式模型**：Load Profile 必须声明 `model: open | closed`；SLO 验证默认 open（arrival-rate）；closed 需写明理由。
4. **强度与形状分离**：Profile 描述形状（相对比例），Test 提供目标强度。
5. **Open model 下每个 Flow 编译为一个 k6 Scenario**，按权重分配到达率。
6. **SLO 为数据**，Composer 生成 SLO 阈值，并**自动附加 Validity 阈值**（`dropped_iterations`、`checks` 等）。
7. **Verdict** = `passed | failed | invalid | error | aborted`，由 Result Builder 按阈值类别确定性计算；`invalid` 优先于 `failed`。
8. **数据选择只使用 `*InTest` 字段**。

## Options Considered

| 方案 | 结论 |
|---|---|
| 直接手写 `options.scenarios`（官方示例方式） | 拒绝：每个测试类型复制配置，模型隐式 |
| 在一个 iteration 内按权重随机选 Flow | 拒绝：open model 下单个 Flow 的实际到达率不可控 |
| YAML DSL 描述 Flow | 拒绝：业务流程需要分支与提取，JS 更合适 |
| Gatling 风格的 Flow ⟂ Injection ⟂ Protocol 分离 | **采纳其思想**，在 k6 上以 Composer 实现 |

## Consequences

- 同一 Flow 可在 smoke/average/stress/spike/soak/breakpoint 下运行，无需修改业务代码；
- Composer 是唯一需要理解 k6 executor 细节的地方；
- 需要一个 Validity 规则集并随经验扩充；
- Verdict 可直接作为 CI 状态与未来 AI 的可靠输入。

## Reconsideration Conditions

- k6 原生提供了 workload 与 flow 分离的一等机制 → 迁移到原生机制；
- 实践中发现 Composer 需要处理大量特例（> 预期复杂度）→ 回顾分层是否合理。
