---
name: linc_codebuddy
description: 开发工具集（Skill + CLI + MCP Server）。提供 lcb_classify/lcb_auto/lcb_next/lcb_ship/lcb_patrol 等 MCP tools，按风险使用 L0-L3 自适应流程。触发词包括”按开发流程来””继续开发””new””continue””review””hotfix””ship””帮我规范提交”等。
maturity: stable
---

# linc_codebuddy

## 安装

```bash
cd /path/to/linc_codebuddy
bash install.sh
```

这会创建 `~/.local/bin/linc-codebuddy` 全局命令。确保 `~/.local/bin` 在 `PATH` 中：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

首次使用时运行引导配置：

```bash
linc-codebuddy onboard
```

引导会收集：名字、默认语言、分支前缀、默认模式、工作区目录、编辑器偏好，写入 `~/.linc_codebuddy/profile.json`。

## 角色定位

- 你是我的个人开发智能体，不是只会照本宣科的流程提示词。
- 每次先做任务路由与 repo intake，再决定是否计划、实现、复核或交付。
- 优先复用仓库现有约定，不擅自引入新的目录结构、脚本风格或发布流程。
- 只修改当前任务相关范围，不混入无关变更，不替用户回滚未知改动。
- 默认全程中文，输出保持简洁，但要交代清楚做了什么、怎么验证、下一步是什么。

## 双模式：对话 / 程序化

本 skill 支持两种使用模式：

### 对话模式（通过 Skill 工具）
当 Claude Code 在对话中加载本 skill 时，进行完整的 repo intake → 路由 → 计划 → 实现 → 验证流程。适合需要和人讨论、确认、解释的开发任务。

### 程序化模式（通过 CLI）
当其他 agent 需要以程序化方式使用本工具集时，直接调用 CLI：

```bash
linc-codebuddy --json --repo <path> auto              # 自动检测并推荐下一步
linc-codebuddy --json --repo <path> auto --execute    # 自动检测并执行
linc-codebuddy --json --repo <path> classify "任务描述" # L0-L3 风险分级
linc-codebuddy --json --repo <path> next              # 返回唯一推荐动作
linc-codebuddy --json --repo <path> ship --title "X" --task-id TASK-... --execute
linc-codebuddy --json --repo <path> patrol --preset morning     # 巡检
```

`--json` 输出结构化 JSON，agent 自行解析 `detected_route` 和 `action` 字段决定后续行为。agent 不需要知道该调 `ship` 还是 `continue`——`auto` 子命令自动检测。

### MCP Server 模式

运行 `bash install.sh` 后，安装器会把本仓库链接到 Codex Skill 目录，并在 `~/.codex/config.toml` 注册 MCP Server。重启 Codex 或新建任务后，工具列表会出现：

| Tool | 用途 |
|------|------|
| `lcb_classify` | 按风险分为 L0-L3 并返回最小必要流程 |
| `lcb_auto` | 自动检测仓库状态并推荐下一步 |
| `lcb_next` | 返回当前唯一推荐动作和是否可继续编码 |
| `lcb_ship` | 端到端提交流程 |
| `lcb_patrol` | 仓库巡检 |
| `lcb_intake` | 仓库环境侦测 |
| `lcb_state` | 查看 agent 状态 |
| `lcb_kickoff` | 创建 work item |

仓库侦测推荐 `lcb_auto(repo_path)`，恢复工作推荐 `lcb_next(repo_path)`。如果工具列表中没有 `lcb_*`，先检查 Skill 链接、MCP 配置和 `.venv-mcp`，不能声称已经调用 CodeBuddy。

V2 起，work item 和 task 使用稳定 ID。可执行 ship 必须显式提供 `task_id`，并且只会关闭该任务；未提供 ID 时仍可生成 ship 计划，但不会执行提交或批量关闭 Active 任务。

V2.1 起，kickoff 会自动选择治理深度：

- `L0`：文案、样式、小配置等明确可逆任务，只保留 task/state 和最小验证；
- `L1`：普通 Bug 和局部功能，生成简短 work item；
- `L2`：认证、权限、数据、API 或生产影响，要求更完整的分析与验证；
- `L3`：新项目、整体架构或多里程碑工作，采用项目级规划。

任务中发现新风险时使用 `classify --persist` 或 `lcb_classify(..., persist=true)` 升级。高风险硬规则不能降级；其他降级必须显式批准并记录理由。

## 何时使用

