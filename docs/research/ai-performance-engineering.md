# Research：AI + Performance Engineering 真实项目

> 研究日期：2026-09-29
> 标记约定：**[事实]** 有来源；**[判断]** 本项目结论；**[推测]** 仅见于二手/竞品来源或无法确认。
> 本文回答：**现实中 AI 在性能测试中到底做了什么？哪些有证据？哪些只是营销？**

---

## 0. 结论先行

| # | 结论 | 类型 |
|---|---|---|
| 1 | 证据最充分的模式是 **k6 Studio autocorrelation**：LLM 输出**结构化关联规则** → 确定性引擎执行 → 回放验证 → 人逐条审核。 | 事实 + 判断 |
| 2 | 几乎所有厂商都发布了 MCP Server，但**大部分是 plumbing（数据/工具访问），不是智能**。价值在权限模型与预聚合数据。 | 判断 |
| 3 | 真正有效的"分析"大多**不是 LLM**：NeoLoad Augmented Analysis（ML 分段）、Grafana Cloud Insights（规则审计）、Apache Otava（Change Point Detection）。 | 事实 |
| 4 | LLM 结果摘要是"基于真实数据的 prose"，**没有任何厂商公布准确率**；Azure 文档明确写 "might not always be accurate"。 | 事实 |
| 5 | 自由形式 LLM RCA 证据薄弱：OpenRCA 最佳模型 **11.34%**；ReAct agent ~35%；RCACopilot 0.766 仅针对**根因类别**且依赖多年积累的确定性诊断流水线。 | 事实 |
| 6 | **没有找到任何评估 LLM 生成压测脚本质量（k6/JMeter）的同行评审研究**。 | 事实（检索范围内） |
| 7 | 回归检测有带标注的 benchmark 与公开 P/R（Mozilla、Hunter）；LLM "insights" 产品没有。 | 事实 |
| 8 | 最常见失败模式：**"脚本能跑 ≠ 测试有效"**、非确定性报告、无 ground truth、对无效测试（负载机饱和、warm-up）视而不见、爆炸半径。 | 判断 |

AI 介入类型：**(a)** 真正介入测试闭环；**(b)** 仅生成文字；**(c)** 仅生成脚本；**(d)** LLM/MCP 薄包装。

---

## 1. 项目逐一评估

### 1.1 grafana/mcp-k6（k6 2.0 中以 `k6 x mcp` 提供）

| 项 | 内容 |
|---|---|
| GitHub | https://github.com/grafana/mcp-k6 ；[docs](https://grafana.com/docs/k6/latest/set-up/configure-ai-assistant/) |
| 维护 | [事实] 50★，push 2026-09-28，21 open issues，README 标注 "Experimental" |
| 技术栈 | Go；stdio / streamable HTTP |
| 定位 | 为外部 coding agent（Claude Code、Cursor）提供 k6 工具 |
| AI 介入点 | 服务器本身**无 AI**；工具：`validate_script`（1 VU × 1 iteration）、`run_script`、`list_sections`、`get_documentation`；prompt 资源 `generate_script` |
| 工作流 | agent 查文档 → 写脚本 → validate（冒烟运行）→ 修错 → run |
| AI 输入 / 输出 | 自然语言意图 + 文档 → k6 脚本 |
| 传统自动化可否替代 | 验证与执行本身就是确定性的；只有"意图 → 脚本"需要 LLM |
| 验证机制 | ✅ 1 VU 冒烟运行 |
| 类型 | (c)+(d)，带验证闭环 |
| 优点 | 文档 grounding 减少 API 幻觉；冒烟 gate |
| 缺点 | 冒烟通过只证明"能跑"，不证明负载真实、阈值合理；`run_script` 可对任意目标加压（爆炸半径） |
| 借鉴 | **文档作为工具 + "先冒烟再加压" gate** |
| 不借鉴 | 让 agent 自由决定目标、VU、时长 |

### 1.2 k6 Studio autocorrelation

