# TrafficVerse Engineering Standards

> 版本：v1.2  
> 状态：Accepted  
> 适用范围：本仓库全部源代码、测试、配置、脚本、迁移和文档  
> 相关文档：[PRD](docs/PRD.md)、[System Design](docs/SYSTEM_DESIGN.md)、[Agent Development Guide](docs/AGENT_DEVELOPMENT_GUIDE.md)、[ADR](docs/ADR.md)

## 1. 规范的使用方式

本文是 TrafficVerse 的代码规范和文件目录规范。所有开发者与 Agent 在修改仓库前必须阅读并遵守。

关键字含义：

- **MUST / 必须**：不可违反；违反时不能合并。
- **SHOULD / 应该**：默认遵守；偏离时需在变更说明中写明理由。
- **MAY / 可以**：按任务需要选择。

文档发生冲突时，不允许自行选择方便的版本：

1. 产品范围以 `docs/PRD.md` 为准；
2. 已接受架构决策以 `docs/ADR.md` 为准；
3. 模块、协议和运行时设计以 `docs/SYSTEM_DESIGN.md` 为准；
4. 代码和目录写法以本文为准；
5. 任务边界和验收标准以 `docs/AGENT_DEVELOPMENT_GUIDE.md` 为准。

若上层文档之间存在实质冲突，停止扩散实现，先更新对应设计或 ADR。不得用局部代码绕过文档冲突。

## 2. 不可破坏的系统约束

任何代码变更都必须保持：

1. SUMO/TraCI 是车辆、路线、车道和信号灯的全局真值源；SUMO GUI 不属于产品 UI。
2. CARLA 是 ROI 内视觉镜像，不独立决定全局运动学状态。
3. 只有 `SimulationManager` 可以调用 TraCI `simulationStep` 和 CARLA `world.tick()`。
4. Core Run 使用 50 ms 固定步长、Town04 同源资产和严格信号灯映射。
5. ROI 使用核心区+Buffer 滞回，不得改回单阈值同步。
6. 跨模块只使用公共领域模型、事件和 Port，不共享第三方 SDK 对象或全局可变状态。
7. 配置来自类型化 YAML，不硬编码领域和部署参数。
8. 实时状态与异步结果使用版本化 WebSocket envelope；资源 CRUD 使用 REST。
9. 高频轨迹使用 Parquet，关系元数据使用 PostgreSQL。
10. Core Run Gate 优先于 Product Gate 和性能优化。

修改上述约束必须先新增或替代 ADR。

## 3. 仓库目录规范

### 3.1 标准目录

```text
TrafficSIM/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock                         # 项目唯一 lockfile
├── .env.example
├── configs/
│   ├── runtime-baseline.yaml
│   ├── defaults.yaml
│   ├── scenarios/
│   │   └── core-run-town04.yaml
│   └── maps/
│       └── town04/
│           ├── manifest.yaml
│           ├── Town04.xodr
│           ├── network.json
│           ├── routes.yaml
│           ├── registration.yaml
│           ├── signals.yaml
│           └── network.geojson
├── contracts/
│   ├── scenario.schema.json
│   ├── openapi.yaml
│   └── websocket/
│       └── *.schema.json
├── src/
│   └── trafficverse/
│       ├── __init__.py
│       ├── cli.py
│       ├── bootstrap.py
│       ├── config/
│       ├── domain/
│       │   ├── models/
│       │   ├── enums.py
│       │   ├── errors.py
│       │   └── events.py
│       ├── ports/
│       │   ├── simulation.py
│       │   ├── persistence.py
│       │   └── messaging.py
│       ├── application/
│       │   ├── scenario_service.py
│       │   ├── simulation_manager.py
│       │   ├── metrics_engine.py
│       │   └── replay_service.py
│       ├── maps/
│       │   ├── opendrive_parser.py
│       │   ├── compiler.py
│       │   ├── geojson.py
│       │   └── validator.py
│       ├── traffic/
│       │   ├── engine.py
│       │   ├── network.py
│       │   ├── demand.py
│       │   ├── routing.py
│       │   ├── behavior.py
│       │   ├── lane_change.py
│       │   ├── signals.py
│       │   └── safety.py
│       ├── adapters/
│       │   ├── carla/
│       │   ├── persistence/
│       │   └── messaging/
│       ├── roi/
│       │   ├── geometry.py
│       │   ├── synchronizer.py
│       │   ├── signal_synchronizer.py
│       │   └── coordinate_transformer.py
│       ├── controllers/
│       ├── api/
│       │   ├── app.py
│       │   ├── dependencies.py
│       │   ├── rest/
│       │   └── websocket/
│       └── logging/
├── ui/
│   ├── app/
│   ├── api_client/
│   ├── models/
│   ├── views/
│   ├── viewmodels/
│   ├── widgets/
│   ├── web/
│   │   ├── map/
│   │   └── dashboard/
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
│   ├── maps/
│   ├── dev/
│   └── ci/
├── artifacts/                      # 运行产物；不提交
└── docs/
```