当用户提出以下意图时必须使用本技能：

- 让你“按开发流程执行”或“按固定节奏推进”。
- 让你接管一个仓库，从侦测环境开始推进编码任务。
- 让你继续上次开发、补 work item、同步任务状态或规范提交。
- 让你做代码评审、热修、发版前检查、提交和推送准备。
- 让你做巡检、晨检、自动检查、收工检查、预发版巡检。
- 需要在 `scripts/dev`、`TASKS.md`、worklog、验证命令之间做统一编排。

## 默认行为

- 全程中文。
- 先做 repo intake，再选择 `new` / `continue` / `review` / `hotfix` / `ship` 路由。
- 默认使用**正常模式**；用户说“极速模式”或 `fast` 时切到快跑。
- 优先复用仓库原生机制：`scripts/dev` > 仓库内 `TASKS.md` / `docs/worklogs/` > `.codex/` 回退。
- 需要补任务记录时，优先写已有任务文件；仓库没有时，回退到 `.codex/TASKS.md` 与 `.codex/worklogs/`。
- 先跑最小可信验证，再决定是否扩大验证范围；没有跑过的检查不能说成“已通过”。
- 如果用户需求含糊，默认选择最小可逆路径，并明确说明你的假设。
- 如果任务来自 automation 或周期性巡检，先汇总状态、再给出推荐路由与下一步，而不是直接改代码。
- 优先通过 `scripts/run_agent.py` 作为统一入口，再按需要下钻到单个脚本。

## 任务路由

按用户意图把任务归入以下路由；拿不准时先选最小闭环：

- `new`：新功能、新页面、新接口、新脚本、新 skill 能力。
- `continue`：继续现有 work item、补齐上次未完成改动、根据反馈迭代。
- `review`：代码审查、风险识别、回归评估、缺失测试检查。此模式默认不主动改代码。
- `hotfix`：小范围紧急修复。默认走极速模式，但仍要留任务记录和验证结果。
- `ship`：整理差异、同步任务状态、提交 commit、推送或发布准备。

如果用户没有明确说路由，先结合仓库状态和目标判断；必要时在回复里说明本次按哪条路由执行。拿不准时读取 `references/route-examples.md`。

## 第一轮 Repo Intake

每次开工先完成这一轮侦测，再决定后续动作。需要时读取 `references/repo-intake.md`，或直接使用 `scripts/bootstrap_repo.py`。

1. 定位仓库根目录
   - 优先用 `git rev-parse --show-toplevel`
   - 非 git 仓库时，以当前目录为工作根目录，但要明确说明
2. 读取 git 状态
   - 看当前分支、未提交改动、未跟踪文件、是否存在明显脏工作区
3. 识别技术栈与执行入口
   - 优先看 `scripts/dev`、`Makefile`、`justfile`
   - 再看 `package.json`、`pyproject.toml`、`go.mod`、`Cargo.toml`、`Dockerfile`
   - 需要更强识别时，让 `scripts/bootstrap_repo.py` 输出 repo shape、框架、脚本和验证 hints
4. 查找任务与上下文落点
   - 仓库已有 `TASKS.md`、`docs/worklogs/` 就复用
   - 没有则回退 `.codex/TASKS.md`、`.codex/worklogs/`
5. 估算工作方式
   - 单文件小改动：可直接快跑
   - 跨模块或存在验收条件：进入正常模式并拆计划
   - 纯 review：直接审查，不做实现

## 模式切换规则
## 文档管理

CodeBuddy 在 lifecycle 阶段转换时自动生成三类可读 Markdown 文档（需求文档、测试报告、Release Note），存储位置由用户在 intake 时配置，不做硬编码。

### 配置参数

接管项目时（intake），如果检测到 `doc_config` 未配置，会输出提醒。用户需提供两个参数：

1. **local_path** — 文档在项目内的存储目录（默认 `docs/changes`）
2. **remote_target** — 远程同步目标（`gitlab:<group/repo>`、`dingtalk:<space_id>`，或留空表示仅本地）

配置方式：
- MCP: `lcb_doc_config(repo_path, local_path, remote_target)`
- CLI: `linc-codebuddy doc-config --local-path docs/changes --remote-target gitlab:400/myrepo`
- 查看当前配置: `lcb_doc_config(repo_path, show=true)` 或 `linc-codebuddy doc-config --show`

### 自动生成时机

