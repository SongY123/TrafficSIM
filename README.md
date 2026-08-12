# TrafficVerse

TrafficVerse 的目标架构是“SUMO 全局交通真值 + TrafficVerse 自有二维页面 + CARLA ROI 原生三维
窗口”。SUMO 只通过 TraCI 接入，TrafficVerse 不嵌入 SUMO GUI；CARLA 必须 windowed 运行，其
原生窗口通过 PySide6 `QWindow.fromWinId()` 托管到运行页右侧。

生产装配已切换为 `SumoTrafficEngineAdapter`，旧的 `NativeTrafficEngine` 二维实现已经删除。
Town04 SUMO 资产和 Qt 原生窗口 host 仍用于独立的 Core Run 验收；真实 CARLA 联仿和
native-window 现场 Gate 仍必须在同一图形桌面会话完成。

## 运行模式与版本

- Python 3.10
- Node.js 16.20.2、npm 8.19.4（仅构建左侧 Web 地图）
- Town04 + CARLA Core Run：SUMO 1.27.1、50 ms、`127.0.0.1:8813`
- 原生二维 SUMO 包：直接使用 PATH 中主机 SUMO 的实际版本和 `.sumocfg` 自带步长
- CARLA 0.9.16：`127.0.0.1:2000`
- TrafficVerse API：`127.0.0.1:8000`

## 安装

```bash
uv sync --frozen --extra sumo --extra carla --extra ui
```

## 生成并校验 Town04 SUMO 资产

```bash
python scripts/maps/generate_town04_sumo.py
sumo -c configs/maps/town04/map.sumocfg --end 5
```

## 启动

### 直接运行已有 SUMO 场景（二维）

把每个完整场景目录放到 `configs/maps` 下即可，不需要补 `.xodr` 或 TrafficVerse 场景 YAML：

```text
configs/maps/my-scene/
├── my-scene.sumocfg
├── my-scene.net.xml
├── my-scene.rou.xml
└── my-scene.add.xml          # 仅在 sumocfg 引用时需要
```

然后直接启动 API 和 UI：

```bash
uv run trafficverse serve --host 127.0.0.1 --port 8000
uv run trafficverse ui --api-url http://127.0.0.1:8000
```

在“场景配置”中选择该 SUMO 包并创建/开始实验。TrafficVerse 会自动：

- 解析 `.sumocfg` 引用的网络、路线、additional、begin/end/step-length；
- 从 `.net.xml` 生成 MapLibre/deck.gl 道路、路口和通用信号点；
- 启动 PATH 中的本机 `sumo` 并通过 TraCI 推进；
- 使用实际 SUMO 版本，不要求等于 1.27.1；
- 禁用 CARLA/ROI，只运行二维仿真；
- 从桌面“仿真配置”启动的正式运行写入 `artifacts/simulations/<timestamp>/`，快速测试写入
  `artifacts/tests/<timestamp>/`；未携带配置快照的兼容 API 才使用
  `artifacts/sumo/<experiment-id>/`。三种入口都不修改源场景。
- 正式运行会生成 SUMO summary/tripinfo/edgeData/laneData/queue 结果和 Parquet 快照/增量回放记录；
  “历史仿真”读取正式目录，使用本次运行实际 `.net.xml` 展示道路，并可导出完整 ZIP。

“场景配置”只列出这种由 `.sumocfg` 自动发现的二维 SUMO 包。Town04 Core Run manifest 仍可在
“资产中心”查看，但不会再作为另一条二维场景实现混入该选择器。

目录中只有一个 `.sumocfg` 时，场景 ID 是目录名；有多个时，每个配置分别显示为
`<目录名>-<配置文件名>`。所有输入必须存在并位于 `configs/maps` 内。损坏场景会显示校验错误，
但不会阻止其他场景加载。

直道障碍物示例位于 `configs/maps/mixed-automation-obstacle`，道路为双向三车道，前进方向右侧两条车道
从仿真开始就由真实障碍车辆堵塞。场景包含多辆随机分布的 L0-L5 车辆，同等级车辆的 Krauss 参数带确定性
正态扰动；直接打开它的 `.sumocfg` 会使用 SUMO 自身的安全换道机制。
要观察 L0-L5 的差异化制动和换道策略，在 macOS 上运行：

