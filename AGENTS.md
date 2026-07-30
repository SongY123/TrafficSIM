# TrafficVerse Engineering Standards

> 版本：v1.3
>
> 状态：Accepted
>
> 适用范围：本仓库全部源代码、测试、配置、脚本、迁移和文档
>
> 相关文档：[PRD](docs/PRD.md)、[System Design](docs/SYSTEM_DESIGN.md)、
> [Agent Guide](docs/AGENT_DEVELOPMENT_GUIDE.md)、[ADR](docs/ADR.md)

## 1. 规范优先级

1. 产品范围以 `docs/PRD.md` 为准；
2. 已接受决策以 `docs/ADR.md` 为准；
3. 模块、协议和运行时以 `docs/SYSTEM_DESIGN.md` 为准；
4. 代码和目录规则以本文为准；
5. 任务边界和验收以 `docs/AGENT_DEVELOPMENT_GUIDE.md` 为准。

文档实质冲突时停止扩散实现，先更新设计或 ADR。不得用局部代码绕过冲突。

## 2. 不可破坏的系统约束

1. SUMO/TraCI 是车辆、路线、车道、运动学和信号灯的唯一真值源；
2. SUMO GUI 不属于产品 UI；
3. 只有 `SimulationManager` 可以调用 TraCI `simulationStep()`；
4. Core Run 使用 50 ms 固定步长和 Town04 同源 SUMO 资产；
5. UI 只消费标准快照，不自行推演权威车辆位置；
6. 跨模块只使用公共领域模型、事件和 Port，不共享第三方 SDK 对象；
7. 配置来自类型化 YAML，不硬编码领域或部署参数；
8. 实时状态与异步结果使用版本化 WebSocket envelope，资源 CRUD 使用 REST；
9. 高频轨迹使用 Parquet，关系元数据使用 PostgreSQL；
10. CARLA、ROI、RGB 图像和 native-window 已移除，禁止恢复兼容别名、配置或测试 marker。

修改上述约束必须先新增或替代 ADR。

## 3. 目录与模块边界

```text
TrafficSIM/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── configs/
│   ├── runtime-baseline.yaml
│   ├── defaults.yaml
│   ├── scenarios/
│   └── maps/town04/
├── contracts/
│   ├── openapi.yaml
│   └── websocket/
├── src/trafficverse/
│   ├── cli.py
│   ├── bootstrap.py
│   ├── config/
│   ├── domain/
│   ├── ports/
│   ├── application/
│   ├── maps/
│   ├── traffic/
│   ├── adapters/
│   │   ├── sumo/
│   │   ├── persistence/
│   │   └── messaging/
│   ├── controllers/
│   ├── api/
│   └── logging/
├── ui/
│   ├── app/
│   ├── api_client/
│   ├── models/
│   ├── views/
│   ├── viewmodels/
│   ├── widgets/
│   ├── web/map/
│   └── assets/
├── migrations/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   ├── performance/
│   └── fixtures/
├── scripts/
├── artifacts/
└── docs/
```

文件放置：

| 内容 | 位置 |
|---|---|
| 领域模型、枚举、错误、事件 | `src/trafficverse/domain/` |
| 第三方抽象接口 | `src/trafficverse/ports/` |
| 用例编排、生命周期 | `src/trafficverse/application/` |
| 依赖注入 | `src/trafficverse/bootstrap.py` |
| SUMO/TraCI 实现 | `src/trafficverse/adapters/sumo/` |
| OpenDRIVE 和地图编译 | `src/trafficverse/maps/` |
| 车辆控制策略 | `src/trafficverse/controllers/` |
| HTTP/WebSocket | `src/trafficverse/api/` |
| PySide6、MapLibre、deck.gl | `ui/` |
| 公共机器契约 | `contracts/` |
| 用户配置 | `configs/` |
| 数据库迁移 | `migrations/` |
| 运行产物 | `artifacts/`，不得提交 |

依赖方向：

```text
ui -> REST/WebSocket contracts
api -> application -> ports -> domain
adapters -> ports + domain
maps -> domain
traffic/controllers -> ports + domain
bootstrap/cli -> application + concrete adapters
```

