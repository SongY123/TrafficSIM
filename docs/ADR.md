# TrafficVerse Architecture Decision Record

> 版本：v1.4
> 状态：Target Baseline（实现迁移中）
>
> 输入：[PRD.md](./PRD.md)
>
> 设计：[SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md)
>
> 实施：[AGENT_DEVELOPMENT_GUIDE.md](./AGENT_DEVELOPMENT_GUIDE.md)

## 1. ADR 使用规则

本文记录 TrafficVerse v1.0 的关键技术决策，目的是让后续 Agent 理解“为什么这样设计”，而不是只看到当前代码。

状态定义：

- **Proposed**：待验证或待评审；
- **Accepted**：实现必须遵守；
- **Deprecated**：仍可能存在但不可用于新实现；
- **Superseded**：已被另一个 ADR 替代。

变更规则：

1. 已接受 ADR 不直接改写结论；发生方向变化时新增 ADR，并在旧记录标记 `Superseded by ADR-xxx`。
2. 仅补充事实、链接或澄清措辞时可原地更新，但不得悄悄改变决策语义。
3. 偏离 Accepted 决策前，Agent 必须给出场景、证据、替代方案、迁移影响和回滚方案。
4. ADR 约束优先于局部实现便利；PRD 产品目标变化则先更新 PRD，再更新 ADR 和系统设计。

## 2. 决策索引

| ID | 决策 | 状态 |
|---|---|---|
| ADR-001 | 使用 SUMO + CARLA 混合仿真 | Superseded by ADR-022 |
| ADR-002 | SUMO 是全局运动学 Truth Source | Superseded by ADR-022 |
| ADR-003 | 使用核心 ROI + Buffer 滞回同步 | Accepted |
| ADR-004 | 使用中央固定步长与单一仿真时钟 | Accepted |
| ADR-005 | 核心编排和后端采用 Python | Accepted |
| ADR-006 | FastAPI + REST + WebSocket 分工 | Accepted |
| ADR-007 | YAML 场景配置 + 类型化启动校验 | Accepted |
| ADR-008 | 契约优先、统一领域模型和 Port/Adapter | Accepted |
| ADR-009 | 自动驾驶控制意图回写 SUMO，不由 CARLA 反向定真值 | Superseded by ADR-022 |
| ADR-010 | PostgreSQL + Parquet + JSON/YAML 分层存储 | Accepted |
| ADR-011 | PySide6 作为第一阶段 UI，保留 React 替换边界 | Accepted |
| ADR-012 | 回放采用 Snapshot + Delta/Event，而非重跑仿真 | Accepted |
| ADR-013 | 显式地图配准与集中坐标转换 | Accepted |
| ADR-014 | 有界队列、可观察降级与差异化故障策略 | Accepted |
| ADR-015 | MVP 采用模块化单体，外部仿真器保持进程边界 | Accepted |
| ADR-016 | 统一 ID、仿真时间、单位、版本与确定性规则 | Accepted |
| ADR-017 | MVP 二维地图采用 Leaflet，指标图表采用 Plotly | Superseded by ADR-026 |
| ADR-018 | 固定首个可运行环境与版本矩阵 | Superseded by ADR-024/025 |
| ADR-019 | 固定 Town04 同源地图资产并由 SUMO 主控信号灯 | Superseded by ADR-022 |
| ADR-020 | MVP 采用 Leaflet 平面坐标与 JSON JPEG 相机帧 | Superseded by ADR-025 |
| ADR-021 | 先通过 Core Run Gate，再实现产品与优化能力 | Superseded by ADR-024/025 |
| ADR-022 | 自研 Native Traffic Engine 替代 SUMO，MVP 只实现基础交通能力 | Superseded by ADR-024 |
| ADR-023 | macOS 控制端使用远程 CARLA Simulation Runtime | Superseded by ADR-024/025 |
| ADR-024 | 恢复 SUMO 为全局交通真值并由 TrafficVerse 统一联仿 | Accepted |
| ADR-025 | PySide6 托管本机 CARLA 原生窗口，不传输 RGB 画面 | Accepted |
| ADR-026 | 左侧地图迁移到 MapLibre + deck.gl | Accepted |
| ADR-027 | 原生 SUMO 二维场景包自动发现并使用主机 SUMO 托管运行 | Accepted |

---

## ADR-001 — 使用 SUMO + CARLA 混合仿真

- 状态：Superseded by ADR-022
- 日期：2026-07-15

### 背景

产品同时要求数千车辆的全局交通流和局部高保真三维自动驾驶行为。SUMO 擅长大规模路网、路由、信号灯、跟驰和换道；CARLA 擅长三维场景、车辆模型、天气、相机和传感器表现。单独使用任一工具都会牺牲另一端核心能力。

### 决策

采用 SUMO + CARLA 混合架构：SUMO 负责全路网交通计算，CARLA 只渲染 ROI 内选定车辆与环境，TrafficVerse 负责时间、坐标、车辆生命周期和状态同步。

### 选择理由

- 直接复用两个成熟仿真器的互补能力；
- 大部分车辆只存在于 SUMO，避免 CARLA Actor 数随全路网车辆线性增长；
- 符合“二维宏观 + 三维微观”的科研展示目标；
- 控制器与展示层解耦，后续可以独立替换算法或 UI。

### 放弃的方案

- **仅 CARLA**：高保真，但大规模交通流成本和建模能力不合适。
- **仅 SUMO**：规模合适，但无法达到三维展示和自动驾驶视觉演示目标。
- **自研统一仿真器**：控制力最大，但成本、验证难度和交付周期不可接受。

### 后果与约束

- 必须解决地图配准、时间同步、ID 映射、版本兼容和双进程故障；
- 集成测试环境更重，CI 应拆成无仿真器、SUMO、SUMO+CARLA 三档；
- 不允许为减少同步工作而让两个仿真器各自独立演化同一车辆。

---

## ADR-002 — SUMO 是全局运动学 Truth Source

- 状态：Superseded by ADR-022
- 日期：2026-07-15

### 背景

混合仿真若没有明确权威源，会出现 SUMO 与 CARLA 的位置、速度、碰撞和车辆存在性互相冲突，难以统计、复现和回放。

### 决策

SUMO 是所有车辆存在性、位置、速度、加速度、车道、路线和信号灯的全局权威来源。CARLA Actor 是视觉镜像。Dashboard、记录器、2D 地图和回放都以标准化后的 SUMO 状态为基础；CARLA 仅补充视觉帧和三维组件健康信息。

### 选择理由

- SUMO 能稳定承载全局车辆规模；
- 单一权威源消除双向冲突和不可解释的状态分叉；
- 科研指标和回放有统一依据；
- ROI 外车辆和 ROI 内车辆使用同一交通规则连续演化。

### 放弃的方案

- **CARLA Truth Source**：无法覆盖 ROI 外全局车辆，规模成本高。
- **双主同步**：需要冲突解决和连续校正，容易产生振荡与不可复现行为。
- **ROI 内 CARLA、ROI 外 SUMO 分区真值**：车辆过边界时必须迁移动力学状态，复杂且破坏连续性。

### 后果与约束

- CARLA 碰撞或物理反应默认不直接改写 SUMO；如需闭环物理研究，必须另立 ADR。
- CARLA 镜像车辆关闭 autopilot，由 TrafficVerse 更新 transform。
- SUMO 断连属于真值丢失，实验默认失败；CARLA 断连可按配置降级为二维仿真。

---

## ADR-003 — 使用核心 ROI + Buffer 滞回同步

- 状态：Accepted
- 日期：2026-07-15

### 背景

将所有车辆生成到 CARLA 会耗尽渲染和物理预算。仅使用单一 ROI 边界又会导致车辆在边界附近反复创建/销毁，产生闪烁、资源抖动和失败概率放大。

### 决策

使用带滞回的 ROI：未映射车辆进入核心半径时创建；已映射车辆离开 `核心半径 + buffer` 后销毁；两者之间保持原状态。基线配置为核心半径 1000 m、buffer 200 m，均可由 YAML 配置。

### 选择理由

- 将 CARLA 负载限制在局部范围；
- 滞回避免边界抖动；
- 算法简单、可解释、可用纯逻辑测试；
- 支持固定焦点、跟车焦点和后续多 ROI 扩展。

### 放弃的方案

- **全量镜像**：不能满足数千车辆目标。
- **单阈值 ROI**：边界抖动明显。
- **每 N 秒批处理替换全部 Actor**：视觉不连续且尖峰负载大。
- **只按车辆重要性、不考虑空间**：难以保证局部三维场景完整性。

### 后果与约束

- 同步器必须维护一一 binding，处理 spawn 失败、Actor 意外消失和 SUMO 车辆消失。
- Actor 达上限时按关注车辆与距焦点距离确定优先级，并发出降级事件。
- “ROI 大小”在配置中明确为半径，避免将 PRD 的 1000 米误解为直径。

