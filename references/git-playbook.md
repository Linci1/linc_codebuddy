# Git Playbook

用于 `ship` 路由，或当用户明确要整理 branch / commit 时读取。

## 分支命名

默认前缀：`codex/`

推荐格式：

- `codex/new-<slug>`
- `codex/continue-<slug>`
- `codex/review-<slug>`
- `codex/hotfix-<slug>`
- `codex/ship-<slug>`

原则：

- 名字短、可读、可搜索
- 优先体现任务意图，不必把所有细节塞进分支名
- 没有明确要求时，不擅自切分支；先给建议即可

## Commit 类型

优先使用：

- `feat:` 新能力
- `fix:` 缺陷修复
- `refactor:` 结构调整但不改行为
- `docs:` 文档说明
- `test:` 测试补充
- `chore:` 工具、配置、流程性整理

## Commit 主题

要求：

- 说明业务价值，不只写技术动作
- 主题尽量短
- 一次 commit 尽量只表达一个逻辑闭环

示例：

- `feat: add repo intake route detection`
- `fix: handle non-git repos in task sync`
- `docs: document review and ship routes`
- `chore: add branch and commit helper scripts`

## 使用 helper 的建议

- 分支建议：`python3 scripts/prepare_branch.py "任务标题"`
- commit 建议：`python3 scripts/draft_commit.py --title "任务标题"`

如果用户明确要实际创建分支，再用 `--create`。