### 3.2 文件放置规则

| 内容 | 必须放置位置 | 禁止放置位置 |
|---|---|---|
| 领域模型、枚举、领域错误 | `src/trafficverse/domain/` | `api/`、`adapters/`、`ui/` |
| 第三方系统抽象接口 | `src/trafficverse/ports/` | 具体 adapter 文件中临时定义 |
| 用例编排、生命周期 | `src/trafficverse/application/` | FastAPI handler、UI callback |
| 依赖注入和具体 adapter 装配 | `src/trafficverse/bootstrap.py` | domain/application 内部 |
| CARLA/SQLAlchemy/WebSocket 实现 | 对应 `adapters/` | `domain/`、`controllers/` |
| OpenDRIVE 导入和原生地图编译 | `src/trafficverse/maps/` | CARLA adapter、UI |
| SUMO/TraCI adapter | `src/trafficverse/adapters/sumo/` | API handler、UI callback |
| ROI、配准、信号灯纯逻辑 | `src/trafficverse/roi/` | CARLA adapter 私有函数 |
| 车辆控制策略 | `src/trafficverse/controllers/` | TraCI connection、Simulation Manager |
| HTTP/WS 接入层 | `src/trafficverse/api/` | application/domain |
| PySide6、MapLibre、deck.gl、Plotly | `ui/` | 后端 domain/application |
| 公共机器契约 | `contracts/` | 手工复制在多个模块 |
| 用户可调配置 | `configs/` | Python 常量、UI 默认值 |
| 数据库 schema 变更 | `migrations/` | 应用启动时动态建表 |
| 开发/构建脚本 | `scripts/<purpose>/` | 仓库根目录散落脚本 |
| 运行日志、Parquet、截图、视频 | `artifacts/` | `src/`、`tests/fixtures/` |

目录必须在有实际文件时创建，不建立空目录树。仓库根目录不得新增临时 Python、SQL、JSON 或 shell 文件。根目录 `main.py` 不承载产品逻辑，T01 建立 CLI 后应删除示例入口。

### 3.3 包与模块边界

允许的依赖方向：

```text
ui → REST/WebSocket contracts
api → application → ports → domain
adapters → ports + domain
maps → domain
traffic → ports + domain
roi → domain + ports
controllers → domain + ports
bootstrap/cli → application + concrete adapters
```

必须遵守：

- `domain` 只允许导入 Python 标准库和 Pydantic；不得导入 FastAPI、CARLA、SQLAlchemy、PySide6。
- `ports` 只导入标准库、typing 和 domain。
- `application` 可以导入 domain/ports，不导入具体 adapter SDK。
- adapter 之间不得直接导入；协作由 application 层通过 Port 编排。
- 只有 `bootstrap.py`/CLI composition root 可以同时导入 application 和具体 adapters，用于构造依赖；其中不得包含业务规则。
- `api` 不直接导入 TraCI、CARLA 或 SQLAlchemy model。
- `ui` 不导入 `src/trafficverse`；只能使用 REST/WebSocket 和生成/本地镜像的协议模型。
- `controllers` 不持有 TraCI connection、不调用 CARLA，不访问数据库或 WebSocket。
- `__init__.py` 保持轻量，不启动线程、不连接外部系统、不读取文件、不执行注册副作用。
- 禁止循环导入。若出现循环，优先修正职责边界，不使用函数内 import 掩盖问题。