| 项 | 内容 |
|---|---|
| GitHub | https://github.com/grafana/k6-studio ；[generator docs](https://grafana.com/docs/k6-studio/components/generator/) |
| 维护 | [事实] 543★，push 2026-09-29；v1.10（2026-01）预览需 OpenAI key → v1.13 改用 Grafana Assistant → v2.0（2026-07-31）GA |
| 技术栈 | Electron + 录制代理 + 规则生成器 |
| AI 介入点 | **关联**：识别动态值（session、CSRF token、ID），生成提取/替换规则 |
| 工作流 | 录制 → 发送至 Assistant → Studio "runs validation to identify mismatches between your recording and a live test run" → AI 提出规则 → **用户逐条审核** → 本地应用 |
| AI 输入 / 输出 | 录制（类 HAR）+ 回放差异 → **声明式规则**（非自由代码） |
| 传统自动化可否替代 | 部分可以：经典启发式（两次录制 diff，找"响应中出现、后续请求回传"的值）LoadRunner/NeoLoad 做了多年。LLM 增加的是歧义情况下的判断与语义命名 [判断] |
| 验证机制 | ✅ 回放 diff + 人工审核 |
| 类型 | **(a)** |
| 缺点 | 录制数据（可能含 PII/token）发往 SaaS；上下文长度限制；月度配额；无公开准确率 |
| 借鉴 | **LLM 输出受约束规则 → 确定性引擎应用 → 回放验证 → 人审** |
| 不借鉴 | 敏感流量不脱敏直接上传 |

### 1.3 k6 2.0 AI 子命令（`k6 x agent / mcp / docs / explore`）