---

## ADR-004 — 使用中央固定步长与单一仿真时钟

- 状态：Accepted
- 日期：2026-07-15

### 背景

SUMO、CARLA、控制器、UI 和记录器有不同运行速度。如果各自使用墙上时间或独立循环，状态会错帧，暂停/倍速/回放也难以定义。

### 决策

Simulation Manager 持有唯一仿真时钟，以配置的固定 `step_ms` 串行推进控制器、SUMO、ROI、CARLA 和采集。权威时间是整数 `simulation_time_ms`。播放倍率只改变 wall-clock 调度，不改变仿真步长。

### 选择理由

- 同一时间点的状态和指标可对齐；
- 支持确定性、暂停、逐帧和倍速；
- 更容易定位慢组件和验证调用顺序；
- 避免浮点时间累计误差。

### 放弃的方案

- **各组件自由运行**：吞吐可能更高，但同步和复现困难。
- **可变步长**：适合部分数值模拟，但控制器和两个仿真器的行为更难一致。
- **墙上时间为权威**：负载抖动会改变实验结果。

### 后果与约束

- CARLA 必须开启同步模式，fixed delta 与配置一致。
- 单个 tick 内顺序固定，外部命令进入串行队列。
- 慢 UI/日志不得阻塞权威 tick；需要有界队列和流控。

---

## ADR-005 — 核心编排和后端采用 Python

- 状态：Accepted
- 日期：2026-07-15

### 背景

SUMO TraCI、CARLA、科研计算、数据处理和 FastAPI 都有成熟 Python 生态。项目强调科研迭代和 Agent 自动开发，需要较低集成成本和统一语言。

### 决策

核心领域、应用编排、仿真 adapters、API、记录和回放采用受支持版本的 Python；通过 `pyproject.toml` 固定具体版本范围，使用完整类型标注和静态检查。

### 选择理由

- 两个仿真器和数据生态的一等支持；
- 研发速度与科研可扩展性高；
- FastAPI/Pydantic/PyArrow/SQLAlchemy 可覆盖所需能力；
- 降低多语言跨进程协议数量。

### 放弃的方案

- **C++ 全栈**：运行效率高，但开发和 UI/API 集成成本高。
- **Java/Kotlin**：后端成熟，但 CARLA/SUMO 科研生态不如 Python 直接。
- **Node.js 后端**：Web 能力强，但仿真 SDK 和数值处理不占优。

### 后果与约束

- 高频路径优先批量 SDK 调用、向量化和进程隔离，不能仅靠线程绕过 CPU 瓶颈。
- 类型检查、lint 和测试是合并门禁；禁止以动态 `dict` 代替公共契约。
- 若性能证据表明确需原生扩展，应新增 ADR，保留 Python Port 边界。

---

## ADR-006 — FastAPI + REST + WebSocket 分工

- 状态：Accepted
- 日期：2026-07-15

### 背景

系统既有场景/实验等低频资源操作，也有车辆状态、Dashboard、事件、命令结果等实时双向流。纯轮询延迟和开销较高，纯 WebSocket 又不利于资源语义、缓存、OpenAPI 和调试。

### 决策

后端使用 FastAPI。REST 负责场景、实验、事件、指标和 artifact 的 CRUD/查询；WebSocket 负责异步控制命令、状态变化、实时车辆 delta、Dashboard、事件和回放流。两者共享版本化 Pydantic 模型。

### 选择理由

- REST 对低频资源语义清晰，易生成 OpenAPI；
- WebSocket 提供低延迟双向通信和订阅；
- FastAPI 与 Python/Pydantic 领域契约整合自然；
- 同一网关便于第一阶段本机部署和第二阶段 Web UI。

### 放弃的方案

- **全部 REST 轮询**：实时性和带宽效率较差。
- **全部 WebSocket**：资源操作、幂等、缓存和工具支持变复杂。
- **gRPC 到 UI**：强类型高效，但浏览器/桌面集成和可调试性成本更高。
- **消息队列直接暴露 UI**：部署复杂度超出 MVP。

### 后果与约束

- “所有异步通信用 WebSocket”不等于“禁止 REST”；异步结果不得由长 HTTP 请求等待。
- 每条 WebSocket 消息包含版本、实验 ID、仿真时间、sequence 和 correlation。
- 慢客户端必须流控；不能让发送队列拖慢仿真循环。

---

## ADR-007 — YAML 场景配置 + 类型化启动校验

- 状态：Accepted
- 日期：2026-07-15

### 背景

科研实验需要可读、可复制、可版本化配置。未校验的自由格式 YAML 容易把错误推迟到长时间仿真后才暴露，硬编码又破坏可复现性。

### 决策

用户场景采用 YAML；加载后映射为类型化 `ScenarioConfig`，执行语法、字段、交叉字段和环境四层校验。实验创建时保存解析后的不可变配置快照及 hash。部署字段可由环境变量覆盖。

### 选择理由

- YAML 对人工编辑和科研参数友好；
- 类型和交叉校验能尽早失败；
- 快照与 hash 支持复现和审计；
- UI、CLI、API 可复用同一 schema。

### 放弃的方案

- **只使用 JSON**：机器友好，但手写大场景可读性较弱。
- **只存数据库表单字段**：版本控制和跨环境共享不便。
- **Python 配置文件**：表达力强但可执行，安全性和跨工具兼容较差。

### 后果与约束

- 所有可调领域参数必须进入 schema，不得散落常量。
- 未知字段默认拒绝，避免拼写错误被忽略。
- secret 不写入场景快照；当前场景原则上不需要凭证。

---

## ADR-008 — 契约优先、统一领域模型和 Port/Adapter

- 状态：Accepted
- 日期：2026-07-15

### 背景

项目由多个 Agent 分任务开发。若模块共享第三方对象、数据库 model 或自由 `dict`，各任务会产生隐式耦合，集成时才发现字段和生命周期不一致。

### 决策

跨模块使用 `VehicleState`、`SimulationFrame`、`DomainEvent` 等统一领域模型；外部系统通过 Protocol/Port 抽象，具体 SDK 位于 adapters。先定义接口和契约测试，再实现逻辑。

### 选择理由

- 支持并行开发和无外部依赖测试；
- 将 TraCI/CARLA/SQLAlchemy/FastAPI 的变化限制在边缘；
- 明确依赖方向和模块所有权；
- 为未来替换 UI、存储或 worker 模式保留空间。

### 放弃的方案

- **模块直接互相导入内部类**：短期代码少，长期耦合和循环依赖严重。
- **共享全局状态**：容易产生竞态，无法隔离实验。
- **全系统统一巨型模型**：减少转换但把不同关注点绑在一起。

### 后果与约束

- adapter 与领域之间需要显式转换代码。
- 公共契约变更必须做版本和兼容评审。
- domain 不得导入第三方基础设施 SDK；任务边界由 Agent Guide 固定。

---

## ADR-009 — 自动驾驶控制意图回写 SUMO，不由 CARLA 反向定真值

- 状态：Superseded by ADR-022
- 日期：2026-07-15

### 背景

多级自动驾驶控制器需要影响车辆行为。如果控制器驱动 CARLA 物理而 SUMO 仍独立推进，同一车辆会出现两个轨迹，且出入 ROI 时无法连续。

### 决策

控制器读取上一帧标准观察，输出 `ControlCommand`，由 SUMO adapter 在下一步前应用速度、加速度或换道意图。SUMO 产生的新状态再同步到 CARLA。CARLA 不将物理结果反写为全局轨迹。

### 选择理由

- 保持 ADR-002 的单一真值；
- ROI 内外行为连续；
- 控制器不依赖仿真 SDK，便于测试和替换；
- 全局指标与展示使用同一结果。

### 放弃的方案

- **控制器直接操作 CARLA**：只影响 ROI 内车辆且形成双真值。
- **控制器直接调用 TraCI**：能工作，但破坏接口边界和统一调度顺序。
- **CARLA 物理结果每帧强制覆盖 SUMO**：可能造成路网/车道状态非法和反馈振荡。

### 后果与约束

- MVP 重点验证交通行为而非高保真车辆动力学闭环。
- 控制命令必须经过边界/NaN 校验和批量应用。
- 若未来需要传感器—规划—控制—动力学闭环，需设计独立模式和真值迁移 ADR。

---

## ADR-010 — PostgreSQL + Parquet + JSON/YAML 分层存储

- 状态：Accepted
- 日期：2026-07-15

### 背景

场景、实验和事件需要事务、关系和查询；车辆轨迹是高频、批量、分析型数据；配置和产物清单需要可移植。单一存储无法同时最优满足这些模式。

### 决策

PostgreSQL 保存关系元数据、状态历史、事件索引、聚合指标和 artifact 元数据；Parquet 保存高频轨迹、道路状态和回放数据；YAML 保存用户场景；JSON 保存解析快照、manifest 和结构化日志。