### 3.4 功能责任与并行开发边界

本节用于多人并行开发时减少同文件冲突。功能负责人对其垂直功能切片负责，但不因此获得修改共享
装配文件和公共契约的默认权限。若任务单另有明确分工，以任务单为准，并在开始开发前同步更新本节。

#### 3.4.1 默认功能分工

| 负责人 | 产品功能 | 默认可修改范围 |
|---|---|---|
| 吴思睿 | 工作台、资产中心、地图/车辆智能体资产管理、相关功能弹窗 | `ui/views/asset_center_page.py`、工作台与资产中心新增页面、`ui/widgets/asset_directory.py`、`ui/models/assets.py`、`src/trafficverse/maps/`、`src/trafficverse/api/map_catalog.py` 及对应测试 |
| 赵彦豪 | 项目详情、场景配置、交通需求与仿真参数配置 | `ui/views/scene_configuration_page.py`、项目详情新增页面、`src/trafficverse/application/scenario_service.py`、场景功能专属 model/service 及对应测试 |
| 姜云涛 | 仿真运行、实验管理、数据回放与分析 | `ui/views/live_monitor_page.py`、`ui/views/experiment_management_page.py`、`ui/views/data_analysis_page.py`、运行/回放功能专属 application 模块及对应测试 |
| 当轮集成负责人 | 主窗口装配、公共导航、公共协议、依赖与发布集成 | 下述共享热点文件；每轮只能指定一名集成负责人 |

功能负责人可以在自己的范围内新增 feature-local 文件。不得因为调用方需要某能力，就直接进入其他
负责人的页面、service 或测试文件实现。跨功能需求优先通过 Port、signal、REST/WS 契约或小型公共
model 交付。

#### 3.4.2 共享热点文件

以下文件容易被多个功能同时修改，默认视为受保护共享热点：

```text
AGENTS.md
pyproject.toml
uv.lock
src/trafficverse/bootstrap.py
src/trafficverse/cli.py
src/trafficverse/api/app.py
src/trafficverse/api/dependencies.py
src/trafficverse/api/rest/routes.py
src/trafficverse/api/contracts.py
src/trafficverse/domain/models/
contracts/
ui/app/main.py
ui/views/main_window.py
ui/views/navigation.py
ui/views/components.py
ui/viewmodels/run_viewmodel.py
ui/models/protocol.py
ui/api_client/
migrations/
```

- 并行开发期间，只有当轮集成负责人可以修改共享热点文件。
- 功能分支需要接入导航、主窗口、依赖注入或公共 API 时，先在功能目录完成实现和测试，再提交一份
  “集成清单”，列出需要注册的页面、路由、依赖和 signal；由集成负责人集中接线。
- 紧急情况下确需由功能负责人修改共享热点，必须先在任务记录中声明文件、改动目的和预计完成时间，
  获得其他受影响负责人确认后再修改；同一时间一个共享热点文件只能有一个写入者。
- 禁止在功能分支中顺带格式化、重命名或重排共享热点及其他负责人文件。

#### 3.4.3 新功能文件组织

新增功能应优先按功能拆文件，避免继续扩大单体页面或单体路由：

```text
ui/views/<feature>_page.py
ui/views/<feature>_dialogs.py
ui/viewmodels/<feature>_viewmodel.py
src/trafficverse/api/rest/<feature>.py
src/trafficverse/application/<feature>_service.py
tests/unit/ui/test_<feature>_*.py
tests/unit/application/test_<feature>_service.py
```

- 页面私有弹窗放在对应 `<feature>_dialogs.py`，不得把功能弹窗加入
  `ui/views/components.py`；只有两个以上已落地功能复用且接口稳定后才可提升为公共组件。
