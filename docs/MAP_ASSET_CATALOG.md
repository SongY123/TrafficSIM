# 地图资产目录与支持格式

> 状态：Implemented UI catalog / conversion scope constrained by PRD
>
> 适用范围：TrafficVerse 资产中心、地图 manifest、MapLibre/deck.gl 预览

## 1. 目标与边界

资产中心把一张地图作为一个可复用目录管理。目录名称来自地图摘要，文件列表来自服务端已校验的
`manifest.yaml`。UI 不扫描任意本机路径，也不复制后端地图文件。选择目录或文件时，右侧请求该
地图包发布的标准 `network.geojson`，由 MapLibre 管理相机、deck.gl 绘制路网。

“支持格式”分为四个层级：

1. **目录收录**：manifest 可跟踪并显示完整文件名和后缀；
2. **上传校验**：可通过当前 `/api/v1/maps/import` 上传 OpenDRIVE；只有生成完整可运行 SUMO
   包后才发布到目录；
3. **二维预览**：可生成当前标准路网预览；
4. **倾斜预览**：复用同一标准路网和 deck.gl 图层，只改变 WebGL 相机与图层。

目录收录不表示 TrafficVerse 会把任意格式自动转换为 SUMO 地图。当前上传入口以 OpenDRIVE 为
权威源，但现有通用编译器只生成标准展示资产，缺少 `.net.xml`、`.sumocfg` 或 route/vType 时
导入任务必须明确失败且不得进入 catalog。CARLA 资产和配准文件已移除，不属于当前地图包。

## 2. 支持格式矩阵

| 文件格式 | 主要消费者 | 目录收录 | 直接导入 | 预览 | 说明 |
|---|---|---:|---:|---:|---|
| `.xodr` | SUMO 生成链 | 是 | 条件支持 | 编译后 | 仅完整可运行 SUMO 包可发布 |
| `.net.xml` | SUMO | 是 | 否 | 通过同包 GeoJSON | SUMO 路网 |
| `.sumocfg` | SUMO | 是 | 否 | 通过同包 GeoJSON | SUMO 运行配置 |
| `.rou.xml` | SUMO | 是 | 否 | 否 | 路线、车流或车型 |
| `.add.xml` | SUMO | 是 | 否 | 否 | SUMO 附加定义 |
| `.geojson` | deck.gl、MapLibre | 是 | 否 | 是 | `network.geojson` 是标准资源 |
| `.json` | deck.gl、MapLibre | 是 | 否 | 视 schema | 路网、样式或 tileset 元数据 |
| `tileset.json`、`.b3dm` | deck.gl 3D Tiles | 是 | 否 | 显式引用后 | 当前 Gate 不加载大型场景 |
| `.glb`、`.gltf`、`.bin` | deck.gl | 是 | 否 | 显式引用后 | WebGL 模型及缓冲区 |
| `.yaml`、`.yml` | TrafficVerse | 是 | 否 | 否 | manifest、信号和路线配置 |

当前不支持 OSM、Shapefile、Vissim 文件直接导入或转换。增加权威导入源必须先扩展地图编译器、
manifest 校验、REST 契约和对应 ADR，不能只增加文件选择后缀。

## 3. 标准地图包目录

```text
Town04/
├── manifest.yaml
├── Town04.xodr
├── Town04.net.xml
├── Town04.rou.xml
├── vtypes.rou.xml
├── map.sumocfg
├── network.geojson
├── network.json
├── routes.yaml
└── signals.yaml
```

`manifest.yaml` 是文件清单和 checksum 的权威来源。资产中心只展示 manifest 中受跟踪的文件。

## 4. 搜索与选择规则

- 搜索匹配地图名称、地图 ID、平台名称、完整文件名和复合后缀；
- 搜索 `SUMO`、`town04`、`geojson` 或 `.net.xml` 均可保留匹配目录；
- 选中文件等价于选中所属地图包，不把 XML 等文件直接交给 MapLibre；
- manifest 尚未返回时先显示目录，返回后增量填充文件；
- 资产预览与场景运行地图选择分离，不改变实验地图 ID。

## 5. 公共 UI 组件

可复用组件为 `ui.widgets.AssetDirectoryWidget`。它只负责目录呈现、搜索过滤和选择事件，不访问
REST、不读取后端目录，也不持有业务真值。

- 输入：`Sequence[AssetDirectoryEntry]`；
- 输出信号：`asset_selected(str)`；
- API/ViewModel 将 `MapSummary + MapManifest` 转换为目录模型；
- 使用方根据 `asset_id` 请求并展示预览。
