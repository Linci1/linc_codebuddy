# CodeBuddy 2.0 实施路线图

> 执行原则：按里程碑逐步交付，每个里程碑都必须可单独验证和回滚。不要在同一轮同时实现整套体系。

## 0. 接手协议

后续模型开始任何实现前：

1. 完整阅读 `README.md` 和 `technical-design.md`；
2. 运行 repo intake，检查当前分支、未提交修改和测试入口；
3. 将现有未知修改视为用户资产，不覆盖、不回滚；
4. 读取当前 `SKILL.md`、`run_agent.py`、`agent_state.py`、`sync_tasks.py`、`create_work_item.py`、`patrol_repo.py`、`mcp_server.py`；
5. 先补现状测试或建立 characterization test；
6. 只推进当前里程碑；
7. 发现方案与代码事实冲突时，先更新设计和说明影响；
8. 未经用户明确要求，不提交、推送、发布或安装到全局环境。

## 1. 里程碑总览

| 版本 | 目标 | 核心交付 |
|---|---|---|
| V2.0 | 可靠状态基础 | 稳定 ID、精确任务、state V2、修复 ship、next |
| V2.1 | 自适应治理 | classify、L0-L3、动态升级、最少必要产物 |
| V2.2 | 规范驱动变更 | project/change、phase、gate、审批记录 |
| V2.3 | 质量闭环 | evidence、追踪矩阵、verify、drift |
| V2.4 | GitLab 与多项目 | Issue/MR/CI/Release 引用、workspace 状态 |
| V3（候选） | 常驻编排 | 暂停恢复、定时巡检、多 Agent 独立评审 |

## 2. V2.0：可靠状态基础

状态：Implemented locally（2026-07-28），尚未提交或推送。

### 目标

消除错误完成任务和跨会话状态不明确的问题，使 CodeBuddy 能可靠回答“当前做什么、下一步做什么”。

### 范围

1. 为 work item 和 task 引入稳定 ID；
2. state 增加 `schema_version` 和 V1 -> V2 migration；
3. active task 从标题匹配改为 ID；
4. 修复 `ship --execute` 批量关闭全部 Active 任务；
5. ship 必须关联明确 task/change；
6. 新增确定性的 `next` 决策；
7. CLI、JSON 和 MCP 返回兼容信息；
8. 增加自动化测试。

### 明确不做

- 不实现完整 requirements/design/gate；
- 不接 GitLab API；
- 不引入 LangGraph；
- 不调整所有文档目录；
- 不做多 Agent 编排。

### 推荐任务

1. `TASK-V20-001`：为现有行为建立 characterization tests；
2. `TASK-V20-002`：定义 state V2 schema 和 migration；
3. `TASK-V20-003`：实现稳定 ID 与精确任务操作；
4. `TASK-V20-004`：修复 ship，仅关闭关联任务；
5. `TASK-V20-005`：实现 `next` 决策和输出；
6. `TASK-V20-006`：扩展 CLI/MCP，更新 SKILL 和参考文档；
7. `TASK-V20-007`：在临时仓库完成端到端回归。

### 验收标准

- 两个 Active 任务存在时，ship 指定 TASK-A 后只有 TASK-A 变为 done；
- 未指定 task ID 的老调用不会批量关闭任务；
- V1 state 可无损迁移，迁移前有备份或 dry-run；
- state 写入中断不会留下半个 JSON；
- `next` 在 blocked、active、ready 和 idle 场景返回稳定结果；
- 所有测试在临时目录运行，不污染真实仓库；
- 原有 intake、patrol、kickoff、review 和建议式 ship 继续可用。

### 停止点

完成验收后停止，向用户报告设计偏差、测试结果和 V2.1 建议，等待确认。

### 本地实施记录

- 已增加 `WI-YYYYMMDD-NNN` 和 `TASK-YYYYMMDD-NNN` 稳定 ID；
- 已实现 state schema V2、V1 自动迁移、备份和原子写入；
- kickoff 已记录 work item ID、active task ID 和 next action；
- executable ship 已强制要求 task ID，并只关闭指定任务；
- 已增加 CLI/MCP `next`；
- 已保留旧标题任务的读取与手动迁移兼容；
- 已增加临时 Git 仓库端到端测试，并纳入 quick validation；
- 实施中发现并修复既有 execute 路径缺少 `is_agent_metadata_path` 导入的问题。

