# 路网生成 Demo（Road Network Generation Demo）

基于大语言模型 Agent 自动生成路网，并导出为 SUMO 格式的后端 Demo。

## 整体流程

```
用户自然语言描述（"我要一个十字路口"）
        ↓
  FastAPI 后端（main.py）
        ↓
  Agent 生成调用 roadgen 的 Python 代码（agent.py）
        ↓
  独立任务目录中执行代码（runner.py）
        ↓
  roadgen 构建路网并导出 SUMO 文件（.net.xml）
        ↓
  返回执行日志与生成的文件列表，供前端渲染
```

## 目录结构

```
backend/
├── main.py            # FastAPI 入口：路由、CORS、异常处理
├── agent.py           # Agent：自然语言 → 可执行的 Python 代码
├── runner.py          # 执行生成代码，隔离每次任务并收集产物
├── config.py          # 配置读取（从 .env 读取，不写死敏感信息）
├── requirements.txt   # Python 依赖
└── .env.example       # 环境变量模板（复制为 .env 后填写）
```

## 环境要求

- Python 3.10+
- 依赖：FastAPI、Uvicorn、OpenAI 兼容客户端、python-dotenv
- roadgen：仅 Linux 提供预编译 wheel，Windows 请使用 WSL 或在 Linux 服务器上运行

roadgen 项目地址：https://github.com/hakuturu583/hdmap_generator

## 快速开始

```bash
cd backend
pip install -r requirements.txt

# 复制配置模板，填写模型服务信息
cp .env.example .env
#   编辑 .env，填入 MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME

python -m uvicorn main:app --reload --port 8000
```

启动后访问：

- 接口文档（Swagger）：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

## 接口说明

### POST /generate

请求：
```json
{ "description": "一个十字路口，两条双向两车道的道路垂直相交" }
```

响应：
```json
{
  "status": "success",
  "description": "...",
  "model_configured": true,
  "generated_code": "...",
  "execution": {
    "exit_code": 0,
    "stdout": "",
    "stderr": "",
    "elapsed_sec": 1.23,
    "artifacts": ["output/xxx.net.xml"],
    "timeout": false
  }
}
```

## 后续计划

- Agent 层由 OpenAI 兼容调用切换为 Claude Agent SDK / Codex SDK，
  使 Agent 具备"写代码 → 执行 → 看报错 → 自行修复"的闭环能力。
- 接入组里服务器部署的模型服务。
- 在 Linux 环境安装 roadgen，打通 SUMO 路网实际导出。
