# CodeBuddy 2.0 技术设计草案

> 本文档定义建议的数据模型、目录、状态机、门禁和兼容策略。实现过程中允许细化，但改变核心边界需要记录设计决策。

## 1. 设计目标

- 在现有 Skill、CLI、MCP 和 Python 脚本上增量演进；
- 保持 `new / continue / review / hotfix / ship` 兼容；
- 用确定性代码管理状态、ID、阶段和门禁，避免交给模型自由解释；
- 文本产物面向人和 Agent，结构化状态面向程序；
- 简单任务不创建冗余文件；
- 所有状态更新原子化、可迁移、可审计；
- 第一阶段不依赖 LangGraph、数据库或常驻服务。

## 2. 建议目录

继续复用当前 `.codex/linc_codebuddy/`，避免立即引入 `.codebuddy/` 形成双轨。待 V2 稳定后再决定是否迁移目录名称。

```text
.codex/linc_codebuddy/
  project.yaml
  state.json
  policy.json
  migrations/
  changes/
    CHG-YYYYMMDD-NNN-slug/
      change.yaml
      requirements.md
      design.md
      tasks.yaml
      verification.md
      release.md
  decisions/
    ADR-NNN-title.md
  evidence/
    <change-id>/
```

按等级按需创建：

- L0：只更新 state/history，不创建 change 目录；
- L1：创建 `change.yaml`，必要时内嵌验收和任务；
- L2：创建 requirements、design、tasks、verification；
- L3：增加 project、路线图和跨 change 决策。

## 3. 状态模型 V2

建议 schema：

```json
{
  "schema_version": 2,
  "repo_root": "/path/to/repo",
  "project": {
    "id": "PRJ-pandawiki-eco-partner",
    "phase": "implement",
    "milestone": "v1-user-sync"
  },
  "active": {
    "change_id": "CHG-20260728-001-bbs-user-sync",
    "task_id": "TASK-004",
    "route": "continue",
    "level": "L2",
    "next_action": "实现 OIDC claim 持久化"
  },
  "blocking": [],
  "unvalidated_assumptions": [],
  "approvals": [],
  "versions": {
    "development_commit": null,
    "production_version": null
  },
  "history": [],
  "updated_at": "ISO-8601"
}
```

要求：

- schema 必须有版本；
- V1 状态通过显式 migration 转为 V2；
- 写入使用临时文件加原子替换；
- 更新时保留未知字段，避免未来版本降级破坏；
- active task 最多一个；
- history 是摘要，不替代 Git 历史和 evidence；
- 不在状态文件中保存凭据、业务数据或大段模型输出。

## 4. ID 模型

必须使用稳定 ID，不再以标题作为更新主键：

```text
PRJ-<slug>
CHG-YYYYMMDD-NNN-<slug>
TASK-<change-sequence>
REQ-<change-sequence>
ACC-<change-sequence>
EVD-<change-sequence>
ADR-NNN
```

标题可以修改，ID 不变。任务完成、commit 关联和 GitLab 同步都以 ID 为准。

## 5. Change 模型

L1 以上使用 `change.yaml`：

当前 V2.2 实现使用 JSON 语法写入 `.yaml` 文件。JSON 是 YAML 1.2 的子集，这样文件仍可由 YAML 工具读取，同时 CLI 在没有 PyYAML 的个人开发环境中只依赖 Python 标准库。后续若引入 YAML 专属语法，需要先增加解析依赖和迁移测试。

```yaml
schema_version: 1
id: CHG-20260728-001-example
title: 示例变更
level: L1
phase: implement
status: active
problem: 要解决的问题
outcome: 期望结果
in_scope: []
out_of_scope: []
acceptance:
  - id: ACC-001
    scenario: 可验证场景
risks: []
approvals: []
created_at: ISO-8601
updated_at: ISO-8601
```

L2/L3 的详细需求和设计放 Markdown，结构化索引仍留在 `change.yaml`。

## 6. Task 模型

`tasks.yaml` 建议结构：