- `domain` 只导入标准库和 Pydantic；
- `ports` 只导入标准库、typing 和 domain；
- `application` 不导入具体 adapter SDK；
- adapter 之间不得直接导入；
- `api` 不直接导入 TraCI 或 SQLAlchemy model；
- `ui` 不导入 `src/trafficverse`；
- `controllers` 不持有 TraCI connection；
- `__init__.py` 不启动线程、连接资源、读取文件或执行注册副作用；
- 禁止循环导入，不使用函数内 import 掩盖职责错误。

## 4. 并行开发与共享热点

默认功能分工：

| 负责人 | 产品功能 | 默认可修改范围 |
|---|---|---|
| 吴思睿 | 工作台、资产中心、地图/车辆智能体资产管理、相关弹窗 | `ui/views/asset_center_page.py`、工作台/资产中心 feature-local 页面与 viewmodel、`ui/widgets/asset_directory.py`、`ui/models/assets.py`、`src/trafficverse/maps/`、`src/trafficverse/api/map_catalog.py` 及对应测试 |
| 赵彦豪 | 项目详情、场景配置、交通需求与仿真参数 | `ui/views/scene_configuration_page.py`、项目详情 feature-local 页面与 viewmodel、`src/trafficverse/application/scenario_service.py`、场景专属 model/service 及对应测试 |
| 姜云涛 | 仿真运行、实验管理、数据回放与分析 | `ui/views/live_monitor_page.py`、`ui/views/experiment_management_page.py`、`ui/views/data_analysis_page.py`、运行/回放专属 application 模块及对应测试 |
| 当轮集成负责人 | 主窗口装配、公共导航、公共协议、依赖与发布 | 下述共享热点；每轮只能指定一名集成负责人 |

共享热点包括 `AGENTS.md`、`pyproject.toml`、`uv.lock`、`bootstrap.py`、`cli.py`、公共 API、
domain models、contracts、主窗口、导航、公共 viewmodel、`ui/api_client/` 和 migrations。

- 并行期间只有当轮集成负责人修改共享热点；
- 功能分支先实现 feature-local 文件和测试，再提交集成清单；
- 每个任务开工前声明负责人、计划新增文件、计划修改文件白名单、共享热点接线和跨功能契约；
- 不覆盖、回退或格式化其他人的未提交改动；
- 范围变化先更新写入白名单；
- 冲突由文件当前负责人做语义合并，不用整文件覆盖；
- 合并顺序：领域/契约 → 功能 → 集成 → 生成契约与回归。

新页面私有弹窗放 `<feature>_dialogs.py`，状态放 `<feature>_viewmodel.py`，REST 能力放
`api/rest/<feature>.py`；不得把 feature 状态继续堆入 `RunViewModel`，也不得让多人直接编辑
`api/rest/routes.py`、`main_window.py` 或 `navigation.py`。这些接线由集成负责人集中完成。

## 5. Python 与类型规范

- Python 3.10，uv 是唯一环境与 lockfile 管理工具；
- Ruff 行宽 100；公共函数和属性必须有完整类型；
- 公共输入输出禁止无约束 `dict[str, Any]`；
- 配置、API、WebSocket 和持久化边界使用命名 Pydantic model；
- 第三方 SDK 对象必须在 adapter 内转换；
- 公共集合优先 `Sequence`、`Mapping`；
- 字段携带单位：`*_ms`、`*_s`、`*_m`、`*_mps`、`*_rad`；
- 权威仿真时间为整数 `simulation_time_ms`；
- 一个函数一个动作，副作用与纯计算分离；
- 队列必须有界，close 幂等，不使用真实 `sleep` 协调测试。

命名示例：

| 对象 | 规则 | 示例 |
|---|---|---|
| module/function | `snake_case` | `simulation_manager.py` |
| class/model | `PascalCase` | `VehicleState` |
| constant | `UPPER_SNAKE_CASE` | `DEFAULT_STEP_MS` |
| Port | 能力名 + `Port` | `TrafficEnginePort` |
| adapter | 技术名 + 能力名 | `SumoTrafficEngineAdapter` |
| test | `test_<behavior>_<expected>` | `test_pause_does_not_step` |

## 6. 错误、日志与资源

- adapter 捕获 SDK 异常并转换为稳定领域错误；
- 不写裸 `except:`，不静默忽略失败；
- 外部资源使用显式 `start/connect/close` 生命周期；
- 使用 `try/finally` 或 context manager 保证清理；
- 结构化日志至少包含 `component`、`event`、`level`；
- 高频每车每 tick 日志默认关闭；
- 不记录凭证、完整环境变量、隐私、本机路径或大型轨迹帧；
- 任务取消清理后继续传播 `CancelledError`。

