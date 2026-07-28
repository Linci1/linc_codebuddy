# Automation Playbook

这份说明用于把 `linc_codebuddy` 从“被动响应”推进到“可自动触发 / 可巡检”的 harness-native agent。

## 适合自动触发的场景

- **晨检**：每天固定时间扫描一个或多个仓库，汇总 branch、dirty 状态、Active 任务和建议下一步
- **收工检查**：下班前确认是否还有未同步的任务、未提交的改动、缺少的验证
- **预发版巡检**：对准备提交或准备 push 的仓库做一次 `ship` 导向检查
- **连续开发提醒**：对仍有 Active 任务但长时间无推进的仓库给出提醒

## 巡检模式的默认动作

自动触发时，不要直接进实现，先做这三步：

1. `python3 scripts/run_agent.py --json patrol --preset morning`
2. `python3 scripts/run_agent.py --json state`
3. 根据输出决定推荐路由：
   - 有 dirty 改动且有 Active 任务：`continue`
   - 有 dirty 改动但无 Active 任务：`ship`
   - 无 dirty 改动但有 Active 任务：`continue`
   - 用户明确要只看风险：`review`
   - 都没有：`idle`

## 建议的 automation prompt 写法

automation prompt 只描述任务本身，不写调度信息。推荐写法：

### 晨检

“使用 [$linc_codebuddy](/Users/ciondlin/agents/linc_codebuddy/SKILL.md) 对当前工作区做一次晨检：优先用统一入口做 `run_agent patrol --preset morning`，总结仓库状态、Active 任务、推荐路由和今天最值得推进的一步；默认不改代码，除非我在任务里明确要求继续实现。”

### 收工检查

“使用 [$linc_codebuddy](/Users/ciondlin/agents/linc_codebuddy/SKILL.md) 做收工检查：优先用统一入口做 `run_agent patrol --preset end-of-day`，查看 dirty 改动、未同步任务、建议验证项和是否适合进入 ship；默认不改代码，只输出结论和下一步建议。”

### 预发版巡检

“使用 [$linc_codebuddy](/Users/ciondlin/agents/linc_codebuddy/SKILL.md) 做预发版巡检：优先用统一入口做 `run_agent patrol --preset pre-ship` 或 `run_agent ship`，检查变更边界、建议验证、branch 和 commit 方案；默认不 push。”

## 状态文件

默认状态文件路径：

`<repo>/.codex/linc_codebuddy/state.json`

建议记录：

- 最近一次路由
- 最近一次模式
- 最近 work item
- 最近 patrol 时间
- 最近 patrol 推荐
- 最近备注

## 什么时候不要自动改代码

以下情况下，automation 只做巡检，不做实现：

- 仓库存在大量脏改动
- 本轮没有明确 work item
- 用户只是想看状态或提醒
- 当前任务应该先 review 再决定怎么改