```yaml
schema_version: 1
change_id: CHG-...
tasks:
  - id: TASK-001
    title: 明确字段映射
    status: done
    depends_on: []
    completion_conditions:
      - BBS claim 样例已经确认
    verification:
      - evidence_id: EVD-001
    requirement_ids: [REQ-001]
  - id: TASK-002
    title: 实现字段持久化
    status: active
    depends_on: [TASK-001]
    completion_conditions: []
    verification: []
    requirement_ids: [REQ-001, REQ-002]
```

状态至少包括 `planned / ready / active / blocked / done / cancelled`。

约束：

- 同一 change 最多一个 active task；
- 依赖未完成的任务不能进入 active；
- `ship` 只允许关闭明确传入的 task ID；
- 未满足 completion conditions 或缺少要求的 evidence，不能转 done；
- cancel 必须有理由；
- GitLab Issue 映射是引用，不改变本地 ID。

## 7. Phase 状态机

合法阶段：

```text
explore, specify, design, plan, implement,
verify, release, operate, learn, completed, cancelled
```

默认正向转换：

```text
explore -> specify -> design -> plan -> implement
implement -> verify -> release -> operate -> learn -> completed
```

允许回退，例如 verify 失败回到 implement，设计假设失效回到 specify/design。每次转换记录：

- from / to；
- actor；
- reason；
- gate result；
- timestamp；
- approval reference（如需要）。

L0 不必完整走状态机；L1 可以合并 specify/design/plan，但仍要有目标、完成条件和验证。

## 8. 分级引擎

第一版采用确定性规则和模型建议结合：

1. 程序扫描仓库和关键词产生风险信号；
2. Agent 根据用户目标补充不确定性与业务影响；
3. 硬规则给出最低等级；
4. 输出 level、confidence、reasons、required artifacts；
5. 后续发现新风险时重新分类并升级。

建议评分维度每项 0-3：

- requirement_uncertainty；
- change_scope；
- data_impact；
- security_auth_impact；
- production_impact；
- rollback_difficulty。

硬信号优先于总分。认证、权限、不可逆数据和生产操作最低 L2。

## 9. 门禁模型

门禁输出：

```json
{
  "allowed": false,
  "from_phase": "design",
  "target_phase": "implement",
  "level": "L2",
  "missing": [
    {"code": "ACCEPTANCE_UNCONFIRMED", "message": "验收场景未确认"}
  ],
  "warnings": [],
  "next_action": "确认 requirements.md 中的验收场景",
  "requires_approval": false
}
```

最低门禁：

| 转换 | L1 | L2/L3 |
|---|---|---|
| specify -> design | 目标和完成条件 | 问题、范围、需求、验收和关键假设 |
| design -> plan | 可省略独立设计 | 影响面、方案、风险、兼容和回滚 |
| plan -> implement | 任务明确 | 依赖、完成条件、验证方法、必要批准 |
| implement -> verify | 改动完成、针对性测试 | 实现任务完成、技术检查和迁移准备 |
| verify -> release | 完成条件通过 | 验收矩阵有证据、风险已处理或接受 |
| release -> operate | 发布说明 | 部署/回滚/生产验证齐全且获得批准 |

`--force` 不得静默绕过认证、授权、生产、数据删除或不可逆操作门禁。允许的 override 必须记录 actor、理由、风险和时间。

## 10. Next 决策

`next` 必须尽量由结构化状态确定，不让模型自由发散：

1. 有 blocking：返回最高优先级 unblock 动作；
2. 当前 phase 门禁缺失：返回补齐门禁的动作；
3. 有 active task：返回该任务的下一个未完成条件；
4. 无 active task：从依赖已满足的 ready task 中选择关键路径任务；
5. implement 完成：进入 verify；
6. verify 失败：返回到关联实现任务；
7. 无 active change：建议建立 change 或保持 idle。

输出至少包含 phase、level、change ID、task ID、next action、reason、can_modify_code 和 requires_approval。

## 11. 验证与证据

建议 `verification.md` 包含追踪矩阵：

| Requirement | Acceptance | Implementation | Test | Evidence | Status |
|---|---|---|---|---|---|

Evidence 元数据至少记录：

- evidence ID；
- 类型（command/api/ui/manual/ci）；
- 执行时间；
- command 或步骤；
- exit code / 结果；
- 关联 requirement、acceptance 和 task；
- 运行环境；
- 原始输出路径或 CI URL。

