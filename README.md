# Linc CodeBuddy

面向个人开发者的自适应工程治理 Agent。在编码之前收敛需求，在交付时用证据证明完成，跨会话也能可靠恢复上下文。

## 它解决什么问题

- 新项目或模糊需求下大模型容易直接冲进编码，偏离主线
- 需求、设计、任务、验收之间缺少可追溯关系，跑着跑着不知道做到哪了
- 技术测试通过了但无法证明实现了原始需求
- 简单修改和复杂改造用同一套重量级流程，要么过度要么不够

CodeBuddy 把这些场景用一套生命周期 + 自适应治理等级来管理，而不是靠大模型临场判断。

## 安装

```bash
bash install.sh
```

安装后自动完成：
- Skill 链接到 `~/.codex/skills/linc_codebuddy`
- MCP Server 注册到 `~/.codex/config.toml`
- CLI 命令 `linc-codebuddy` 安装到 `~/.local/bin`

重启 Codex Desktop 或新建任务后生效。

如果使用 cc-switch 等工具管理 Codex 配置，请在该工具中同时启用 CodeBuddy Skill 和 MCP Server，避免切换模型时覆盖 `~/.codex/config.toml` 中的 MCP 注册。

## 三种使用方式

### 1. Skill（对话模式）

在 Codex 中直接使用，CodeBuddy 作为 Skill 自动接管项目管理。

### 2. CLI（命令行）

```bash
linc-codebuddy intake                      # 仓库侦测 + 状态恢复
linc-codebuddy kickoff "实现用户分组"       # 创建变更并确定治理等级
linc-codebuddy next                        # 查看当前唯一焦点和下一步
linc-codebuddy gate verify                 # 检查阶段门禁
linc-codebuddy state                       # 查看完整状态
linc-codebuddy doc-config --show           # 查看文档配置
linc-codebuddy generate-docs --type all    # 手动生成文档
```

### 3. MCP Server（程序化）

通过 `lcb_*` 工具调用，共 19 个工具：

| 类别 | 工具 |
|---|---|
| 项目管理 | `lcb_intake`, `lcb_project_init`, `lcb_kickoff`, `lcb_state`, `lcb_next` |
| 变更与阶段 | `lcb_change`, `lcb_gate`, `lcb_verify`, `lcb_drift` |
| 分类与治理 | `lcb_classify`, `lcb_pilot` |
| 证据与交付 | `lcb_evidence`, `lcb_ship`, `lcb_gitlab_sync` |
| 自动化 | `lcb_auto`, `lcb_patrol` |
| 文档管理 | `lcb_doc_config`, `lcb_generate_docs` |
| 工作区 | `lcb_workspace_status` |

## 核心能力

### 生命周期管理

```
explore -> specify -> design -> plan -> implement
        -> verify -> release -> operate -> learn
```

每个阶段转换都经过 gate 检查，确保必要产物（需求、验收、实现、证据）到位才放行。

### 自适应治理等级

| 等级 | 场景 | 流程 |
|---|---|---|
| L0 快修 | 文案、配置、可逆小错误 | 定位、修改、最小验证 |
| L1 标准 | 明确功能、普通 Bug | change + 实现 + 测试 |
| L2 设计 | 跨模块、API、认证 | 需求 + 验收 + 设计 + 完整验证 |
| L3 项目 | 新项目、模糊问题 | 探索 + 架构 + 分阶段交付 |

简单任务走最短路径，复杂变更自动加厚流程。不做一刀切。

### 文档管理

接管项目时提醒配置两个参数：
- **local_path** — 文档在项目内的存储目录（默认 `docs/changes`）
- **remote_target** — 远程同步目标（`gitlab:<repo>`、`dingtalk:<space_id>`、或留空）

阶段转换时自动生成三类 Markdown 文档：

| 转换目标 | 生成文件 | 来源 |
|---|---|---|
| design / plan / implement | `requirements.md` | change.yaml |
| verify | `test-report.md` | evidence + verification |
| release / operate | `release-note.md` | change + verification + transitions |

不配置则跳过，不阻塞流程。

### 前端设计协作

前端任务采用职责分离的协作链路：

```text
CodeBuddy intake/classify -> bzdesignprompt -> DESIGN.md
  -> frontend-design -> Playwright 验证 -> CodeBuddy 交付
```

- 新页面、新模块、控制台、门户或视觉重做：先检查 `DESIGN.md`，缺失时使用 `bzdesignprompt` 选择模板。
- 已有 `DESIGN.md`：直接作为 `frontend-design` 的实现约束，不重复覆盖。
- 文案、颜色、间距或单组件修复：保持轻量，不强制引入设计模板。
- CodeBuddy 继续负责需求、验收、验证证据和交付记录。

### 架构图协作

需要架构图、流程图、时序图、数据流图或状态生命周期图时，CodeBuddy 优先与 `archify` 协作：

```text
CodeBuddy -> 读取仓库证据 -> Archify typed JSON
  -> showcase validate -> 独立 HTML -> visual-check -> CodeBuddy evidence
```

Archify 负责确定性渲染和布局校验；CodeBuddy 负责判断图类型、收集真实仓库证据、保存 JSON/HTML 产物，并把验证回执纳入交付记录。

### 证据与验收追踪

每条验证证据关联到具体的验收条件 ID，需求变更后自动标记旧证据为 stale，防止"测试通过但跟需求无关"的情况。

## 项目结构

```
linc_codebuddy/
  SKILL.md                  # Skill 元数据 + 完整行为指令
  install.sh                # 一键安装
  agents/openai.yaml        # Codex UI 元数据
  scripts/
    run_agent.py            # CLI 统一入口
    mcp_server.py           # MCP Server（19 个 lcb_* 工具）
    lifecycle.py            # 生命周期 + 阶段门禁
    governance.py           # L0-L3 自适应分级
    quality.py              # 证据 + 验证 + 漂移检测
    doc_sync.py             # 文档生成 + 远程同步
    gitlab_sync.py          # GitLab 参考快照
    pilot.py                # V3 触发评估
    ...                     # 其他辅助脚本
  tests/
    test_v2_foundation.py   # 41 个核心测试
    test_doc_sync.py        # 16 个文档管理测试
  docs/codebuddy-2/         # 2.0 改造设计文档
  references/               # Skill 参考资料库
```

## 验证

```bash
python3 -B scripts/quick_validate.py        # 快速校验
python3 -B -m unittest discover -s tests -v # 完整测试
```

## 技术约束

- 不依赖 AutoGPT / MetaGPT / CrewAI / LangGraph / Letta 运行时
- 吸收上述项目的治理思想，但用纯 Python + Git 仓库状态实现
- 简单需求保持轻量，不做冗余流程
- 所有人工决策和审批留痕，不静默绕过

## License

当前仓库尚未附加开源许可证。未经作者明确许可，不授予复制、修改或再分发权利。