- 页面状态和业务逻辑放 feature-local viewmodel；不得继续向 `RunViewModel` 添加与运行控制无关的
  工作台、资产或场景表单状态。
- 新 REST 能力放 feature route 模块，避免多人直接修改 `api/rest/routes.py`；路由注册由集成负责人
  完成。
- 测试默认只修改与本功能对应的测试文件。公共契约测试由集成负责人统一生成和更新。

#### 3.4.4 开工、交付与冲突处理

每个并行任务开始前必须在任务说明中写明：

1. 功能负责人和功能名称；
2. 计划新增文件；
3. 计划修改文件（写入白名单）；
4. 是否需要共享热点集成；
5. 对其他功能提供或依赖的契约。

开发过程中必须遵守：

- 只修改写入白名单中的文件；范围变化时先更新任务说明并通知受影响负责人。
- 不覆盖、不回退、不“顺手修复”其他负责人未合并的改动。
- 发现跨功能缺陷时，先提交最小复现或接口需求给对应负责人；未经协调不得跨区修复。
- 公共契约先定生产者、消费者和兼容性，再由功能负责人分别实现两端；禁止双方同时编辑同一文件。
- 合并顺序固定为：领域/契约基础 → 功能实现 → 集成接线 → 生成契约与回归验证。
- 发生冲突时由文件当前负责人处理语义合并；不得使用整文件覆盖解决冲突。

功能交付必须附带：

- 实际修改文件清单；
- 对外接口、signal、路由或 model 变更；
- 需要集成负责人执行的接线步骤；
- 已运行测试和未运行测试；
- 已知会影响其他负责人的后续事项。

## 4. Python 代码规范

### 4.1 工具链

项目固定 Python 3.10。T01 必须在 `pyproject.toml` 配置：

- Ruff：格式化、lint、import sorting；
- mypy：静态类型检查；
- pytest：测试；
- coverage.py/pytest-cov：覆盖率报告。

项目统一使用 uv 管理 Python 环境和 lockfile。安装与检查命令：