“建议运行的检查”和“已经运行的证据”必须分开。未经执行的命令不能标记通过。

V2.3 的 evidence 使用每条一个 JSON 文件，位于 `.codex/linc_codebuddy/evidence/<change-id>/EVD-NNN.json`。只保存截断和脱敏后的摘要、执行元数据及外部引用，不内嵌完整日志。Acceptance 和 requirement 记录内容指纹，内容更新后旧 evidence 进入 stale 状态，必须重新确认。

## 12. 漂移检测

V2 初期先实现可解释的启发式检查：

- diff 中的文件不在 change scope 或 task 预期范围；
- commit message 未引用 change/task ID；
- task 完成但 acceptance 无 evidence；
- requirements/design 修改后实现未重新确认；
- active task 与当前 milestone 无关联；
- 新增能力没有 requirement ID；
- 多次提交后通过的 acceptance 数量没有变化；
- active change 长期没有 next action 或阻塞说明。

Drift 只报告证据和建议，不应基于弱信号自动回滚代码。

## 13. CLI 与 MCP 演进

建议保留现有命令并增加：

```text
linc-codebuddy project init
linc-codebuddy classify
linc-codebuddy change create/show/update
linc-codebuddy gate [target-phase]
linc-codebuddy next
linc-codebuddy task activate/done/block
linc-codebuddy verify
linc-codebuddy drift
linc-codebuddy release
linc-codebuddy workspace status
```

对应 MCP 工具先保持少而稳定：

```text
lcb_project_init
lcb_classify
lcb_change
lcb_gate
lcb_next
lcb_task
lcb_verify
lcb_drift
lcb_release
lcb_workspace_status
```

不要让每个底层 CRUD 都成为独立 MCP tool；CLI 可以细，MCP 应按 Agent 使用场景聚合。

## 14. 兼容与迁移

### GitLab 引用同步

V2.4 使用 GitLab 快照作为适配边界。同步计划先比较对象绑定和规范化快照指纹：无变化返回 noop，绑定 ID 改变返回 conflict，只有 conflict-free planned 状态可以写入本地 change。快照按字段白名单持久化，不保存凭据、描述正文、评论和用户资料。`--apply` 的含义仅是应用本地引用；所有真实 GitLab 写操作仍需显式批准和独立 executor。

- 现有 V1 `state.json` 必须可读；
- `TASKS.md` 和 worklogs 暂时继续支持；
- V2 首先建立适配层，不立即删除旧路径；
- 旧 work item 没有 ID 时生成迁移 ID并保留原路径引用；
- `ship` 默认改为必须指定 task/change；
- 老调用若未指定 ID，只生成计划并提示选择，不自动关闭任务；
- 所有迁移支持 dry-run 和备份；
- MCP schema 变化应保留旧工具一段兼容周期。

## 15. 测试策略

最低测试集：

- state V1 -> V2 migration；
- 原子写入和损坏状态恢复；
- ID 唯一性；
- 合法与非法 phase transition；
- L0-L3 分类硬规则；
- gate 缺失项与 override；
- task 依赖、唯一 active task、精确 done；
- ship 只关闭指定 task；
- next 在 blocking、gate、active、ready、verify 失败等状态下的决策；
- verification evidence 与需求关联；
- 旧 CLI/MCP 调用兼容；
- dirty worktree 和未知用户改动保护。

建议使用临时 Git 仓库做集成测试，禁止测试修改真实项目。

## 16. 安全边界

- 不将 token、密码、证书、生产变量写入状态和 evidence；
- shell command 使用参数数组，避免未经验证的字符串进入 `bash -c`；
- destructive、production、external-write 动作单独标记并要求批准；
- Git remote 和 push 目标必须在执行前核验；
- 不以 `--force` 作为通用逃生门；
- state、policy 和 change 文件都应允许仓库级保护和审查。

## 17. 真实试点评估

V2 完成后使用 `pilot record/evaluate` 记录恢复次数、人工上下文重建时间、误门禁、产物时间、长任务恢复失败、并行阻塞和定时巡检需求。V3 不是默认下一阶段；只有重复观测到 durable orchestration、并行隔离或无人值守运行的实际瓶颈时，才进入 scoped experiment。