验证命令：

```text
python3 -B -m unittest discover -s tests -v
python3 -B scripts/quick_validate.py
python3 -B -m py_compile scripts/*.py tests/*.py
```

## 3. V2.1：自适应治理

状态：Implemented locally（2026-07-28），尚未提交或推送。

### 目标

让简单任务快速推进，让复杂或危险任务自动提升治理深度。

### 范围

1. 定义 L0-L3 分类输出和 policy；
2. 实现六维评分与高风险硬规则；
3. kickoff/auto 输出 level、理由和本次最小流程；
4. 按等级生成最少必要产物；
5. 实施中发现风险时支持升级；
6. 高风险降级要求批准与留痕；
7. 增加 `classify` CLI/MCP。

### 验收场景

- 修改按钮文案判定为 L0，不创建完整 change 目录；
- 根因明确的局部 Bug 判定为 L1，只生成简短 work item；
- OIDC、权限或数据迁移最低为 L2；
- 初始 L0 在发现认证影响后升级为 L2，并阻止继续快修；
- 用户批准降级时记录理由；
- 相同输入在同一 policy 下给出可重复的硬规则结果。

### 停止点

至少选择一个 L0 和一个 L2 真实项目试点，记录流程成本和误判，再决定 V2.2。

### 本地实施记录

- 已实现六维评分、L0-L3 输出和 policy 阈值；
- 已实现认证、权限、敏感信息、迁移、生产和新项目等硬规则；
- 已增加 CLI/MCP `classify`，支持结构化评分和持久化；
- kickoff 已输出 level、理由、流程和必要产物；
- L0 只创建 task/state，不创建 worklog；L1-L3 继续按现有 work item 承载，避免提前引入 V2.2 目录；
- active task 发现风险时可自动升级，并记录 classification history；
- 非硬风险降级必须显式批准并填写理由；硬最低等级不可降级；
- 已验证完成的高风险任务不会污染下一项低风险工作；
- 已用“修改按钮文案”完成 L0 试点，用“调整 OIDC 登录权限”完成 L2 试点；
- 初始规则曾将“登录按钮文案”误判为 L2，已将宽泛“登录”信号收窄为登录流程、逻辑和账号校验等行为性信号。

## 4. V2.2：规范驱动变更

**状态：已在本地实现并通过验收，停在 V2.3 前。**

### 目标

复杂需求在编码前形成可审核、可追溯的依据。

### 范围

1. project/change 数据模型；
2. explore/specify/design/plan/implement/verify 等 phase；
3. change 目录及按需产物；
4. phase transition；
5. 自适应 gate；
6. approval 和 override 记录；
7. `project init`、`change`、`gate` CLI/MCP；
8. 将现有 route 映射到 phase，而非替换 route。

### 验收场景

- L2 change 缺少验收场景时不能进入 implement；
- L1 可以合并设计与计划，不被迫生成空文件；
- phase 可以在 verify 失败后回退 implement；
- gate 返回缺失事实及唯一建议动作；
- 生产、权限和不可逆动作不能被普通 force 静默绕过；
- 新会话只读仓库即可恢复当前 phase 和 active change。

### 停止点

用 CodeBuddy 自身的一个真实功能完整跑完 specify -> verify，复盘文档负担和门禁有效性。

### 本地实现记录

- 已加入 repository-backed project/change 模型和稳定 `CHG-YYYYMMDD-NNN-slug` ID；
- 已加入 phase 合法迁移、迁移历史、gate、approval/override 记录；
- L0 继续不创建 change，L1 可从 specify 直接进入 implement 且不生成空 design/tasks 文件；
- L2 缺少 acceptance 时无法进入 implement，gate 返回缺失事实和一个建议动作；
- verify 失败可带原因回退 implement；生产、权限、删除和不可逆风险不能被普通 override 绕过；
- 已加入 `project init`、`change create/show/update/transition`、`gate` CLI，以及聚合 MCP 工具；
- `next` 已优先读取 active change 的 phase/gate，同时 route 保持独立；
- `project.yaml` 和 `change.yaml` 当前写入 JSON 兼容 YAML，避免新增 PyYAML 运行依赖；
- 已用临时仓库完成 L1 和 L2 生命周期试跑，新进程可仅凭仓库文件恢复 active change、phase 和 level；
- V2.3 evidence matrix、drift、GitLab 同步和多 Agent 编排均未开始。