```bash
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

自动修复只针对当前任务涉及文件；不得借格式化工具重写无关目录。Ruff 行宽固定为 100。

### 4.2 命名

| 对象 | 规则 | 示例 |
|---|---|---|
| package、module、函数、变量 | `snake_case` | `simulation_manager.py`、`run_tick` |
| 类、枚举、Pydantic model | `PascalCase` | `VehicleState`、`ExperimentStatus` |
| 常量 | `UPPER_SNAKE_CASE` | `DEFAULT_STEP_MS` |
| Protocol/外部端口 | 能力名 + `Port` | `TrafficEnginePort`、`EventPublisherPort` |
| 具体实现/adapter | 技术名 + 能力名 | `NativeTrafficEngine`、`CarlaAdapter` |
| application service | 用例名 + `Service` 或 `Manager` | `ScenarioService`、`SimulationManager` |
| 异常 | 语义名 + `Error` | `VersionMismatchError` |
| 测试 | `test_<behavior>_<expected>` | `test_vehicle_exits_buffer_destroys_actor` |

缩写在类名中按普通单词处理：`RoiSynchronizer`、`ApiClient`，不要写成 `ROISynchronizer`。协议字段沿用已冻结形式，例如 `experiment_id`、`simulation_time_ms`。

### 4.3 类型和数据模型

- 所有公共函数、方法和属性必须有完整类型标注。
- 禁止无约束 `dict[str, Any]` 作为公共输入输出。
- Pydantic model 用于配置、API、WebSocket、持久化边界和公共领域契约。
- `dataclass(frozen=True, slots=True)` 可用于模块内部不可变值对象和纯计算结果。
- 第三方 SDK 对象必须在 adapter 内转换为 TrafficVerse model。
- `Any` 仅允许在不可避免的第三方原始边界，必须局部收窄并注释原因。
- 不使用可变默认参数；集合默认值使用 `default_factory`。
- 对外返回集合优先使用 `Sequence`、`Mapping`；内部确需修改时再使用 `list`、`dict`。
- 空值必须有明确语义；不要用空字符串、`0` 或空字典代替 `None`。
- 枚举值显式稳定，不依赖 `auto()` 生成对外协议值。

### 4.4 时间、单位和 ID

字段名必须携带单位：

- 时间：`*_ms`、`*_s`；权威仿真时间为整数 `simulation_time_ms`。
- 距离：`*_m`；速度：`*_mps`；加速度：`*_mps2`；角度：`*_rad`。
- 字节：`*_bytes`；频率：`*_hz`。

禁止使用无单位的 `timeout`、`speed`、`duration` 作为跨模块字段。UI 显示 km/h 时，只在 view/viewmodel 转换，不修改领域值。

资源 ID 使用 UUID，车辆主 ID 使用场景指定或引擎生成的稳定字符串 ID。CARLA Actor ID 只在当前 world 生命周期内使用，禁止作为持久化主键；信号灯持久化使用原生 signal ID 和 OpenDRIVE signal ID binding。

### 4.5 函数、类和模块

- 一个函数只承担一个可描述的动作；优先早返回，避免超过三层嵌套。
- 四个以上含义相近的参数应使用类型化 command/config 对象；避免布尔参数控制多种行为。
- 副作用与纯计算分离。例如 ROI `reconcile` 只生成 plan，adapter 负责应用。
- 一个类只有一个主要变化原因。不要创建 `Utils`、`Helpers`、`Common` 等无领域含义的聚合类或文件。
- 模块通常应保持在约 400 行以内；超过时按职责拆分，不为满足行数机械拆文件。
- 函数通常应保持在约 50 行以内；复杂状态机和协议解析可例外，但必须有测试和清晰分段。
- 公共 API 只暴露调用方需要的最小表面；下划线前缀表示模块私有实现。
- 不为了未来可能需求提前创建抽象。第二个真实实现出现或 Port 边界已由架构明确时再抽象。

### 4.6 异步、并发和资源生命周期

- `async` 只用于实际异步 I/O、队列或生命周期编排，不把纯计算包装成 async。
- 禁止在 event loop 中执行阻塞 CARLA/文件调用或长时间 CPU 密集地图编译；使用专用执行边界并保持调用顺序。
- 所有队列必须有明确容量、溢出策略和监控指标；禁止无界队列。
- 只有 Simulation Manager 推进仿真；任何 callback、worker、UI、logger 不得调用 step/tick。
- 外部资源使用显式 `start/connect/close` 生命周期；关闭必须幂等。
- 使用 `try/finally` 或 async context manager 保证清理。
- 任务取消不得吞掉 `CancelledError`；清理完成后继续传播取消。
- 不使用真实 `sleep` 协调测试；使用 fake clock、event 或受控队列。

### 4.7 错误处理

- 领域和应用层抛出 `domain/errors.py` 中的稳定错误类型和错误码。
- adapter 捕获 SDK 异常并转换，禁止将 TraCI/CARLA/SQLAlchemy 原始异常泄漏到 API/UI。
- 不写裸 `except:`；捕获 `Exception` 时必须在边界记录上下文并重新抛出或转换。
- 不静默忽略失败。允许降级时必须发布领域事件并更新组件健康。
- 错误信息不得包含凭证、完整环境变量、用户隐私或任意本机路径。
- 状态变化和资源清理必须保持幂等；重复命令返回稳定结果或明确冲突。

### 4.8 日志与可观测性

- 使用结构化日志，不使用 `print()` 记录运行状态。
- 每条运行日志至少包含：`component`、`event`、`level`；有上下文时增加 `trace_id`、`experiment_id`、`simulation_time_ms`、`vehicle_id`。
- 日志消息使用稳定事件名，例如 `roi.actor_spawn_failed`，说明文字放字段中。
- 高频每车每 tick 日志默认关闭；使用计数器、采样或 debug level。
- 不在日志中写 base64 相机数据、完整轨迹帧或大型配置。
- 异常使用 `logger.exception` 保留 stack trace；预期业务拒绝不记录为系统异常。

### 4.9 注释和文档字符串

- 标识符、公共 docstring、错误码和协议字段使用英文。
- 面向用户的 UI 文案和项目说明可使用中文。
- 注释解释“为什么”和约束来源，不重复代码表面行为。
- 公共 Port、领域模型中的非显然字段、复杂算法和兼容 workaround 必须有 docstring。
- TODO 格式：`TODO(owner-or-task): reason and removal condition`；禁止无上下文 TODO。
- 不保留大段注释掉的代码；删除后依赖版本控制恢复。

## 5. 配置和契约规范

### 5.1 配置

- 所有用户可调和部署参数进入类型化配置 model。
- YAML 使用两个空格缩进、UTF-8、显式单位字段和稳定 `schema_version`。
- 未知字段默认拒绝，避免拼写错误静默生效。
- 配置加载顺序固定：代码安全默认值 → YAML → 允许的环境变量覆盖 → 类型/交叉/环境校验 → 不可变 resolved snapshot。
- 环境变量只覆盖部署字段，例如 host、port、数据库连接；不得覆盖 seed、路线和自动驾驶比例而不写入 resolved snapshot。
- secret 只来自环境或 secret store，不进入 YAML、日志、测试 fixture 或 Git。
- `configs/defaults.yaml` 只放跨场景默认值；地图专属参数放对应 map 目录。

### 5.2 REST 和 WebSocket

- REST 基础路径固定 `/api/v1`；handler 只做校验、鉴权预留、调用 application service 和序列化。
- request/response 必须使用命名 Pydantic model，不返回临时字典。
- 错误使用统一 `error.code/message/details/trace_id` 结构。
- 写接口按设计实现幂等和乐观锁；不得在 HTTP 请求内等待长时间仿真完成。
- WebSocket 消息必须使用统一 envelope，并携带 `schema_version`、`type`、`experiment_id`、`simulation_time_ms` 和 `sequence`。
- 命令回复必须设置 `correlation_id`。
- 新增消息类型必须同时更新 model、JSON Schema、契约测试和文档。
- Core Run 不定义或发布 `camera.frame`；CARLA 画面由 Qt 直接托管本机原生窗口。

### 5.3 契约变更

- 新增可选字段可以保持当前主版本；删除、改名、类型改变或语义改变必须提升主版本。
- `contracts/` 中的 OpenAPI/JSON Schema 由代码生成并由 snapshot test 锁定。
- 生成文件头部必须注明生成来源和命令；禁止手工修改生成结果。
- 公共契约变更必须列出生产者、消费者、兼容性和迁移顺序。

## 6. Adapter 规范

### 6.1 SUMO / Map Assets

- TraCI SDK 只放在 `adapters/sumo/`，通过 `TrafficEnginePort` 向 application 暴露能力。
- SUMO 网络必须由同一 Town04 OpenDRIVE 生成；运行时只加载已校验的 `.sumocfg` 资产。
- 每次 step 恰好调用一次 `simulationStep`，并返回同一 SUMO 时间的不可变 `TrafficSnapshot`。
- SUMO 连接丢失、时间回退或 step 失败必须转换为稳定领域错误并使当前实验失败。
- 控制命令在 step 前批量应用；单车非法命令不得阻断其他合法命令。
- `network.json`/GeoJSON 只用于展示和查找，不参与车辆推进，不形成第二真值。

### 6.2 CARLA

- CARLA SDK 只出现在 `adapters/carla/`。
- client/server 版本必须一致；不匹配时拒绝 READY。
- Simulation Manager 是唯一 tick 发起者。
- 车辆和信号灯使用 batch API；部分失败返回逐项结果。
- 镜像车辆禁用 autopilot，不让 CARLA 物理反写 SUMO。
- CARLA world reload 后必须重新解析 Actor 和 OpenDRIVE signal binding。
- 产品不创建 UI 专用 RGB sensor；CARLA 原生窗口由 Qt foreign-window 容器托管。
- close 时恢复原始 world settings 并销毁本系统创建的全部 Actor/sensor。

### 6.3 Persistence

- SQLAlchemy model 留在 persistence adapter，不进入 domain。
- repository 方法实现 Port，不将 session 暴露给 application。
- 一个用例需要原子性时，由明确 Unit of Work/transaction 边界控制。
- 查询必须分页；禁止无条件加载整张事件或轨迹表。
- 高频轨迹不得逐车逐 tick 写 PostgreSQL。

## 7. 数据库和迁移规范

- 所有 schema 修改通过 Alembic migration；文件名使用 `<revision>_<short_description>.py`。
- migration 必须包含可执行 upgrade；可逆变更提供 downgrade，不可逆时在文件和变更说明中明确。
- 生产启动不得调用 `create_all()` 自动建表。
- 表名、列名、索引名使用 `snake_case`。
- 主键、外键、唯一约束和状态枚举在数据库层同时约束，不能只依赖应用校验。
- 时间审计字段使用 UTC timezone-aware timestamp；仿真时间使用 bigint 毫秒。
- JSONB 只保存结构确实可变的数据；核心可查询字段使用显式列。
- migration 测试至少验证空库 upgrade 到 head，以及 downgrade/upgrade 循环（可逆时）。

## 8. UI 代码规范

- UI 是 API 客户端，不得导入后端 domain/application/adapters。
- `views/` 只负责布局和事件转发；状态与交互逻辑放 `viewmodels/`。
- `api_client/` 统一管理 REST、WebSocket、重连、sequence gap 和错误转换。
- 网络、JPEG 解码和大数据转换不得阻塞 Qt UI thread。
- Qt signal/slot 名称表达领域事件，例如 `experiment_state_changed`。
- Widget 不自行计算权威指标，不保存第二份业务状态。
- MapLibre/deck.gl 只消费路网和 SUMO 派生的标准车辆/信号消息；不得嵌入 SUMO GUI。
- JavaScript 代码放 `ui/web/`，不以内联字符串散落在 Python view 中。
- 用户可见错误必须给出可执行恢复建议，不只显示 stack trace。
- 控件启用状态由实验状态机驱动，不在多个页面重复判断。

## 9. 测试规范

### 9.1 目录和命名

测试目录按行为层级组织，并尽量镜像源码路径：

```text
src/trafficverse/roi/synchronizer.py
tests/unit/roi/test_synchronizer.py

