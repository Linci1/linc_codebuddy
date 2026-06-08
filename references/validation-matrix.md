# 验证矩阵

先跑最小可信验证，再决定是否扩大范围。优先级始终是：

1. 仓库原生命令
2. 与改动最相关的 lint / test
3. 只在必要时跑 build 或更慢的全量检查

## 通用优先级

- 如果有 `scripts/dev checklist`，优先它
- 如果有 `Makefile` / `justfile` 中的标准检查命令，优先它
- 只改文案、注释、纯展示文案时，可降级为最小静态检查
- 改公共接口、配置、构建链路或数据迁移时，要补 build 或集成检查

## JavaScript / TypeScript

识别信号：

- `package.json`
- `pnpm-lock.yaml` / `yarn.lock` / `package-lock.json`

推荐顺序：

1. `lint`
2. 受影响模块的测试
3. `build`

命令选择：

- pnpm: `pnpm lint`, `pnpm test`, `pnpm build`
- yarn: `yarn lint`, `yarn test`, `yarn build`
- npm: `npm run lint`, `npm test`, `npm run build`

适用场景：

- UI 组件、样式、小逻辑变更：通常 `lint` + 相关测试
- 路由、打包、环境变量、类型边界变更：补 `build`

## Python

识别信号：

- `pyproject.toml`
- `requirements.txt`
- `pytest.ini`

推荐顺序：

1. `ruff check` 或等价 lint
2. `pytest -q`
3. `mypy` 或项目中的类型检查

适用场景：

- 只改纯函数或业务逻辑：至少跑相关测试
- 改接口契约、Pydantic 模型、依赖注入：补类型检查

## Go

识别信号：

- `go.mod`

推荐顺序：

1. `go test ./...`
2. `go vet ./...`（如果仓库原本就在用）

适用场景：

- 并发、I/O、接口行为变化时，不跳过测试

## Rust

识别信号：

- `Cargo.toml`

推荐顺序：

1. `cargo test`
2. `cargo clippy -- -D warnings`（如果仓库已有这类约定）

## Docker / Infra

识别信号：

- `Dockerfile`
- `docker-compose.yml`
- `compose.yaml`

推荐顺序：

1. `docker compose config`
2. 仓库已有的镜像或容器检查脚本

## 结果表达

- 跑过：明确写命令和结果
- 没跑：明确写未运行原因
- 失败：写失败点、影响范围和建议下一步
