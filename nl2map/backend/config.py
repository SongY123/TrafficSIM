"""配置读取：所有敏感信息都从 .env 文件读取，不写死在代码里。"""
import os
from dotenv import load_dotenv

load_dotenv()

MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "").strip()
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "").strip()

# 模型是否已配置
MODEL_CONFIGURED = bool(MODEL_BASE_URL and MODEL_API_KEY and MODEL_NAME)

# 每次生成代码的执行超时时间（秒）
EXEC_TIMEOUT_SEC = 60

# 工作目录：每次请求生成的代码和路网文件都放这里
WORKSPACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspaces")