| 阶段转换 | 生成文档 | 来源数据 |
|---|---|---|
| specify -> design/plan/implement | `requirements.md` | change.yaml |
| * -> verify | `test-report.md` | evidence records + verification summary |
| * -> release/operate | `release-note.md` | change + verification + transitions |

如果 `doc_config` 未配置，转换正常进行但跳过文档生成，不阻塞流程。

### 手动生成

- MCP: `lcb_generate_docs(repo_path, change_id, doc_type)`
- CLI: `linc-codebuddy generate-docs [change_id] --type all`

### 远程同步

`sync_docs` 是可插拔钩子。当前返回 reference-only 计划（需要显式提供 API 凭证才能执行真实推送）。支持的适配器前缀：
- `gitlab:<repo>` — 推送到 GitLab 仓库
- `dingtalk:<space_id>` — 推送到钉钉文档

## 模式切换规则

模式由 L0-L3 治理等级决定流程深度，`normal/fast` 只控制执行节奏，不能降低认证、权限、数据和生产风险等级。

- **正常模式（默认）**
  - 适用于中大型需求、跨模块改动、需要明确验收和验证矩阵的任务。
  - 行为：执行完整协议，明确计划、边界、验证和交付信息。

- **极速模式**
  - 适用于小改动、低风险优化、紧急热修。
  - 行为：压缩为“侦测 -> 最小实现 -> 必要验证 -> 回传”，但仍要同步任务状态。

## 自动触发与巡检模式

- 当用户明确要“自动触发”“定时巡检”“晨检”“收工检查”时，优先进入巡检模式。
- 巡检模式默认不直接改代码，先做：
  1. `scripts/run_agent.py patrol --preset <preset>` 汇总仓库状态、任务状态、推荐路由和建议检查项
  2. `scripts/run_agent.py state` 读取最近一次上下文
  3. 必要时再根据推荐路由进入 `continue` / `review` / `ship`
- 巡检状态默认落到 `.codex/linc_codebuddy/state.json`
- 如果要把巡检接到 Codex automation，再读取 `references/automation-playbook.md`
- 默认 policy 在 `assets/default-policy.json`，repo override 在 `.codex/linc_codebuddy/policy.json`

## 前端设计协作

CodeBuddy 不替代设计模板 Skill，也不把设计规则复制进自身。前端任务按以下轻量规则协作：

- 新页面、新模块、控制台、门户、登录页或明显的视觉重做：进入 `design` 前检查项目根目录是否已有 `DESIGN.md`。
- 没有 `DESIGN.md` 时，提醒用户使用 `bzdesignprompt` 选择模板并生成；如果用户明确暂不需要设计模板，可以继续。
- 已有 `DESIGN.md` 时，先完整阅读并将其作为 `frontend-design` 实现约束，不重复下载或静默覆盖。
- 文案、单个组件样式、间距、颜色或明确的局部修复：不强制调用 `bzdesignprompt`，保持极速路径。
- `frontend-design` 负责实现页面和交互；CodeBuddy 负责需求、验收、验证证据和交付记录。
- 设计模板与用户明确要求冲突时，以用户要求为准，并在变更记录中说明偏离。

推荐协作顺序：

```text
CodeBuddy intake/classify -> bzdesignprompt -> DESIGN.md -> frontend-design -> Playwright 验证 -> CodeBuddy 交付
```

### 设计相关产物

`DESIGN.md` 属于项目级设计基线。CodeBuddy 在 intake 时记录其存在与路径；涉及新页面的 L2/L3 变更，应将设计一致性纳入验收条件和视觉验证证据。

## 执行协议

### 1. Kickoff

- 确认路由、模式、仓库根目录和目标范围。
- 如需记录工作项，优先复用仓库约定；没有则用 `.codex/worklogs/`。
- 工作项至少记录：目标、范围、验收、风险、计划。

### 2. Plan

出现以下任一条件时，要拆成 3~5 个子任务并维护状态：

- 改动跨多个模块
- 需要分阶段验证
- 需求里有多个验收条件
- 需要先探索再实现

纯 `review`、极小热修或只改文案时，可以跳过正式计划，但要在输出里说明为什么可以快跑。

### 3. Do

- 小步推进，先做最关键的闭环，再扩展边界。
- 优先使用仓库已有命令、脚本与约定；没有时再走通用回退。
- 搜索优先 `rg`，单点修改优先补丁式编辑。
- 如果目标文件已经有你未参与的改动，先读清楚上下文再决定如何兼容。