## 5. V2.3：质量闭环

**状态：已在本地实现并通过验收，停在 V2.4 前。**

### 目标

从“运行过测试”升级为“有证据证明需求被实现”。

### 范围

1. evidence 模型与存储；
2. requirement/acceptance/task/test/evidence 追踪矩阵；
3. `verify` 汇总技术、行为和需求验证；
4. 独立 review 结果关联 change；
5. `drift` 启发式检查；
6. CI URL 和本地命令结果引用；
7. release readiness 判断。

### 验收场景

- 建议命令不会被误记为已执行；
- 测试成功但 acceptance 缺证据时 change 不能通过 verify；
- 超出 change scope 的文件被 drift 标记；
- requirement 更新后旧 evidence 被标记为待重新确认；
- review finding 可以阻塞 release；
- evidence 不包含秘密和不必要的大段日志。

### 本地实现记录

- 已加入 `EVD-NNN` evidence 记录，支持 command/api/ui/manual/ci/review 类型，以及 acceptance、requirement、task 关联；
- 建议检查与执行证据完全分离，只有显式 `evidence record` 才会写入事实记录；
- evidence 摘要限制为 2000 字符，并对 token、secret、password、API key 和 Bearer token 做基础脱敏；
- 已实现 acceptance/requirement 指纹，规范内容改变后旧 evidence 自动标记 stale；
- `verify` 同时输出结构化汇总和 change 目录中的 `verification.md` 追踪矩阵；
- acceptance 或 requirement 缺证据、证据陈旧、high/critical review finding 未解决时，不具备 release readiness；
- release gate 已接入 verification summary，无证据时阻断，补齐证据后放行；
- `drift` 当前只读报告 scope 外文件和 stale evidence，不修改或回滚源码；
- 已加入 `evidence record/list`、`verify`、`drift` CLI 与聚合 MCP 工具，`next` 在 verify 阶段优先返回证据缺口；
- 已用临时 Git 仓库跑通 implement -> verify -> release gate，并验证范围漂移；
- GitLab 同步、CI 主动读取、release 外部写入和多项目汇总仍留待 V2.4。

## 6. V2.4：GitLab 与多项目

**状态：本地安全适配层已实现并通过离线验收；真实 GitLab API 连接器尚未启用。**

### 目标

将本地工程状态与 GitLab 的协作、CI 和发布能力连接，同时保持权威边界清晰。

### 范围

1. change 引用 GitLab Milestone/Issue；
2. task 引用 Issue；
3. verification 引用 Pipeline/MR；
4. release 引用 Tag/Release/Environment；
5. workspace 汇总 phase、blocking 和 next；
6. 同步 dry-run、幂等和冲突检测；
7. 所有外部写操作遵守权限和批准策略。

### 明确原则

- 仓库保存目标、需求、设计和决策；
- GitLab 保存 Issue、MR、CI、Release 和 Environment；
- 不做无策略的双向字段覆盖；
- 默认先只读同步，再逐步开放写入；
- 外部写入必须报告具体目标和结果。

### 本地实现记录

- 已加入 GitLab reference snapshot 模型，覆盖 change→Milestone/Issue、task→Issue、verification→MR/Pipeline、release→Release/Environment；
- 同步默认 dry-run，`--apply` 只更新本地 change 引用，不向 GitLab 写入；
- 相同快照重复同步返回 noop，不产生重复历史；远端对象 ID 与已有绑定不一致时返回 conflict 并拒绝覆盖；
- GitLab 响应采用字段白名单，只保留 ID、状态、标题、URL、时间和必要版本引用，不复制描述、评论、作者或用户资料；
- 外部写入适配接口要求 `execute + approval_ref + actor + executor`，当前未提供通用真实写 CLI，避免误操作；
- workspace status 已汇总 branch、dirty、active change、phase、level、blocking 和 next action；
- 已加入 `gitlab sync --snapshot` CLI、`lcb_gitlab_sync` 和 `lcb_workspace_status` MCP；
- 已用临时仓库验证 `planned -> applied -> noop` 成功路径和 binding conflict 失败路径；
- 尚未配置任何真实 GitLab 地址、token 或项目 ID，也未访问或修改公司 GitLab；
- 真实 GitLab 只读获取、分页/限流、认证、网络错误恢复，以及批准后的 Issue/MR/Release 写执行器需要作为独立集成阶段完成。