```bash
open -a XQuartz
uv run python scripts/dev/run_mixed_automation_obstacle.py --delay-ms 500
```

该示例 runner 默认让 L0 车辆较晚发现障碍并以较弱减速度制动，因此仍可能发生碰撞；使用
`--no-l0-crash` 可切换回 SUMO 原生安全跟驰模式。

### Town04 + CARLA Core Run（独立验收链路）

1. 启动 SUMO TraCI 后端。推荐 headless；它没有需要接入 TrafficVerse 的页面：

```bash
sumo -c configs/maps/town04/map.sumocfg --remote-port 8813
```

调试时可把 `sumo` 换为 `sumo-gui`，但 GUI 保持独立。

2. 在同一图形桌面会话启动 windowed CARLA 0.9.16，不使用 `-RenderOffScreen`。

3. 设置 CARLA 顶层窗口的 native window ID，并启动 API/UI：

```bash
export TRAFFICVERSE_CARLA_WINDOW_ID=<native-window-id>
uv run trafficverse serve --host 127.0.0.1 --port 8000
uv run trafficverse ui --api-url http://127.0.0.1:8000
```

UI 左侧从 REST/WebSocket 获取 SUMO 派生的标准快照并自行绘制；右侧直接显示 CARLA 原生窗口。
系统不传输 `camera.frame` 或 JPEG/base64 图像。
二维页面使用仓库内置的 MapLibre/deck.gl 离线 bundle，运行时不需要 Node.js、CDN 或公网。
Town04 没有真实地理 `geoReference`，所以地图采用由本地 OpenDRIVE/GeoJSON 派生的 OSM 风格道路
分层，而不叠加会与仿真坐标错位的现实 OpenStreetMap 瓦片。车辆模型和所有 Web 资源同样离线加载。
`network.geojson` 保留标准车道与信号灯要素，并从同一份 `Town04.net.xml` 追加 SUMO 车道、路口
内部连接线和路口面作为显示专用几何；这些附加要素只用于 MapLibre/deck.gl 预览，不参与车辆推进。
执行 `python scripts/maps/generate_town04_sumo.py --display-only` 可在不重建路线的情况下刷新显示几何。
点击“开始运行”后，车辆位置和灯色由 SUMO 的实时快照更新；Web 地图不使用墙上时间自行推算车辆位置。

服务器的 Web 地图构建环境为 Node.js 16.20.2、npm 8.19.4：

```bash
cd ui/web/map
npm ci
npm run build
```

Python/Qt 运行使用 conda `carla` 环境。当前服务器 X11 的 Mesa `llvmpipe` 会被 Chromium 的
WebGL blocklist 拦截，因此仅在该软件渲染环境显式启用已验证的覆盖参数：

```bash
DISPLAY=:1 conda run -n carla python -m trafficverse.cli ui \
  --api-url http://127.0.0.1:8000 \
  --allow-software-webgl
```

有受支持硬件 GPU 的桌面环境不要添加 `--allow-software-webgl`。

## 验证

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

真实 SUMO integration：

```bash
TRAFFICVERSE_SUMO_INTEGRATION=1 uv run pytest -m traffic \
  tests/integration/traffic/test_sumo_adapter.py
```

真实原生 SUMO 包 integration（使用主机当前 SUMO）：

```bash
TRAFFICVERSE_SUMO_PACKAGE_INTEGRATION=1 uv run pytest -m "integration and traffic" \
  tests/integration/traffic/test_managed_sumo_package.py
```

CARLA 与 Qt foreign-window 验收需要 PySide6、CARLA 和目标窗口处于同一主机、同一用户、同一
图形桌面会话。远程 tty、无头 CARLA 或 RenderOffScreen 无法完成该 Gate。

设计详情见 [PRD](docs/PRD.md)、[System Design](docs/SYSTEM_DESIGN.md)、
[ADR](docs/ADR.md)、[地图资产目录与支持格式](docs/MAP_ASSET_CATALOG.md) 和
[Agent Guide](docs/AGENT_DEVELOPMENT_GUIDE.md)。
