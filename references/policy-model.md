# Policy Model

`linc_codebuddy` 现在有结构化 policy，用来把“文档里写的偏好”变成“脚本能读懂的规则”。

## 默认 policy

默认 policy 文件在：

`assets/default-policy.json`

它定义了：

- 默认语言与模式
- branch 前缀
- ship 行为
- patrol 是否只读
- 验证顺序
- 哪些路由默认创建 work item
- patrol presets（晨检 / 收工检查 / 预发版巡检 / 续做接力）

## 仓库级 override

每个 repo 可以有自己的 override 文件：

`<repo>/.codex/linc_codebuddy/policy.json`

规则：

- 没有 override 时，只使用默认 policy
- 有 override 时，按 key 深合并
- 字典会合并
- 标量和数组会被 override 覆盖

## 常见可改项

推荐优先改这些：

- `branch_prefix`
- `default_mode`
- `default_ship_behavior`
- `allow_code_changes_on_patrol`
- `work_item.create_on_routes`
- `route_defaults`
- `patrol_presets`

## 典型 override 示例

```json
{
  "branch_prefix": "dev",
  "route_defaults": {
    "hotfix": {
      "mode": "normal"
    }
  },
  "patrol_presets": {
    "pre-ship": {
      "focus": [
        "run stricter validation",
        "require ship summary"
      ]
    }
  }
}
```

## 什么时候用 policy 而不是 references

- **policy**：给脚本读的、稳定的、结构化规则
- **references**：给 agent 读的、解释性的、策略性的说明

简单说：

- 机器要执行的默认规则放 policy
- 人类偏好和解释放 references