- **[事实]** k6 自身不运行 LLM。`k6 x agent init` 向 `.claude/skills/`、`.cursor/rules/` 等写入 SKILL.md（测试规划、smoke/load/browser、Playwright 转换、文档查询等），并配置 `.mcp.json` 指向 `k6 x mcp`（[k6 2.0 blog](https://grafana.com/blog/k6-2-0-release/)，[xk6-subcommand-agent](https://github.com/grafana/xk6-subcommand-agent)）。
- **[事实]** 同时引入 Assertions API（`expect`），为 agent 提供机器可判定的 pass/fail。
- 类型：(c)+(d)，为外部 agent 提供脚手架。
- **[判断]** 借鉴：把领域知识做成 skill + 可验证工具，而不是产品内聊天机器人。不借鉴：把 skill 文件当作质量保证（没有公开评估）。

### 1.4 Grafana Cloud k6 "Cloud Insights"（非 LLM 对照组）

- **[事实]** 算法化审计，分 Reliability / Best Practice / System（负载机健康）三类，0–100 评分 + pass/fail（[docs](https://grafana.com/docs/grafana-cloud/testing/k6/analyze-results/get-cloud-insights/)），文档未提及 LLM。
- **[推测]** 未找到 Grafana Assistant 分析 k6 Cloud 测试结果的文档。
- **[判断]** 借鉴：**确定性、可解释的有效性审计**（"URL 太多"、"负载机 CPU 过高"），不需要 LLM 就能拦截最常见的无效测试。

### 1.5 AWS Distributed Load Testing（DLT）：MCP Server 与 DevOps Agent 集成

| 项 | 内容 |
|---|---|
| GitHub | https://github.com/aws-solutions/distributed-load-testing-on-aws ；[MCP spec](https://docs.aws.amazon.com/solutions/latest/distributed-load-testing-on-aws/mcp-tools-specification.html) |
| 维护 | [事实] 419★，push 2026-09-25；v4.2.0（2026-07-23）加入 DevOps Agent 集成；v4.3.0（2026-09-25）加入 MCP 写操作（默认关闭） |
| 架构 | MCP client → Bedrock AgentCore Gateway（Cognito 校验）→ Lambda → 现有 DLT REST API；Fargate 运行 JMeter/k6/Locust |
| 工具 | ReadOnly（默认）7 个：list/get scenarios、test runs（p50/90/95/99 按区域/endpoint）、`get_baseline_test_run`、artifacts；ReadWrite 增加创建/启动/调度/上传脚本；`get_workflow_guides` 提供流程配方 |
| AI 介入点 | 内置无 AI；供外部 agent 访问数据。DevOps Agent 可"从压测运行发起调查" [推测：触发机制与数据源未能获取] |
| 类型 | (d)，但工程化程度最高 |
| 借鉴 | **默认只读；写工具不注册；由 IAM 强制，而非 prompt 约束**；Baseline run 为一等对象；服务端提供流程配方 |
| 不借鉴 | baseline 对比交给 LLM 算。**数值比较应确定性完成，LLM 最多负责叙述** |
| 其他 | aws-samples/load-test-llm-with-locust 是压测 LLM 端点（AI 是被测对象）。未找到用 Bedrock agent 做性能工程的实质性 aws-samples 项目 [判断] |

### 1.6 Azure Load Testing：AI Actionable Insights / VS Code Copilot / Azure MCP

- **[事实]** Insights 在运行后按需生成，关联客户端与服务端（Azure Monitor）指标，服务端指标是前提；输出摘要、关键洞察、支撑证据、下一步建议；文档警示 "AI-generated insights might not always be accurate... validate with your application's telemetry"（[docs](https://learn.microsoft.com/en-us/azure/app-testing/load-testing/how-to-analyze-test-results-using-actionable-insights)）。类型 (b)。
- **[事实]** VS Code 扩展（~5★）通过 Copilot 从 Postman/Insomnia/.http 生成 **Locust** 脚本，可本地运行（[GitHub](https://github.com/microsoft/azureloadtesting-extension)）。类型 (c)。
- **[事实]** Azure MCP Server（microsoft/mcp，3.7k★）提供 loadtesting 命令。类型 (d)。
- **[判断]** 借鉴：每条洞察附证据；**以服务端指标为前提**（只有客户端数据无法支撑 RCA）。不借鉴：把非确定性文字洞察作为 gate。

### 1.7 Tricentis NeoLoad：Augmented Analysis / MCP / Agentic Performance Testing

- **[事实]** Augmented Analysis（2025.1）：基于 RED 指标的 **ML**，将运行切分为带标签的区间（如"负载增加下稳定"、"退化"），按区间重算指标；Tricentis 明言"not a magic fix"，仍需 APM 回答"为什么"；算法未公开（[release notes](https://docs.tricentis.com/neoload-web-v2/en-us/content/release_notes.htm)，[shiftsync](https://shiftsync.tricentis.com/neoload-77/augmented-analysis-in-neoload-web-how-ai-turns-load-test-data-into-decisions-2561)）。**[判断]** 功能上等价于 change-point/分段方法，不是 LLM。
- **[事实]** MCP（2025）：`get-result-timeseries/contexts/slas/statistics`、`update-result`（agent 把结论写回结果）；2026-04 约 45 个工具，改用 `mcp_discover/mcp_execute` 元工具节省上下文。
- **[事实]** 2026-05 AI 报告（按 credit 计费），2026-08 AI chat 可启动/停止测试。
- **[判断]** 借鉴：**计算百分位前先把运行分段（稳态 vs 爬坡）**——不需要 LLM；分析结论写回结果记录形成审计轨迹。不借鉴：不透明、按量计费的报告作为事实来源。

### 1.8 OpenText Performance Engineering（原 LoadRunner）Aviator

- **[事实]**（搜索摘要）VuGen 内 Aviator 聊天；对回放日志错误 "Ask Aviator" 解释并建议修复。
- **[推测]**（仅见 Gatling 竞品博客）Aviator for Analysis、MCP、Gemini 后端。
- 类型 (b)+(c)。**[判断]** 最具体的价值是**基于一次真实失败回放日志**的解释。

### 1.9 BlazeMeter AI Anomaly Analysis

- **[事实]** 先由既有 Anomaly Detection（方法未公开）标记异常；"Analyze with AI" 取异常附近的 JMeter 错误日志与响应体，由 LLM 聚类为不同问题并给出解释与建议；**硬上限：前 50 个异常**（[docs](https://help.blazemeter.com/docs/guide/performance-ai-anomalies.htm)）。
- 类型 (b)，但输入合理。**[判断]** 借鉴：**确定性检测器在前，LLM 只解释/聚类被标记的非结构化证据**。不借鉴：静默截断。

### 1.10 Gatling AI Assistant / gatling-ai-extensions

- **[事实]** [gatling-ai-extensions](https://github.com/gatling/gatling-ai-extensions)（Apache-2.0，~5★）：skills 包括 `convert-from-jmeter`、`convert-from-loadrunner`、bootstrap 等；MCP 查询 Enterprise 资源（[docs](https://docs.gatling.io/ai/)）。
- **[事实]**（厂商博客）IDE 助手 BYO key 生成多语言 simulation；"AI Insights" 自然语言对比运行。
- **[判断]** 借鉴：**脚本迁移（JMX/VuGen → 代码）**是合理的 LLM 场景：繁琐、半结构化、可由编译 + 冒烟验证。不借鉴：没有统计检验支撑的自然语言运行对比。

### 1.11 Artillery / QAInsights jmeter-mcp-server / 社区 k6 "AI" 项目

- **[事实]** Artillery（9k★）无官方 AI；社区 MCP 包装 CLI。类型 (d)。
- **[事实]** [QAInsights/jmeter-mcp-server](https://github.com/QAInsights/jmeter-mcp-server)（~74★）：**分析在代码中计算**（JTL 解析、百分位），LLM 只消费数字。借鉴：预聚合；不借鉴：未文档化的启发式阈值。
- **[事实]** 某社区 "AI-native k6 MCP server"（0★）实际为**模板生成**，无 LLM 代码生成——典型的"定位 > 实质"。
- 注意区分：periscope、xk6-llm 等是**压测 LLM 端点**，AI 是被测对象，不属于本主题。

---

## 2. 学术研究

| 研究 | 内容 | 关键数字 | 启示 [判断] |
|---|---|---|---|
| **RCACopilot**（Microsoft, EuroSys'24, [arXiv](https://arxiv.org/abs/2305.15778)） | 基于 handler 的诊断信息收集（部署 4 年+）+ GPT-4 摘要 + 历史事件 few-shot 检索 → 预测根因**类别** | 准确率 ≤ 0.766 | 大部分工作由确定性收集流水线完成 |
| **RCAgent**（Alibaba, CIKM'24, [arXiv](https://arxiv.org/abs/2310.16340)） | 工具增强自主 agent，内部部署模型；自一致性 | 优于 ReAct（自动+人工评估） | 需要私有部署与大量工程 |
| **LLM Agents for RCA**（Microsoft, FSE'24, [arXiv](https://arxiv.org/abs/2403.04123)） | ReAct agent vs CoT/检索基线 | ~35% vs ~39%，幻觉更少 | agent 并不天然更准 |
| **OpenRCA**（Microsoft, ICLR'25, [GitHub](https://github.com/microsoft/OpenRCA)） | 335 个故障、68GB 日志/指标/trace | 最佳 LLM **11.34%** | **原始遥测上的自由形式 LLM RCA 不可靠** |
| **RCAEval**（WWW'25, [arXiv](https://arxiv.org/abs/2412.17015)） | 735 个故障案例、11 种故障类型、15 个可复现基线 | — | 评估任何 RCA 声称的 ground-truth benchmark |
| **CALLMIT**（FORGE'25, [IEEE](https://ieeexplore.ieee.org/document/11052809/)） | LLM + 因果图提出可能违反性能需求的 workload 配置 | 效果量 [推测] | 测试规划方向，学术规模 |
| **ServeGen**（[arXiv](https://arxiv.org/abs/2505.09999)） | 基于生产特征的统计 workload 生成（面向 LLM serving） | 避免 50% 资源不足 | 这是**统计建模**，不是 LLM 生成负载 |
| **Apache Otava / Hunter**（ICPE'23, [arXiv](https://arxiv.org/abs/2301.03034)） | E-divisive CPD | 18,000–300,000× 加速（[arXiv 2505.06758](https://arxiv.org/abs/2505.06758)） | 回归检测用统计方法 |
| **Mozilla CPD 研究**（[arXiv 2606.18377](https://arxiv.org/abs/2606.18377)） | 25 种 CPD + 15 种 ensemble，174 条专家标注序列 | 现有 t-test 12.5% FP；ensemble F1 +11% | 回归检测已有可量化的非 LLM 方案 |

**[事实]** 检索范围内未找到对 LLM 生成 k6/JMeter 脚本真实性/有效性的同行评审评估；LLM 测试生成文献几乎全部针对单元测试。

---

## 3. 综合：AI 介入点分类

| 介入点 | 例子 | 价值证据 | 判断 |
|---|---|---|---|
| 自然语言 → 脚本 | mcp-k6、Azure → Locust、Gatling | 只有厂商 demo，无真实性指标 | 脚手架可用，价值取决于冒烟 gate；已商品化 |
| 脚本迁移（JMX/VuGen → 代码） | Gatling skills | 可编译 + 回放验证 | **合适**：繁琐、有边界、可检查 |
| 关联/参数化 | k6 Studio | 回放 diff + 结构化规则 | **证据最充分**；但启发式已覆盖大部分情况 |
| 回放错误解释 | OpenText Aviator | 基于具体失败日志 | 小而真实 |
| 结果摘要（文字） | Azure、Gatling、NeoLoad APT | 厂商自己声明可能不准 | 除非绑定确定性证据，否则主要是便利/营销 |
| 异常/区间检测 | NeoLoad（ML）、Cloud Insights（规则）、Otava（CPD） | CPD 有 benchmark 与 P/R | **真实价值，但不是 LLM 的工作** |
| 已标记异常的错误聚类 | BlazeMeter | 合理（非结构化文本），无指标 | 位于确定性检测器下游时适合 LLM |
| RCA | RCACopilot、RCAgent、Azure | OpenRCA 11%，ReAct 35%，RCACopilot 77%（仅类别） | 只能作为**基于精选证据的候选假设排序** |
| 测试规划 | CALLMIT | 仅学术 | 有潜力，未经证实 |
| 基于生产流量的负载建模 | 未见 LLM 形式 | — | 经典 trace 建模更优 |
| MCP 工具访问 | 各厂商 | 质量取决于 guardrail | **plumbing，不是智能** |

---

## 4. 常见失败模式

1. **API 幻觉**：不存在的 k6 模块/选项。缓解：文档检索工具 + 1 VU 验证。
2. **能跑 ≠ 有效**：冒烟通过不能证明并发下关联正确、think time/pacing 真实、数据唯一、Open/Closed 选择正确。**没有任何产品验证负载真实性**。
3. **非确定性报告**：同一运行得到不同"洞察"，不可复现、不可 diff、不能做 CI gate。
4. **无 ground truth**：厂商洞察功能没有标注评估。只有学术 RCA（OpenRCA、RCAEval）与 CPD 有 benchmark，而在那里 LLM 表现较弱。
5. **对无效测试视而不见**：把负载机饱和、warm-up 窗口、错误拉低的延迟解读为"回归"。确定性审计能处理，LLM 摘要通常不能。
6. **上下文限制与截断**：原始遥测放不进上下文，**预聚合是必须的**。
7. **爆炸半径**：带运行/写权限的 agent 可以对任意目标加压。
8. **数据外泄**：录制与响应体（token、PII）发往 SaaS LLM。
9. **定位膨胀**："AI-native" 实际是模板引擎。

---

## 5. 对本项目的设计原则（来自研究）

1. **确定性 Core**：指标聚合、SLO/阈值判定、baseline 对比（统计检验/CPD）、测试有效性审计全部是代码。**LLM 只消费它们的输出，永远不看原始时序，永远不决定 pass/fail**。
2. **LLM 只输出受约束的产物**（规则、配置 diff、脚本 patch），每个产物在接受前通过执行验证（冒烟、回放 diff、阈值）。
3. **每条 LLM 结论必须引用证据 ID**（runId、指标查询、日志片段）。
4. **工具权限**：默认只读；运行/写工具在基础设施层限制（目标白名单、VU 上限），而不是靠 prompt。
5. **先有标注数据再谈可信**：任何 RCA/洞察功能必须先在带标注的故障（如 OpenTelemetry Demo 的 flagd 故障开关）上评估。
6. **不重复商品化能力**：自然语言 → 脚本已由 `k6 x mcp` 等提供，本项目不再实现。