### 选择理由

- PostgreSQL 提供事务、约束、JSONB 和成熟迁移能力；
- Parquet 列式压缩、分析效率和 Python 工具链适合大规模轨迹；
- YAML/JSON 易审阅、导出和跨工具使用；
- 按访问模式选择存储，避免数据库被每车每 tick 写入淹没。

### 放弃的方案

- **全部 PostgreSQL**：实现统一，但高频轨迹写入和长期容量压力大。
- **全部文件**：事务、并发更新和资源查询困难。
- **专用时序数据库**：可能适合指标，但增加 MVP 部署和运维负担。
- **CSV 作为主轨迹格式**：通用但类型、压缩和查询性能不足；可作为导出格式。

### 后果与约束

- 必须维护 artifact manifest、checksum 和数据库 URI 的一致性。
- Parquet schema 需要版本化，写入需批量并与 tick 解耦。
- PostgreSQL schema 使用显式迁移；不得把运行产物提交到源码仓库。

---

## ADR-011 — PySide6 作为第一阶段 UI，保留 React 替换边界

- 状态：Accepted
- 日期：2026-07-15

### 背景

PRD 指定第一阶段 PySide6、第二阶段 React。MVP 偏本机科研演示，需与 CARLA 原生窗口和 Python 运行环境快速整合；未来又希望 Web 化。

### 决策

v1.0 使用 PySide6 实现四页面桌面 UI。UI 只通过 REST/WebSocket 使用后端能力，不直接导入 Native Traffic Engine、CARLA manager 或数据库。这样第二阶段 React 可复用同一协议。

### 选择理由

- 本机应用、CARLA 窗口和 Python 开发链整合快；
- 与 PRD 交付顺序一致；
- API 边界避免 UI 框架锁死业务逻辑；
- 后续 React 迁移无需重写核心编排。

### 放弃的方案

- **直接 React**：长远适合 Web，但第一阶段本机三维集成和部署工作更多。
- **PySide6 直接调用 Python service**：代码少，但会破坏未来前端替换和进程隔离。
- **CARLA 自带 HUD 作为完整 UI**：难覆盖场景管理、2D、Dashboard 和回放。

### 后果与约束

- UI 需要处理网络断开、重连和 snapshot 恢复，即使后端在本机。
- 共享的只有协议 schema 和生成客户端，不共享业务对象。
- React 迁移应新增 ADR，PySide6 在迁移完成前仍是受支持客户端。

---

## ADR-012 — 回放采用 Snapshot + Delta/Event，而非重跑仿真

- 状态：Accepted
- 日期：2026-07-15

### 背景

回放要求暂停、快进、慢放、逐帧和任意时间跳转。仅保存视频无法查询车辆/指标；重新运行仿真可能受版本、随机性和外部环境影响，且 seek 成本高。

### 决策

运行时周期性记录完整状态 snapshot，并在其间记录有序 vehicle/road delta 和 domain event。回放 seek 时加载目标之前最近 snapshot，再应用 delta 到目标时间。回放不重新运行控制器或仿真器。

### 选择理由

- 对仿真器版本和运行环境不敏感；
- 可精确恢复结构化状态和事件；
- snapshot 控制 seek 延迟，delta 控制存储成本；
- 支持不同播放倍率而不改变历史内容。

### 放弃的方案

- **只录像**：适合展示但不支持数据交互和精确状态恢复。
- **只记录每帧完整快照**：读取简单但空间成本高。
- **保存 seed 后重跑**：不能保证跨版本和外部仿真器完全确定，seek 慢。
- **只记 delta**：从头回放才能 seek，且早期损坏影响全部后续。

### 后果与约束

- snapshot/delta schema、sequence 和 checksum 必须稳定。
- 配置决定 snapshot 间隔，需要在 seek 延迟与空间之间权衡。
- 录像、截图可以是附加 artifact，但不替代结构化回放记录。

---

## ADR-013 — 显式地图配准与集中坐标转换

- 状态：Accepted
- 日期：2026-07-15

### 背景

SUMO 与 CARLA 可能使用不同原点、轴方向、高程和 heading 约定。把偏移、翻转和角度修正散落在同步代码中，会产生难以诊断的车辆漂移和地图错位。

### 决策

每个地图组合提供版本化配准配置。`CoordinateTransformer` 是 SUMO→CARLA 坐标和 heading 转换的唯一实现；启动时用至少三个非共线控制点验证误差，超过阈值拒绝运行三维同步。

### 选择理由

- 地图差异显式、可审计、可测试；
- 转换逻辑与 ROI 生命周期分离；
- 可用控制点快速发现原点、缩放、轴和角度错误；
- 后续支持更多 Town/网络而不修改同步算法。

### 放弃的方案

- **在代码中硬编码 offset**：只适用单地图，易漂移。
- **每个调用处自行转换**：重复且不一致。
- **启动后肉眼调整**：不可复现，无法自动验收。

### 后果与约束

- 地图配准文件是场景启动的必需 artifact。
- 坐标/heading fixture 必须覆盖轴方向和角度 wrap。
- 若需要非刚体或分段道路映射，应新增配准模型 ADR，不在同步器内打补丁。

---

## ADR-014 — 有界队列、可观察降级与差异化故障策略

- 状态：Accepted
- 日期：2026-07-15

### 背景

UI、网络、磁盘和 CARLA 可能慢于 SUMO tick。无界队列会导致内存增长；统一“遇错全停”会降低演示可用性；静默丢帧又会损害科研可信度。

### 决策

所有异步边界使用有界队列并定义优先级。状态变更、错误和领域事件不可静默丢失；车辆实时 delta 可合并到最新状态；轨迹在配置允许时可降采样，但必须记录 `DATA_DEGRADED`。SUMO 断连默认失败，CARLA 可降级，单客户端过慢只断开该客户端。

### 选择理由

- 保护仿真核心免受慢消费者拖累；
- 保持资源使用有界；
- 降级行为可检测、可解释、可审计；
- 根据组件对真值的重要性区别处理。

### 放弃的方案

- **无界队列**：短期不丢数据，长期可能 OOM。
- **所有消息同优先级**：可能为实时车辆帧丢失关键错误事件。
- **任何组件失败都立即终止**：CARLA/UI 故障会不必要地中止有价值的 SUMO 实验。
- **静默抽样**：科研数据完整性不可判断。

### 后果与约束

- 每个队列公开 depth、drop/coalesce 计数和容量指标。
- manifest 标记数据完整性和降级区间。
- 故障矩阵和恢复路径必须有注入测试。

---

## ADR-015 — MVP 采用模块化单体，外部仿真器保持进程边界

- 状态：Accepted
- 日期：2026-07-15

### 背景

系统模块多，但 v1.0 主要在单机运行，初期团队与运维规模有限。过早拆微服务会增加部署、协议、观测和故障面；完全单进程又无法容纳 SUMO/CARLA 的原生服务边界。

### 决策

TrafficVerse 代码库采用清晰依赖方向的模块化单体。API、应用服务、领域和 adapters 可在同一 Python 部署单元内运行；SUMO 和 CARLA 保持外部进程。接口设计允许未来把每个 experiment runtime 提升为 worker。

### 选择理由

- MVP 部署和本地调试简单；
- 事务和调用链清晰；
- 通过 Port/Adapter 保留未来拆分点；
- 外部仿真器仍可独立崩溃/重启和资源隔离。

### 放弃的方案

- **立即微服务化**：对当前并发和组织规模收益不足，复杂度高。
- **所有组件同一进程**：SUMO/CARLA 本身不适合嵌入为普通库。
- **UI 直接编排外部进程**：业务状态分散，难以自动化和替换前端。

### 后果与约束

- 模块化必须由导入规则和契约测试强制，不能演变成无边界“大泥球”。
- MVP 可限制一个并发 RUNNING 实验，但 API/模型必须携带 experiment_id。
- 真正拆 worker 时需新增关于 IPC、调度和容错的 ADR。

---

## ADR-016 — 统一 ID、仿真时间、单位、版本与确定性规则

- 状态：Accepted
- 日期：2026-07-15

### 背景

多仿真器、多存储和实时协议最容易在 ID、时间、角度、单位、顺序和随机性上产生隐蔽不一致。这些错误会直接损害同步、指标和实验复现。

### 决策

采用以下统一规则：

- 资源 ID 使用 UUID v4；车辆主 ID 使用单次实验内稳定的 SUMO 字符串 ID；CARLA actor ID 仅为内部映射。
- 权威时间使用整数 `simulation_time_ms`；墙上时间仅审计且为 UTC ISO 8601。
- SI 单位：m、m/s、m/s²、rad；UI 负责显示转换。
- 每个实验消息使用单调 `sequence`；协议和数据 schema 使用显式 `schema_version`。
- 随机行为由 experiment seed 派生，车辆随机流再由稳定 vehicle_id 派生。
- 同一 tick 的记录顺序由 simulation time、sequence、vehicle_id 明确定义。