## 7. 配置与契约

- YAML UTF-8、两个空格缩进、显式单位和稳定 `schema_version`；
- 未知字段默认拒绝；
- 加载顺序：安全默认值 → YAML → 允许的环境变量 → 校验 → resolved snapshot；
- secret 只来自环境或 secret store；
- REST 基础路径 `/api/v1`；
- WebSocket envelope 包含 `schema_version`、`type`、`experiment_id`、
  `simulation_time_ms`、`sequence`；
- 新消息类型同步 model、JSON Schema、契约测试和文档；
- 删除、改名、类型或语义变化提升主版本；
- OpenAPI/JSON Schema 由代码生成并由 snapshot test 锁定。

## 8. SUMO 与地图资产

- TraCI SDK 只出现在 `adapters/sumo/`；
- SUMO 网络从受控 Town04 OpenDRIVE 生成；
- 每次 step 恰好一次 `simulationStep()`，返回同一 SUMO 时间的不可变快照；
- 控制命令在 step 前批量应用；
- 连接丢失、时间回退或 step 失败使实验 FAILED；
- `network.json`/GeoJSON 只用于展示和查找；
- `manifest.yaml` 是地图资产权威清单；
- 派生资产必须记录来源、SUMO 版本、生成命令和 SHA-256；
- 生成 OpenAPI、JSON Schema 和 GeoJSON 必须可重复。

## 9. UI 规范

- UI 是 API 客户端，不导入后端 domain/application/adapters；
- `views/` 负责布局和事件转发，状态与交互放 `viewmodels/`；
- `api_client/` 统一管理 REST、WebSocket、重连和 sequence gap；
- MapLibre/deck.gl 只消费标准路网与 SUMO 快照；
- JavaScript 放 `ui/web/`，不以内联字符串散落在 Python；
- 所有 Web 依赖与模型离线加载；
- UI 不按墙上时间计算权威指标或车辆位置；
- 页面关闭时释放 WebGL、worker、bridge 和 Qt 资源；
- 用户错误必须给出可执行恢复建议。

## 10. 测试规范

测试目录镜像源码职责。一个测试验证一个主要行为，固定 seed、fake clock、稳定 ID，不依赖执行
顺序，不访问公网，不留下 artifact。

- Unit：无真实网络、时钟、数据库、SUMO 或 GUI；
- Contract：验证 Port、JSON Schema、OpenAPI、错误和版本兼容；
- Integration：真实单 adapter，通过 marker 显式选择；
- E2E：验证 SUMO/API/UI 完整路径；
- Performance：独立运行。

允许 marker：`integration`、`traffic`、`postgres`、`e2e`、`performance`。不得新增已移除组件的
marker。真实 SUMO 验收不能用 Fake 或截图替代。

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

## 11. 依赖与安全

- 新增依赖前确认标准库和现有依赖不能完成任务；
- 运行、开发和可选 integration 依赖分组声明；
- 修改 `pyproject.toml` 时通过 uv 同步 `uv.lock`；
- 不使用未固定 Git branch、nightly 或来源不明 wheel；
- 不提交 token、密码、私钥、真实数据库 URI 或含凭证日志；
- `.env.example` 只放无敏感示例；
- 文件路径限制在允许根目录，API 不接受任意 shell 命令；
- 测试和产品运行不得访问公网；
- 大于 10 MB 的新文件先决定 Git LFS/外部存储并记录 ADR。

## 12. Agent 流程与完成定义

1. 阅读 PRD、ADR、System Design、本文和 Agent Guide；
2. 检查并保留现有改动；
3. 确认允许路径、依赖和 Gate；
4. 定义接口、模型和失败语义；
5. 编写或更新测试；
6. 实现当前 Gate 的最小代码；
7. 运行与风险相称的检查；
8. 同步文档、schema、配置和生成物；
9. 报告已运行、未运行和环境阻塞的验证。

禁止删除断言、跳过关键测试、吞异常、静默修改公共协议或 ADR、用 monkey patch 绕过边界、提交
个人绝对路径实现，或在缺少真实依赖时宣称 integration/E2E 通过。

任务完成必须同时满足：目录与依赖方向正确、类型和配置完整、成功与失败路径有测试、相关检查
通过、资源无泄漏、契约同步、文档未过期、无凭证和运行产物、报告证据清楚。