src/trafficverse/adapters/carla/client.py
tests/unit/adapters/carla/test_client.py
tests/integration/carla/test_carla_adapter.py
```

- 测试文件：`test_<subject>.py`。
- 测试函数：`test_<condition>_<expected_behavior>`。
- 一个测试验证一个主要行为；Arrange/Act/Assert 清晰分离。
- 参数化用于相同规则的输入矩阵，不把不同业务行为塞入一个巨型测试。

### 9.2 测试层级

- Unit：无网络、无真实时钟、无真实数据库、无 SUMO/CARLA/GUI；adapter 使用 Fake runtime。
- Contract：验证 Port fake、JSON Schema、OpenAPI、错误结构和版本兼容。
- Integration：验证单个真实 adapter；通过 marker 显式选择。
- E2E：验证 Core Run/Product Gate 的完整用户路径。
- Performance：独立运行，不混入默认快速测试。

推荐 marker：`integration`、`traffic`、`carla`、`postgres`、`e2e`、`performance`。

### 9.3 测试数据和确定性

- 使用固定 seed、fake clock、稳定 vehicle ID 和受控 route。
- 不依赖测试执行顺序，不共享可变 fixture。
- `conftest.py` 只放当前目录树通用 fixture；局部 fixture 放测试文件。
- 优先使用真实 model 和手写 Fake Port，少用深层 SDK mock 链。
- golden/snapshot 文件必须小、可审阅并说明生成方式。
- 测试不得访问公网。
- 临时文件使用 pytest `tmp_path`，测试完成后不在仓库留下 artifact。

### 9.4 回归要求

每个缺陷修复必须包含能在修复前失败的回归测试。每个新行为至少覆盖：

- 正常路径；
- 边界/空输入；
- 外部失败和清理；
- 非法状态或非法配置；
- 与时间、顺序、幂等相关的性质（适用时）。

Core Run 的真实验收不能用 Fake 代替，也不能只提供截图。

## 10. 文件、资产和生成物规范

- 文本文件使用 UTF-8、LF、文件末尾换行。
- Python/YAML/JSON/Markdown 不含无意义尾随空格。
- JSON 机器文件使用稳定键顺序生成；YAML 保持人类可读。
- Town04 派生资产必须来自同一 CARLA 发行版，记录 checksum 和生成命令。
- `manifest.yaml` 是地图资产权威清单；修改任何被追踪文件后必须更新并重新验证。
- 大于 10 MB 的新增文件、二进制资产或录制结果不得直接提交；确需版本化时先决定 Git LFS/外部存储并记录 ADR。
- `artifacts/`、日志、Parquet、截图、视频、数据库文件、cache 和 IDE 文件必须 gitignore。
- 测试 fixture 不复制完整 Town04 大文件；集成测试通过 manifest 引用受控资产。
- 生成的 OpenAPI、JSON Schema 和 GeoJSON 必须可由脚本重复生成。

## 11. 依赖和安全规范

- 新增依赖前先确认标准库或现有依赖不能合理完成任务。
- 运行依赖、开发依赖和可选集成依赖分组声明。
- 依赖版本写入 `pyproject.toml` 并通过 uv 更新 `uv.lock`；禁止只修改本地环境。
- 不使用未固定 Git branch、nightly 或来源不明 wheel 作为 Core Run 依赖。
- CARLA Python API 必须与 server package 同源同版。
- 不提交 token、密码、私钥、真实数据库 URI 或包含凭证的日志。
- `.env.example` 只放无敏感示例值。
- 文件路径输入必须限制在允许根目录，API 不接受任意 shell 命令。

## 12. Agent 开发流程

每个 Agent 必须按以下顺序工作：

1. 阅读 PRD、ADR、System Design、本文、Agent Guide 和自己的任务章节。
2. 检查当前文件和已有改动，保留用户或其他任务的工作。
3. 确认任务允许修改的路径、依赖状态和 Core/Product Gate。
4. 先定义或确认接口、数据模型和失败语义。
5. 编写或更新能证明行为的测试。
6. 实现满足当前 Gate 的最小代码，不提前实现延期优化。
7. 运行与风险相称的 format、lint、typecheck、unit、contract、integration/E2E。
8. 更新受影响文档、schema、配置示例和生成物。
9. 按 Agent Guide 格式提交完成报告，逐项给出验收证据。

禁止：

- 未经要求重写无关模块；
- 为通过测试删除断言、跳过关键测试或吞掉异常；
- 在缺少真实依赖时宣称集成/E2E 已通过；
- 静默修改公共协议或 ADR；
- 用全局变量、monkey patch 或模块导入副作用绕过依赖设计；
- 提交仅能在个人绝对路径运行的实现；
- 为未来优化延迟 Core Run 主链。

## 13. Definition of Done

一个代码任务只有同时满足以下条件才算完成：

1. 代码位于正确目录，依赖方向合法；
2. 公共接口有类型标注，配置和协议使用命名 model；
3. 成功、边界、失败和清理路径有测试；
4. Ruff format/check、mypy 和相关 pytest 通过；
5. 外部资源无泄漏，队列有界，状态变化幂等；
6. 新配置有 schema、默认值、校验和示例；
7. 公共契约和生成文件同步更新；
8. 相关文档和 ADR 未过期；
9. 未引入凭证、运行 artifact、大型未管理文件或本机路径；
10. 完成报告明确区分已运行、未运行和受环境阻塞的验证。

任何“功能看起来能跑”但不满足上述条件的变更都不是完成状态。

## 14. 规范例外

确需偏离本文时，变更说明必须包含：

- 具体规则；
- 无法遵守的技术原因；
- 影响范围和风险；
- 替代保护措施；
- 恢复到规范的条件或后续任务。

涉及架构、真值权属、时间同步、地图资产、信号灯、协议兼容或存储分工的例外，必须通过 ADR，不接受仅在代码评审说明中豁免。