### 选择理由

- 避免浮点时间漂移和跨时区混乱；
- 防止 CARLA Actor 重建后身份改变；
- 单位和版本显式，降低跨模块误解；
- 稳定 seed 支持科研复现和确定性测试；
- sequence 支持丢包检测和回放排序。

### 放弃的方案

- **以 CARLA actor ID 为车辆 ID**：Actor 重建后不稳定，ROI 外也不存在。
- **浮点秒作为主时间**：长期累计和相等判断不可靠。
- **各模块使用自己的单位**：转换点分散、容易重复转换。
- **全局共享随机数生成器**：调用顺序变化会改变其他车辆结果。
- **无版本 JSON**：字段演进无法安全协商。

### 后果与约束

- adapter 必须在边界完成单位和 ID 转换。
- 新增可选字段可保持小版本兼容；删除/重命名/语义变化需提升主版本和迁移。
- 回放、API、数据库和 Parquet 必须使用同一时间与 ID 语义。

---

## ADR-017 — MVP 二维地图采用 Leaflet，指标图表采用 Plotly

- 状态：Superseded by ADR-026
- 日期：2026-07-15

### 背景

运行页需要全路网车辆、缩放拖拽、车辆点击、筛选和热力图，以及实时指标图表。PRD 同时提到 Leaflet、MapLibre 和 Plotly，如果不明确 MVP 选择，UI Agent 可能同时引入两个地图渲染栈。

### 决策

v1.0 在 PySide6 的 Web 视图中使用 Leaflet 实现二维地图和覆盖层，使用 Plotly 实现 Dashboard 图表。地图组件只消费标准 world snapshot/delta，不访问 Native Traffic Engine。MapLibre 保留为需要矢量瓦片、地图样式或 GPU 大规模图层时的后续候选，不与 Leaflet 同时作为 MVP 必需依赖。

### 选择理由

- 与 PRD 的 Sprint 5 明确目标一致；
- Leaflet API 简单、插件和覆盖层生态成熟，足够支撑 MVP 交互；
- Plotly 适合 Python/科研场景的交互指标图；
- 单一地图栈降低 PySide6 嵌入、打包和 Agent 集成复杂度。

### 放弃的方案

- **MVP 同时使用 Leaflet 和 MapLibre**：功能重叠，增加包体、桥接和维护成本。
- **只用 Qt Graphics View 自研地图**：本机集成直接，但地图交互、瓦片和后续 Web 复用成本高。
- **CARLA 俯视相机代替二维地图**：无法高效展示全局数千车辆和路网指标。
- **自研图表组件**：没有必要，且增加交互和导出工作量。

### 后果与约束

- UI 必须将高频 delta 批量更新，不能每车每帧重建全部 Leaflet marker。
- 大规模车辆性能达不到目标时，先优化分层、聚合、Canvas/WebGL renderer；若确需 MapLibre，应基于基准测试新增替代 ADR。
- 图表只展示后端权威指标，不在 Plotly/JavaScript 中重新定义业务公式。

---

## ADR-018 — 固定首个可运行环境与版本矩阵

- 状态：Superseded by ADR-024/025
- 日期：2026-07-15

### 背景

CARLA server、Python client、SUMO/TraCI 和地图资产具有强版本关联。若 Agent 各自选择版本，即使接口代码正确，也可能在连接、地图或运行时阶段失败。当前开发工作区是 macOS，但 CARLA 官方预编译运行环境以 Ubuntu/Windows 为主。

### 决策

首个验收环境固定为 Ubuntu 22.04 x86_64、Python 3.10.x、CARLA server/client 0.9.16、SUMO/TraCI/sumolib 1.27.1、PostgreSQL 16.x、NVIDIA RTX 2070 或更高且至少 8 GB VRAM。macOS 可运行 UI、API、文档和无 CARLA 测试，但 CARLA server 运行在上述 Linux 主机。所有 Python patch 依赖由 lockfile 固定。