### 当前判断

V2.0-V2.4 的确定性工程骨架已经形成。下一步不应立即引入 LangGraph 或多 Agent 常驻运行时，应先选一个真实项目连续使用，验证流程负担、状态恢复、证据质量和 GitLab 引用模型；只有出现长任务恢复、并行隔离或定时巡检的明确瓶颈，再评估 V3。

## 7. V3 候选：常驻工程 Agent

**当前决策：No-Go，继续使用 V2 做真实项目试点。**

只有 V2.0-V2.4 经真实项目验证后才评估：

- LangGraph 负责暂停、恢复、条件分支和人工审批；
- 定时 workspace 巡检；
- 长任务失败恢复；
- 分离产品、架构、开发、测试和发布审查上下文；
- 多 Agent 并行只用于可独立验证的任务；
- 可选长期检索层，但仓库和 GitLab 继续作为事实来源。

不得因为“多 Agent”本身而进入 V3。

### 首轮真实试点记录

CodeBuddy 自身作为首个真实 L1 change，完整运行了 specify -> implement -> verify，并生成 acceptance evidence 和 verification matrix。

观测结果：

- 仓库状态成功恢复 1 次，人工上下文重建 0 分钟；
- 结构化产物约 3 分钟，仅创建 change、pilot 和 verification/evidence 文件；
- false gate block 为 0；
- long-task resume failure 为 0；
- parallelizable blocked work 为 0；
- V3 判断为 no-go，继续 V2 真实使用。

试点发现并修复了三个 V2 工程问题：

- 同 schema 的旧 state 缺省字段只在内存补齐、未回写磁盘；
- verify 已通过时，通用 dirty fallback 抢占了 lifecycle 的 release 建议；
- phase 转换后 state 中的 next_action 仍描述旧转换动作。

这些问题均可由确定性状态代码修复，不需要引入 LangGraph、常驻 Agent 或多 Agent 编排。

### V3 重新评估条件

满足下列至少一项并在多个真实 change 中重复出现，再建立 V3 scoped experiment：

- long-task resume failure 累计至少 2 次；
- 可独立执行的工作因串行流程阻塞累计至少 2 次；
- 明确需要无人值守定时巡检累计至少 2 次；
- 现有仓库状态机无法表达必须暂停和恢复的审批流程。

## 8. 每个里程碑的通用完成定义

每个里程碑完成时必须提供：

1. 本次范围与明确未做事项；
2. 代码和 schema 变化；
3. 向后兼容与迁移结果；
4. 自动测试及真实执行结果；
5. 一个成功路径和一个失败路径的端到端验证；
6. 已知风险和技术债；
7. 文档更新；
8. 下一里程碑是否仍值得做的判断。

## 9. 后续模型首轮执行提示

将下面内容作为开始 V2.0 的任务说明：

```text
请继续开发 linc_codebuddy 的 CodeBuddy 2.0。

先完整阅读：
- docs/codebuddy-2/README.md
- docs/codebuddy-2/technical-design.md
- docs/codebuddy-2/implementation-roadmap.md

本轮只做 V2.0“可靠状态基础”的分析和实施，不提前实现 V2.1 及以后能力。

开始前必须：
1. 检查 git status、当前 diff、分支和远端；
2. 保留并兼容所有未知的用户改动；
3. 阅读现有 state、task、ship、MCP 和测试实现；
4. 先给出 V2.0 的源码现状分析、变更文件、兼容方案和测试计划；
5. 确认设计与现有代码无重大冲突后再实现；
6. 使用临时仓库测试，不能污染真实项目；
7. 不提交、不推送、不全局安装，除非我明确要求。

V2.0 必须交付：
- 稳定 work item/task ID；
- state schema V2 与 V1 migration；
- 精确 active task；
- ship 只关闭指定任务；
- lcb_next；
- CLI/MCP 兼容；
- 自动化测试和端到端验证。

完成后停下来，汇报变更、验证、兼容性、剩余风险和 V2.1 建议，等待确认。
```
