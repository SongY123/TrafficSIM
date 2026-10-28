"""
FastAPI 后端入口。

Pipeline：
  前端自然语言描述
    → agent 生成调用 roadgen 的 Python 代码
    → runner 在独立任务目录执行代码
    → 收集 SUMO 路网文件
    → 返回给前端
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from pydantic import BaseModel, Field

import agent
import config
import runner

app = FastAPI(
    title="路网生成 Demo",
    description="自然语言 → Agent 生成代码 → roadgen 导出 SUMO 路网",
    version="0.1.0",
    docs_url=None,  # 关掉默认文档页，下面用国内 CDN 自定义
)

# 允许前端跨域访问（学长的前端渲染部分会从别的端口/域名调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/docs", include_in_schema=False)
def custom_docs():
    """自定义文档页：Swagger UI 资源走国内镜像，避免默认 CDN 白屏。"""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="路网生成 Demo - 接口文档",
        swagger_js_url="https://registry.npmmirror.com/swagger-ui-dist/5.20.0/files/swagger-ui-bundle.js",
        swagger_css_url="https://registry.npmmirror.com/swagger-ui-dist/5.20.0/files/swagger-ui.css",
    )


class GenerateRequest(BaseModel):
    description: str = Field(..., min_length=1, description="对路网的自然语言描述")


@app.get("/")
def root():
    return {"msg": "路网生成 Demo 后端运行中，接口文档见 /docs"}


@app.get("/health")
def health():
    """健康检查：顺便告诉调用方模型有没有配好。"""
    return {
        "status": "ok",
        "model_configured": config.MODEL_CONFIGURED,
    }


@app.post("/generate")
def generate(req: GenerateRequest):
    # 1. Agent 生成代码
    try:
        code = agent.generate_code(req.description)
    except Exception as e:
        return {
            "status": "agent_error",
            "description": req.description,
            "error": f"调用模型失败：{e}",
        }

    # 2. 执行代码并收集路网产物
    run_result = runner.run_generated_code(code)

    # 3. 根据执行结果决定状态
    if run_result["timeout"]:
        status = "execution_timeout"
    elif run_result["exit_code"] != 0:
        status = "execution_error"
    else:
        status = "success"

    return {
        "status": status,
        "description": req.description,
        "model_configured": config.MODEL_CONFIGURED,
        "generated_code": code,
        "execution": run_result,
    }