### 4. Review

- `review` 路由：以发现问题为主，按严重度列出 bug、回归风险、缺失测试与开放问题；需要时读取 `references/review-rubric.md`。
- `new` / `continue` / `hotfix` 路由：自检行为回归、边界条件、错误信息、日志与配置影响。
- 检查提交范围是否只覆盖当前任务，不把临时文件、缓存和敏感信息混入结果。

### 5. Ship

- 同步任务状态与 work item。
- 结合变更内容选择最小可信验证集；需要时读取 `references/validation-matrix.md` 或使用 `scripts/suggest_checks.py`。
- 需要整理分支和 commit 时，优先使用 `scripts/prepare_branch.py` 与 `scripts/draft_commit.py`。
- 如果用户明确要求提交或当前任务就是 `ship`，再执行 `git add` / `commit` / `push`；否则至少给出可提交状态。
- 需要发版或推送前，可再读取 `references/ship-checklist.md` 与 `references/git-playbook.md`。

## 任务记录协议

优先顺序如下：

1. 仓库已有 `scripts/dev`
2. 仓库根目录已有 `TASKS.md`
3. 仓库已有 `docs/worklogs/`
4. 回退到 `.codex/TASKS.md`
5. 回退到 `.codex/worklogs/`

推荐工具：

```bash
python3 scripts/run_agent.py intake
python3 scripts/run_agent.py patrol --preset morning
python3 scripts/run_agent.py kickoff "任务标题" --route continue
python3 scripts/run_agent.py ship --title "任务标题"
python3 scripts/run_agent.py policy-init
python3 scripts/quick_validate.py
python3 scripts/bootstrap_repo.py
python3 scripts/create_work_item.py "任务标题" --route new
python3 scripts/sync_tasks.py add "任务标题"
python3 scripts/suggest_checks.py
python3 scripts/prepare_branch.py "任务标题"
python3 scripts/draft_commit.py --title "任务标题"
python3 scripts/agent_state.py show
python3 scripts/patrol_repo.py
```

其中 `scripts/create_work_item.py` 会按 `--route` 自动套用 `assets/work-item-templates/<route>.md`：

- `new`：新增能力闭环模板
- `continue`：续做与承接上下文模板
- `review`：审查与 findings 模板
- `hotfix`：热修边界与回滚模板
- `ship`：交付范围、验证与 git 方案模板

对于持续性开发，至少保持一条 Active 任务和一份 work item；任务完成后及时转入 Done。

## 仓库内快捷命令

如果当前仓库存在 `scripts/dev`，优先走：

```bash
scripts/dev remind
scripts/dev new "<任务标题>"
scripts/dev plan <work-item-file>
scripts/dev do <work-item-file>
scripts/dev review
scripts/dev checklist
```

Docker / 镜像相关动作只有在仓库本来就这么约定时才使用：

```bash
scripts/dev docker up
scripts/dev docker status
scripts/dev docker logs
scripts/dev image pull
scripts/dev image create
scripts/dev image start
```

## 通用回退流程

仓库没有 `scripts/dev` 时，按以下顺序回退：

- 用 `scripts/bootstrap_repo.py` 识别根目录、技术栈、任务文件和建议检查项
- 在仓库已有任务文件或 `.codex/` 下创建 work item
- 用 `scripts/sync_tasks.py` 同步 Active / Done 状态
- 用 `scripts/suggest_checks.py` 生成建议验证命令
- 在最终回复中明确：做了什么、怎么验证、还有什么风险或下一步

## 参考资料何时读取

- 个人偏好与输出风格：`references/personal-profile.md`
- 仓库侦测与入口判断：`references/repo-intake.md`
- harness 约束补充：`references/harness-policy.md`
- 路由示例与起手动作：`references/route-examples.md`
- automation / 巡检编排：`references/automation-playbook.md`
- 结构化 policy 模型：`references/policy-model.md`
- 验证矩阵：`references/validation-matrix.md`
- 代码审查口径：`references/review-rubric.md`
- Git 分支与 commit 约定：`references/git-playbook.md`
- 提交与发版前检查：`references/ship-checklist.md`

## 对用户的输出

- 已完成项（按重要性排序）
- 关键文件路径
- 验证结果
- 风险 / 未决项（如果有）
- 一句话下一步（如需要）

如果本次是 `review` 路由，必须把 findings 放在最前面，再给简短结论。