参考：[CARLA 0.9.16 release](https://github.com/carla-simulator/carla/releases/tag/0.9.16)、[CARLA package requirements](https://carla.readthedocs.io/en/0.9.16/start_quickstart/)、[SUMO downloads](https://sumo.dlr.de/docs/Downloads.php)。

### 选择理由

- Ubuntu 22.04、Python 3.10 位于 CARLA 0.9.16 官方支持范围；
- 固定发行版比 nightly build 更可复现；
- 将 CARLA 放在 GPU Linux 主机上可让 macOS 开发机继续作为控制端；
- 版本握手能在启动阶段而非长时间运行后暴露不兼容。

### 放弃的方案

- **每个 Agent 使用本机最新版**：不可复现且容易混用 client/server。
- **在 macOS 直接运行 CARLA server**：不作为官方预编译基线，风险过高。
- **一开始容器化全部 GUI/GPU 组件**：增加首轮构建复杂度，延后评估。

### 后果与约束

- `configs/runtime-baseline.yaml` 是启动必需文件；不匹配时 readiness 失败。
- CARLA Python client 必须与 server 完全同版；SUMO、TraCI、sumolib 必须同版。
- 升级任一核心组件必须先复制基准场景完成兼容验证，再新增 ADR。

---

## ADR-019 — 固定 Town04 同源地图资产并由 SUMO 主控信号灯

- 状态：Superseded by ADR-022
- 日期：2026-07-15

### 背景

SUMO 与 CARLA 的道路、坐标、车道、车型和信号灯若来自不同版本或不同转换过程，会导致车辆漂移、Actor 无法生成和路口灯色不一致。现有设计虽指定 SUMO Truth Source，但没有规定地图资产生产线和信号灯 binding。

### 决策

Core Run 只支持 CARLA 0.9.16 Town04。SUMO 网络从同一 Town04 OpenDRIVE 使用 CARLA co-simulation 工具生成，启用 `--guess-tls`；地图、route、vtype、配准、信号 mapping 和 GeoJSON 由一个带 SHA-256 的 manifest 统一管理。SUMO 是信号灯相位主控，TrafficVerse 每 tick 在 CARLA tick 前批量写入灯色，CARLA 不自主推进信号灯。

参考：[CARLA SUMO co-simulation](https://carla.readthedocs.io/en/0.9.12/adv_sumo/)。

### 选择理由

- 使用同一 OpenDRIVE 消除大部分手工道路对齐风险；
- 官方工具已处理 CARLA/SUMO vtype 和网络转换基础语义；
- 单一信号灯权威与 ADR-002 一致；
- manifest 和严格 binding 让 Agent 能自动校验而不是运行时猜测。

### 放弃的方案

- **手工绘制独立 SUMO Town04**：易产生 lane 和 signal 偏差。
- **CARLA 主控信号灯**：破坏 SUMO 全局真值和二维统计。
- **运行时按空间最近自动匹配信号灯**：结果不稳定，错误难以审计。
- **第一轮同时支持多地图**：扩大资产和验收面，不影响核心闭环证明。

### 后果与约束

- `strict_signal_mapping=true`；缺失或重复 binding 时实验不得 READY。
- 自定义地图、多地图和 lane-specific 复杂相位进入 Product Gate 之后。
- 地图升级需要重新生成全部派生资产和 checksum，不允许只替换单个文件。

---

## ADR-020 — MVP 采用 Leaflet 平面坐标与 JSON JPEG 相机帧

- 状态：Superseded by ADR-025
- 日期：2026-07-15

### 背景

二维地图需要明确坐标系，三维窗口需要明确进程间呈现方式。嵌入 CARLA 原生窗口跨平台脆弱；WebRTC/二进制视频效率高但增加编解码、信令和部署复杂度。

### 决策

二维使用 Leaflet `CRS.Simple` 加载 Native Traffic Engine 平面坐标的静态 `network.geojson`，车辆使用同一平面坐标更新。三维使用 CARLA RGB camera，默认 960×540、10 FPS、JPEG quality 75，通过现有 WebSocket envelope 的 `camera.frame` 以 base64 JSON 发送；服务端和客户端都只保留最新帧。

### 选择理由

- 不需要把本地原生路网坐标伪装成经纬度；
- 相机流可跨主机工作，适配 macOS UI + Linux CARLA 部署；
- JSON 延续 PRD 和现有协议，Agent 实现成本最低；
- 有界 latest-frame 队列避免视频拖慢仿真。

### 放弃的方案

- **嵌 CARLA 原生窗口**：跨操作系统和远程部署不稳定。
- **base64 之前先实现 WebRTC**：更高效但不影响基本功能。
- **CARLA spectator 截屏**：缺少可靠 frame/time 元数据。
- **Leaflet 经纬度 CRS**：SUMO Town04 是局部平面坐标，无此必要。

### 后果与约束

- base64 带宽开销可以接受于单客户端 Core Run，但不能据此宣称生产视频性能。
- `CameraFrame` 必须携带 CARLA frame 和仿真时间；旧帧不得伪标当前时间。
- 二进制 WebSocket、MJPEG、WebRTC、高分辨率和多订阅者均为后续优化。

---

## ADR-021 — 先通过 Core Run Gate，再实现产品与优化能力

- 状态：Superseded by ADR-024/025
- 日期：2026-07-15

### 背景

原 10 个任务同时覆盖仿真、数据库、控制器、指标、回放和完整 UI。让 Agent 一次实现全部能力会推迟最关键的 SUMO↔CARLA 垂直闭环，也会把算法和性能优化问题混入基础集成。

### 决策

第一里程碑只验收固定 Town04 上的 50 辆 SUMO 全局二维、至少 10 个 ROI CARLA Actor、信号灯同步、RGB 实时画面和生命周期控制。核心任务顺序为 `T01 → T02/T03 → T05 → T07 → T09-live → T10-live`。数据库场景管理、L2–L4、指标回放、3D replay、2,500 辆性能和高级 UI 在 Core Run 后继续。

### 选择理由

- 最早暴露最危险的环境、地图、时间和坐标问题；
- 每一阶段都有可见且可自动验收的结果；
- 避免用大量 mock/业务功能掩盖真实共仿真尚未跑通；
- 延期能力不影响证明整体架构可行。

### 放弃的方案

- **严格按编号 T01–T10 全部完成后集成**：真实风险发现过晚。
- **先做完整 UI 和数据库**：不能证明仿真核心可运行。
- **第一轮直接以 2,500/10,000 辆为门槛**：把容量优化与正确性混在一起。

### 后果与约束

- HUMAN/SUMO 原生控制足以通过 Core Run，T05 不再硬依赖 T06。
- T09/T10 必须支持 live 子集先行，不能等待 Replay/Dashboard。
- Core Run 通过不等于 PRD 全部完成；Product Gate 仍需完成剩余任务。

---

## ADR-022 — 自研 Native Traffic Engine 替代 SUMO，MVP 只实现基础交通能力

- 状态：Superseded by ADR-024
- 日期：2026-07-15
- 替代：ADR-001、ADR-002、ADR-009、ADR-019
- 同时替代：ADR-013、ADR-014、ADR-015、ADR-016、ADR-018、ADR-020、ADR-021 中所有以 SUMO、TraCI、SUMO 坐标或 SUMO 资产为前提的条款；其余原则继续有效

### 背景

产品方向调整为自主实现全局二维交通仿真，避免核心交通能力依赖外部交通流仿真器。MVP 仍需证明全局二维交通、交通信号、车辆控制、ROI 与 CARLA 局部三维镜像可以形成完整演示闭环，但不要求复刻成熟交通仿真器的全部模型和工具链。

旧 T02 已实现的 SUMO/TraCI 代码和资产是历史实现，不再是目标架构。它们在迁移任务完成前可以留在仓库用于回归参考，但不得成为新代码、MVP 运行或验收的依赖。

### 决策

TrafficVerse 在仓库内实现 `Native Traffic Engine`，作为车辆存在性、路线、车道、位置、速度、加速度、动作和交通信号灯的唯一真值源。CARLA 继续作为 ROI 内三维镜像，关闭镜像车辆 autopilot，不反向改写交通真值。

MVP 固定范围：

1. Map Compiler 只支持首个验收地图所需的 OpenDRIVE 子集，生成 `network.json`、`network.geojson`、`routes.yaml`、`signals.yaml`、`registration.yaml` 和 `manifest.yaml`；
2. Native Traffic Engine 支持 50 ms 固定步长、车辆生成/到达、固定路线、最短路预计算、自由行驶、基础跟驰、红灯停车、固定周期信号和受控相邻车道换道；
3. 所有车辆读取同一上一帧快照，先计算 proposed state，再进行安全检查和原子提交，保证更新顺序无关；
4. `TrafficEnginePort`、`TrafficSnapshot` 和 `TrafficEngineConfig` 采用技术中性命名；
5. Map Compiler 和 Native Traffic Engine 必须在 macOS arm64 上独立运行；CARLA 三维验收仍可在受支持的 Linux GPU 主机进行；
6. 无 CARLA 时允许完整二维运行；Native Traffic Engine 的不可恢复状态错误使实验失败。

### MVP 明确延期

- 多格式地图导入和地图编辑器；
- 动态交通分配、用户均衡和动态改道；
- 成熟随机驾驶人模型、连续横向动力学和复杂无信号路口 gap acceptance；
- 行人、非机动车、公共交通、排放和路侧检测器；
- 2,500 辆以上的容量承诺和多机分布式执行。

### 选择理由

- 核心交通状态、行为和接口由项目自行控制，便于后续定制混合自动驾驶研究；
- 原生引擎与 API/UI 同仓库、同语言，macOS 开发和二维演示不依赖外部仿真进程；
- 通过严格 MVP 边界，将问题约束为可演示的地图、信号、跟驰和控制闭环；
- 继续保留单一真值、固定步长、ROI 滞回和 CARLA 镜像原则，整体架构无需推翻。

### 放弃的方案

- **继续使用 SUMO 作为默认引擎**：交付快，但不满足核心交通能力自主实现的新产品定义。
- **双引擎长期并存**：增加契约兼容、结果解释和双份验收成本；旧实现只作为迁移参考。
- **第一阶段追求成熟仿真器等价**：地图、换道、路口和模型校准范围过大，不符合 MVP。
- **CARLA Traffic Manager 作为全局真值**：无法满足 macOS 独立二维运行，也会破坏全局轻量交通与局部三维的职责分工。

### 后果与迁移约束

- 公共 `SumoPort`、`SumoConfig`、`SumoSnapshot` 和 `SimulationFrame.sumo` 必须迁移为中性命名；这是协议主版本变更；
- `configs/maps/town04/` 中的 SUMO XML 资产由原生资产替代，运行配置不得再引用 `.sumocfg`；
- `pyproject.toml`、runtime baseline、doctor、CLI、测试 marker 和 README 中的 SUMO 依赖必须在实现任务中移除；
- T02 重新打开并定义为 Native Traffic Engine MVP；旧 T02 的 COMPLETE 仅作为历史证据，不代表新 T02 完成；
- 迁移应先冻结 `traffic-network/1.0` schema 和新 Port，再实现 Map Compiler/Engine，最后移除旧代码，避免下游建立在过渡命名上；
- 在验证前不得宣称交通模型达到现实标定精度或 2,500 辆容量。

---

## ADR-023 — macOS 控制端使用远程 CARLA Simulation Runtime

- 状态：Superseded by ADR-024/025
- 日期：2026-07-16
- 澄清：ADR-015、ADR-018、ADR-020、ADR-022 的 CARLA 部署边界

### 背景

开发与控制端为 macOS arm64，而 CARLA 0.9.16 官方 Python client 发行包只提供 Linux x86_64
和 Windows amd64 构建。即使 CARLA Server 位于远程 Linux 主机，macOS 也不能以官方 SDK
作为可靠的直接 RPC client。若让 macOS 在每个 50 ms tick 上跨公网调用 CARLA，还会把网络抖动
引入唯一仿真时钟和相机数据链路。

### 决策

CARLA 0.9.16 Server 与使用官方 CARLA Python SDK 的 Simulation Runtime 固定部署在远程
Ubuntu 22.04 x86_64 GPU 主机，或位于同一低延迟私有网络。Native Traffic Engine、Simulation
Manager、ROI Synchronizer 和 CarlaAdapter 在远程 Runtime 内共同保持单一 tick 顺序。macOS
运行开发工具和 UI，并通过 TrafficVerse REST/WebSocket 访问远程 Runtime，不直接安装 CARLA
SDK，也不直接推进 CARLA world。

部署配置只保存非敏感的 host、port、timeout 和版本；凭证、VPN 或隧道配置不进入场景 YAML。
CARLA RPC 默认端口 2000/2001 只向受控网络开放，产品用户入口只暴露 TrafficVerse API。

### 选择理由

- 保持官方 CARLA 0.9.16 client/server 完全同版；
- 避免 macOS arm64 缺少官方 client wheel 的兼容风险；
- 将逐 tick Actor、信号和相机操作留在低延迟边界，避免公网抖动破坏固定步长；
- macOS UI 仍可获得全局二维状态与 CARLA JPEG 帧，且无需 GPU 或 CARLA SDK。

### 放弃的方案

- **macOS 直接连接裸 CARLA RPC**：缺少受支持的 0.9.16 macOS arm64 Python client。
- **每个 tick 通过公网调用 CARLA**：延迟和断线会进入核心同步循环。
- **在 macOS 非官方编译 CARLA client/server**：增加不可复现构建，不作为 MVP 基线。
- **CARLA Traffic Manager 接管交通真值**：违反 ADR-022 的单一真值原则。

### 后果与约束

- T03 Adapter 在 macOS 以 mock/runtime contract 测试，真实 smoke 在远程 Linux Runtime 执行；
- 远程断线按 ADR-014 降级三维，Native Traffic Engine 二维真值继续运行；
- 只有远程 Simulation Manager 可调用 `world.tick()`；UI、API handler 和相机 callback 均无此权限；
- T09/T10 必须支持配置远程 API 地址和显示 CARLA 健康，不向浏览器暴露 CARLA RPC；
- 若后续需要拆分独立 CARLA Bridge，必须先定义内部协议并新增 ADR，不得把第三方 SDK 对象跨网传输。

---

## ADR-024 — 恢复 SUMO 为全局交通真值并由 TrafficVerse 统一联仿

- 状态：Accepted
- 日期：2026-07-17
- 替代：ADR-022
- 同时替代：ADR-018 和 ADR-021 的旧运行环境与旧 Core Run 呈现基线；保留固定版本、先验收主链的原则
- 恢复并更新：ADR-001、ADR-002、ADR-009、ADR-019 中关于 SUMO 真值、控制回写和信号灯主控的方向
- 迁移计划：[SUMO_MIGRATION_PLAN.md](./SUMO_MIGRATION_PLAN.md)

### 背景

Native Traffic Engine MVP 已证明技术中性 Port、二维可视化、ROI 和 CARLA adapter 的模块边界，
但继续自研路由、跟驰、换道、信号和交通需求会把项目资源投入到复刻成熟交通仿真器，且难以在
MVP 阶段获得足够的模型验证。产品方向重新确定为使用 SUMO 承担真实交通仿真，PySide6 二维
页面只负责展示，CARLA 只负责 ROI 三维镜像。

用户已在本机准备 SUMO、PySide6 和 CARLA，目标版本继续固定 Python 3.10、SUMO 1.27.1
和 CARLA 0.9.16；目标端点固定为 SUMO TraCI
`127.0.0.1:8813` 与 CARLA RPC `127.0.0.1:2000`。CARLA 官方 SUMO co-simulation 给出了
同源地图转换、50 ms 固定步长、车辆同步和 `tls-manager` 的参考机制；TrafficVerse 需要在现有
`SimulationManager`、Port、ROI 和 API 框架内吸收这些机制，而不是并行运行另一个同步主循环。

### 决策

SUMO 是生产运行中车辆存在性、路线、车道、位置、速度、加速度、跟驰、换道、到达和交通信号灯
的唯一真值源。PySide6、CARLA、指标和记录器只消费标准化后的 SUMO 状态。保留技术中性的
`TrafficEnginePort`、`SumoConfig` 和 `TrafficSnapshot`，由
`SumoTrafficEngineAdapter` 作为生产实现；技术中性命名不表示支持双生产引擎。

`SimulationManager` 是唯一推进者，每 tick 的固定顺序为：

1. 读取并验证控制命令；
2. 通过 TraCI 批量应用命令；
3. 恰好调用一次 `traci.simulationStep()`；
4. 采集 departed、arrived、车辆和 traffic-light subscription 结果，生成同一仿真时间的
   `TrafficSnapshot`；
5. 计算 ROI create/update/destroy 和 SUMO→CARLA 坐标转换；
6. 批量更新 CARLA Actor、车辆灯光和信号灯；
7. 恰好调用一次 CARLA `world.tick()`；
8. 发布二维状态、指标和健康。

固定步长为 50 ms。SUMO、CARLA 和 TrafficVerse 的 step 配置必须相同。SUMO 主控信号灯，
配置固定 `tls_manager: sumo`。控制器产生意图并通过 SUMO adapter 应用，禁止直接操作 UI marker、
Native 引擎状态或 CARLA Actor 形成第二条运动链。

Town04 Core Run 使用 CARLA 0.9.16 同源 OpenDRIVE，经官方 CARLA/SUMO 工具
`netconvert_carla.py --guess-tls` 生成 SUMO 网络。地图 manifest 同时追踪 XODR、`.net.xml`、
`.sumocfg`、route、vtype、GeoJSON、配准和严格信号灯 mapping。

本地基线连接外部启动的 SUMO：

```bash
sumo -c map.sumocfg --remote-port 8813
```

如需人工观察，可以单独使用 `sumo-gui --start`，但 TrafficVerse 不嵌入、控制或依赖
SUMO GUI。默认只有 TrafficVerse 一个 TraCI client。
CARLA endpoint 固定为 `127.0.0.1:2000`。官方 `run_synchronization.py` 只作为设计和验收参考，
不得与 TrafficVerse 同时推进相同实例。

### 选择理由

- SUMO 已提供经过广泛使用的路由、跟驰、换道、信号灯和 TraCI 控制能力；
- 重新采用成熟仿真器能把开发重点放回联仿、控制、可视化和实验能力；
- 现有技术中性 Port、领域快照、ROI 滞回、坐标转换和 API 可以复用，迁移无需推翻全部框架；
- 单一 SUMO 真值使二维显示、三维镜像、指标和回放具有一致来源；
- 官方 co-simulation 流程降低 Town04 地图和信号灯对齐风险。

### 放弃的方案

- **继续扩展 Native Traffic Engine**：自主可控，但 MVP 成本和交通模型验证风险过高。
- **SUMO 与 Native 长期双引擎**：会形成结果解释、命令裁决和验收双份语义。
- **CARLA Traffic Manager 作为真值**：无法覆盖 ROI 外全路网，且破坏二维交通连续性。
- **直接运行官方同步脚本作为第二主循环**：会与现有 SimulationManager 争用 step/tick 和生命周期。
- **UI 直接连接 TraCI**：把真值生命周期分散到展示层，破坏 API 和回放边界。

### 后果与迁移约束

- ADR-022 不再指导新实现；Native Traffic Engine 在真实 Core Run 通过前可作为回归参考，之后从
  生产装配、配置和运行依赖移除；
- 恢复 SUMO/TraCI/sumolib 的可选集成依赖、doctor 检查、adapter、配置、marker 和真实集成测试；
- `traffic-network/1.0` 和 `network.geojson` 只能作为展示/查找资产，不参与交通推进；
- SUMO 断连属于真值丢失，实验默认 FAILED；CARLA 镜像失败不能改变 SUMO 状态；
- 所有公共快照必须能追溯到具体 SUMO simulation time 和 sequence；UI 不得补算权威位置；
- `SYSTEM_DESIGN.md`、Agent Guide、AGENTS、README、配置和协议必须在代码迁移前同步；
- 迁移按 [SUMO_MIGRATION_PLAN.md](./SUMO_MIGRATION_PLAN.md) 执行，未完成真实本地验收前不得宣称
  新架构已经可运行。

参考：[CARLA SUMO co-simulation](https://carla.readthedocs.io/en/latest/adv_sumo/)、
[SUMO TraCI](https://sumo.dlr.de/userdoc/TraCI/)。

---

## ADR-025 — PySide6 托管本机 CARLA 原生窗口，不传输 RGB 画面

- 状态：Accepted
- 日期：2026-07-17
- 替代：ADR-020 中 JSON JPEG 相机帧的三维呈现方案
- 同时替代：ADR-018、ADR-021 和 ADR-023 中以远程无头 Runtime、RGB 帧作为 CARLA 呈现的产品基线
- 保留：ADR-020 的 Leaflet `CRS.Simple` 二维地图选择

### 背景

现有三维链路由 CARLA RGB sensor 产生图像，经 JPEG/base64 和 WebSocket `camera.frame` 传到
PySide6。该方案支持跨主机，但增加传感器、编码、网络、队列、解码、帧时间和降级处理，并且
不符合当前要求：右侧区域应直接集成 CARLA 页面，而不是远程传输 RGB 图像。

当前 CARLA RPC 运行在本机 `127.0.0.1:2000`，因此可以探索将 CARLA 顶层 native window
作为 foreign window 托管到 Qt。Qt 提供 `QWindow.fromWinId()` 包装 native window，并通过
`QWidget.createWindowContainer()` 嵌入 QWidget 布局；但 Qt 同时明确该能力高度依赖平台，
foreign window 主要支持 reparent，焦点、层叠和性能也有平台限制。

### 决策

MVP 三维视图使用本机 CARLA 原生窗口。PySide6 新增 `CarlaNativeWindowHost`，从显式配置的
native window ID 或受测试的平台 locator 获得句柄，调用 `QWindow.fromWinId()`，再通过
`QWidget.createWindowContainer()` 放入运行页右侧。

以下约束为强制项：

1. CARLA、PySide6 和被托管窗口必须在同一主机、同一用户、同一图形桌面会话；
2. CARLA 必须 windowed 运行；`-RenderOffScreen` 或 no-rendering mode 不满足验收；
3. 窗口容器只管理 attach、resize、focus、detach 和 health，不拥有仿真状态，不调用 TraCI，
   不调用 CARLA `world.tick()`；
4. 正式运行优先使用 `TRAFFICVERSE_CARLA_WINDOW_ID` 等显式句柄配置；平台 locator 必须校验
   进程身份和句柄有效性，不能用模糊标题猜测作为稳定契约；
5. Core Run 不创建用于 UI 的 RGB sensor，不发布 `camera.frame`，不编码/解码 JPEG/base64；
6. 目标桌面平台先执行阻断性原型 Gate，验证跨进程窗口句柄、原生窗口边界、resize、
   focus 和清理；
7. 若 `QWindow.fromWinId()` 返回空或窗口无法稳定 reparent，readiness 返回
   `CARLA_WINDOW_EMBED_UNSUPPORTED` 并停止该验收，不静默回退 RGB。

### 选择理由

- 直接满足“不通过 RGB 传输，集成 CARLA 页面”的产品要求；
- 消除 UI 专用相机 Actor、JPEG/base64 开销、最新帧队列和图像解码故障；
- 使用 CARLA 自身渲染窗口保留其原生画面和交互表现；
- Qt 已提供 foreign-window 包装和 QWidget 容器 API，适合先做小型可行性验证。

### 放弃的方案

- **继续 WebSocket JPEG/base64**：跨主机兼容，但违反当前产品要求。
- **WebRTC/MJPEG/共享内存视频**：可优化视频传输，但本质仍是传输 RGB 图像。
- **截取 CARLA 窗口再绘制到 Qt**：仍是图像复制链路，且失去原生窗口语义。
- **UI 内重新实现 CARLA 3D 渲染**：成本和维护风险远超 MVP。
- **失败时静默打开冻结帧或 RGB fallback**：会掩盖不满足验收的事实。

### 后果与迁移约束

- 当前 RenderOffScreen CARLA 必须重启为 windowed；off-screen 模式没有可托管的显示窗口；
- 本方案不支持远程无头 CARLA 直接嵌入本机 UI；如恢复跨主机部署，必须重新选择远程呈现协议并
  新增 ADR；
- 目标桌面平台的 foreign window 可行性是架构阻断项，必须通过实机 Gate；
- `camera.frame` schema、生产者、队列、sensor、decoder、viewmodel 和相关配置在消费者切换后删除；
- 原生窗口异常属于三维组件健康错误；不得影响 SUMO 真值，但 `carla.mode=required` 的 Core Run
  readiness 必须失败；
- Qt 容器的 stacking、focus、键盘事件和大量 native child 性能限制必须纳入原型测试；
- UI 仍只通过 TrafficVerse REST/WebSocket 进行业务控制，窗口嵌入不构成 UI 直连后端 SDK 的例外。

参考：[QWindow.fromWinId](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QWindow.html)、
[QWidget.createWindowContainer](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QWidget.html)、
[CARLA rendering options](https://carla.readthedocs.io/en/0.9.12/adv_rendering_options/)。

## ADR-026 — 左侧地图迁移到 MapLibre + deck.gl

- 状态：Accepted
- 日期：2026-07-17
- 替代：ADR-017 中 Leaflet 作为左侧地图技术栈的决定
- 详细设计：[MAPLIBRE_DECKGL_ARCHITECTURE.md](./MAPLIBRE_DECKGL_ARCHITECTURE.md)

### 背景

当前 Leaflet `CRS.Simple` 已满足 Town04 平面路网和少量车辆的二维展示，但后续需要在同一左侧地图
中切换二维和三维、使用 GPU 批量渲染车辆、加载 glTF 模型并扩展热力图、轨迹和大型三维场景。
MapLibre GL JS 提供 WebGL 地图相机与 style layer，deck.gl 提供面向大量数据和三维 scenegraph 的
GPU layer，并能通过 `MapboxOverlay` 与 MapLibre 共享相机和 WebGL2 context。

UI 当前运行在 PySide6 6.11.1 `QWebEngineView` 中。Qt WebEngine 使用 Chromium，因此首版应走标准
WebGL2 路径，不为尚未复现的 GPU、worker、CSP 或 driver 问题增加大规模兼容与诊断代码。

### 提议决策

左侧地图改用 MapLibre GL JS + deck.gl：

1. MapLibre 负责地图相机、交互、背景 style 和可选底图；
2. deck.gl 负责 TrafficVerse 路网、车辆、信号灯、选择、分析图层和三维模型；
3. 使用 `MapboxOverlay({interleaved: true})`，前置条件为目标 Qt WebEngine 支持 WebGL2；
4. 二维和三维共用同一 `WorldState`，切换只改变 camera 与 layer，不建立第二份车辆状态；
5. deck.gl 使用 meter-offset coordinate system 和展示专用 registration，继续消费 SUMO 局部米制
   位置；当前局部 `network.geojson` 不直接作为 WGS84 MapLibre source；
6. 右侧 CARLA 原生窗口和 ADR-025 保持不变，左侧三维不是 CARLA 画面的替代品；
7. 第一版继续使用 `QUrl.fromLocalFile()`、本地 JS bundle 和现有 Qt bridge。只处理 MapLibre/deck
   初始化失败与 GLB load error；其他兼容代码必须由可复现故障或性能数据驱动；
8. 迁移期间 Leaflet 只作为显式开发 fallback，新方案通过 Gate 后删除，产品不长期维护双地图栈。

Web 构建基线固定为服务器现有 Node.js 16.20.2 和 npm 8.19.4。MapLibre、deck.gl 和构建工具必须
选择兼容该基线的固定版本并提交 npm lockfile；运行时使用本地 bundle，不依赖 Node.js、CDN 或公网。

三维格式采用双导出而非强行统一运行时文件：

- OpenDRIVE `.xodr` 继续作为道路拓扑和坐标同源输入；
- DCC 源资产导出 `.fbx` 给 CARLA 0.9.16/Unreal 导入链；
- 同一源资产导出 glTF 2.0 Binary `.glb` 给 deck.gl `ScenegraphLayer`；
- 大型 Web 场景按需生成 3D Tiles；
- 资产 manifest 统一 `asset_id`、米制单位、坐标轴、pivot、LOD、许可证、生成命令和 checksum。

### 选择理由

- MapLibre 提供二维/三维共用的相机、倾斜和 WebGL 地图能力；
- deck.gl 更适合高频车辆的批量 GPU layer 和重复 GLB 实例；
- meter-offset 可以保持 Town04 局部米制数据，避免每 tick 转换全部车辆到经纬度；
- 双导出尊重 CARLA 的 FBX/Unreal 边界和 Web 的 glTF 生态；
- 以真实问题驱动兼容处理，避免在 Chromium 正常路径前增加无效检查和分支。

### 放弃的方案

- **继续扩展 Leaflet 到三维**：适合简单二维，但不是目标 GPU 三维栈；
- **只使用 MapLibre style layer**：可以画道路和 extrusion，但高频车辆和 GLB 实例扩展不如 deck.gl；
- **只使用 deck.gl，不使用 MapLibre**：可使用独立 view，但会重复地图相机、控件和未来底图能力；
- **让 MapLibre/deck.gl 直接读取 CARLA cooked assets**：Web 运行时无法使用 Unreal cooked assets；
- **要求 GLB 同时作为 CARLA 输入**：CARLA 0.9.16 官方地图导入链要求 XODR + FBX；
- **预先实现完整兼容诊断框架**：没有故障证据，增加代码、状态和测试成本。

### 后果与实施 Gate

- 必须先在目标 PySide6/QWebEngine 中加载本地 MapLibre、deck overlay 和仓库 Box GLB；
- 必须与 windowed CARLA 同时运行，完成 resize、DPI、焦点和 10 分钟稳定性 Gate；
- 必须证明二维行为与当前 Leaflet 等价，且位置仍只来自同 tick SUMO snapshot；
- 允许展示层在 sequence 连续的相邻 SUMO snapshot 端点之间插值，但不得外推、写回权威状态或在
  sequence gap 后继续动画；
- 实时地图可以使用2帧已接收 snapshot 缓冲吸收到达抖动；该缓冲只增加展示延迟，不改变消息、
  指标或控制使用的权威时间；
- 必须用控制点验证 Web meter-offset 配准误差不超过 0.5 m；
- 必须证明至少 50 辆三维实例在目标机器按当前 20 Hz snapshot 稳定显示；
- 同步 PRD、System Design、Agent Guide、UI 测试、依赖 lockfile 和离线构建流程；
- 二维等价 Gate 完成前不删除 Leaflet 文件；完成后不得长期保留双生产地图栈。

---

## ADR-027 — 原生 SUMO 二维场景包自动发现并使用主机 SUMO 托管运行

- 状态：Accepted
- 日期：2026-07-30
- 扩展：ADR-024 的 SUMO 真值和唯一推进者约束
- 保留：Town04 Core Run 的 SUMO 1.27.1、50 ms、同源资产和严格 CARLA 信号映射

### 背景

TrafficVerse 已有的 Core Run 装配只注册 Town04 一个 manifest，忽略实验请求中的实际场景 ID，
并把任何地图选择重写为 `map.sumocfg`。即使 `carla.mode=disabled`，运行工厂仍强制读取
`network.json`、`routes.yaml`、`signals.yaml` 和 `registration.yaml`。这使已经能够由
`sumo -c <scene>.sumocfg` 独立运行的原生 SUMO 场景无法直接接入二维页面。

科研用户通常拥有大量以目录为单位的完整 SUMO 场景，每个目录包含 `.sumocfg`、`.net.xml`、
route、additional、GUI settings 和其他被配置引用的输入。此类场景不需要 CARLA，也不应被要求
补造 OpenDRIVE 或 Town04 专属 manifest。不同场景还可能由主机上不同的 SUMO 稳定版本产生，并
使用各自的 begin、end 和 step-length。

### 决策

TrafficVerse 增加“原生 SUMO 二维包”运行模式，与严格 Town04 Core Run 并存：

1. `configs/maps/<package>/` 下每个顶层 `.sumocfg` 都是一个可发现的运行条目；目录只有一个配置
   时使用目录名作为 ID，多个配置时使用 `<directory>-<config-stem>`；
2. 解析 `.sumocfg` 的 `net-file`、route/additional 和其他显式 input file，所有路径必须位于
   `configs/maps` 允许根目录内；缺失或越界的配置作为不可运行条目报告，不阻断其他目录；
3. 纯二维包不要求 `.xodr`、Town04 `manifest.yaml`、`network.json`、CARLA registration 或
   OpenDRIVE signal binding；MapLibre/deck.gl 展示几何直接由同一 `.net.xml` 生成；
4. 通用信号灯使用稳定 ID `sumo-tls:<tls-id>:<controlled-link-index>`，静态 Point 来自受控进口
   车道停止端，实时颜色来自同一 TraCI link state；存在 `linkSignalID` 时继续保留 Town04 的
   OpenDRIVE 严格 ID；
5. TrafficVerse 使用 PATH 中的 `sumo` 可执行文件托管本地进程，并优先加载该可执行文件同发行版
   的 TraCI tools。`expected_version` 为空时只记录实际版本，不按白名单拒绝；显式配置版本时仍
   严格校验；
6. begin、end 和 step-length 来自 `.sumocfg`。纯二维模式允许场景自己的整数毫秒步长；Town04
   Core Run 仍固定 50 ms，只有 `SimulationManager` 调用 `simulationStep()`；
7. 每次实验把场景输入复制到 `artifacts/sumo/<experiment-id>/package/` 的运行副本，保持原相对
   路径，并把 SUMO 输出留在该 artifact 树；运行不得改写 `configs/maps` 中的源场景；
8. 原生 SUMO 包自动设置 `carla.mode=disabled`，不构造 ROI、registration 或 CARLA signal planner；
   以后若某个任意 SUMO 包需要 CARLA 镜像，必须另行提供经过验证的配准和严格信号 binding。
9. 桌面端二维场景选择器只展示 `kind=sumo` 的自动发现条目。Town04 manifest 继续属于独立 Core
   Run 与资产目录，不作为第二种二维运行入口；旧 `NativeTrafficEngine` 源码不再保留。

### 选择理由

- `.sumocfg` 已是 SUMO 对运行输入、时间和输出的权威配置，额外复制一份 TrafficVerse 场景 YAML
  会引入漂移和批量维护成本；
- 使用主机 `sumo` 与其同发行版 TraCI tools，能兼容用户现有场景环境，同时保留显式版本锁定能力；
- 从同一 `.net.xml` 生成静态几何，保证道路与实时车辆坐标同源，不建立第二交通真值；
- 运行副本隔离输出，既保持原配置的相对路径语义，也保护版本化源资产；
- 纯二维分支使用 no-op ROI/signal planner，避免以虚假的 Town04/CARLA 文件满足构造参数。

### 放弃的方案

- **为每个 SUMO 目录手写完整 TrafficVerse YAML/manifest**：可显式控制，但大量重复字段容易漂移；
- **继续要求所有场景从 `.xodr` 生成**：适合 SUMO/CARLA 同源联仿，不适合已经完成的纯 SUMO 场景；
- **UI 直接启动或推进 TraCI**：会破坏 API 边界和 `SimulationManager` 唯一时钟；
- **直接在源目录运行并写 outputs**：会污染配置资产并使实验结果互相覆盖；
- **宣称兼容任意历史 SUMO 协议**：不现实；实际二进制或 TraCI 协议不兼容时仍以稳定错误失败。

### 后果与约束

- 默认同一进程仍只允许一个运行实验，并使用一个 TraCI client；托管端口冲突会在 prepare 阶段失败；
- 自动发现只扫描允许根目录，不接受 API 传入任意本机路径或任意 shell 命令；
- `.sumocfg` 中输出路径必须是包内安全相对路径；绝对路径或 `..` 输出被拒绝；
- 纯二维场景的 CARLA 状态为 disabled，不应把它显示成三维故障；
- 新增真实集成测试必须至少覆盖一个非 Town04、无 `linkSignalID`、且主机 SUMO 版本不同于 Core
  Run 锁定版本的场景。

---

## ADR-028 — 仿真配置快照、精确交通需求和正式/测试运行目录

- 状态：Accepted
- 日期：2026-08-11
- 修订：ADR-027 第 7 条的通用 SUMO 运行副本目录
- 保留：SUMO 交通真值、`SimulationManager` 唯一推进者、原始场景包不可变

### 背景

仿真配置页允许用户编辑场景名称、地图、仿真时长和 L0–L5 车辆数。旧流程仅把地图 ID
传入实验创建接口，运行时仍使用场景包原始 route 和 end time，因此页面上的交通需求和
时长不是真正可重现的运行输入。同时，开发者需要将快速验证与正式历史仿真分开。

### 决策

1. “保存配置”在 `configs/configs/yyyy-mm-dd-hh-mm-ss/` 创建不可变快照，复制选中的
   SUMO 场景包，不修改 `configs/maps` 源文件；
2. 快照根目录的 `configuration.json` 单独记录工作区/场景 ID、场景名称与描述、地图
   ID/名称、仿真时长、已配置的 L0–L5 精确车辆数和快照内 `.sumocfg` 相对路径；
3. 页面交通需求非空时，保留原 route 文件中的命名 `route` 和 L0–L5 `vType` 定义；缺失的
   已选等级 `vType` 使用稳定默认值补齐。删除原有 `flow/vehicle` 需求，按页面数量生成显式
   `vehicle`，车辆 ID 稳定且发车时刻在配置时长内均匀分布。页面交通需求为空时，不生成
   route 文件并原样保留场景包内已有 `.rou.xml`；
4. 快照内 `.sumocfg` 的 `end` 设为 `begin + duration_ms`，时长必须是该包 SUMO 步长的
   正整数倍；
5. “开始仿真”使用 `artifacts/simulations/yyyy-mm-dd-hh-mm-ss/`，“测试”使用
   `artifacts/tests/yyyy-mm-dd-hh-mm-ss/`。两者都先复制已保存快照，SUMO 输入和输出均限定在
   该次 artifact 树；
6. 用户未保存或保存后又修改页面值时，开始/测试在创建实验前自动执行同一保存
   用例；未变更时复用已保存快照；
7. API 只接收类型化配置和时间戳 ID，不接收任意本机路径。快照必须校验工作区、场景和地图
   归属后才能创建运行副本。

### 后果

- ADR-027 的 `artifacts/sumo/<experiment-id>/package/` 仍作为无配置快照的兼容入口；桌面端新建
  正式/测试运行必须使用本 ADR 的目录；
- 时间戳在同一秒内冲突时向后选取第一个可用秒，仍保持固定目录格式；
- `configuration.json` 是用户快照元数据，`.sumocfg` 仍是 SUMO 的权威运行配置；
- 生成快照和 artifact 是本地用户数据，不进入 Git。

---

## 3. 待验证但不改变当前基线的议题

以下事项需要实现和基准测试后量化，目前不构成新的架构方向：

1. 在目标硬件上 CARLA 可稳定承载的最大 ROI Actor 数；
2. SUMO 在 50 ms step 下的 50/500/2,500 车辆实时因子；
3. Parquet batch size、snapshot interval 与 seek 延迟的最优平衡；
4. 目标桌面平台上原生 CARLA 窗口的 resize、focus 和崩溃恢复稳定性；
5. 单机多实验并发是否值得引入独立 worker。

这些议题应通过 T10 性能和集成报告给出证据。若证据要求改变已接受方向，应新增 ADR，而不是在代码中局部绕开。
