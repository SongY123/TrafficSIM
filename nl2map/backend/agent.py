"""
Agent 模块：把用户的自然语言描述，交给大模型生成一段可执行的 Python 代码。

当前实现走 OpenAI 兼容接口（组里服务器部署的模型通常也是这个格式）。
后续可以直接替换为 Claude Agent SDK / Codex SDK：
agent 的能力会从"只生成代码"升级为"自己写代码、跑代码、看报错、自己改"。
"""
import re
from openai import OpenAI

import config

SYSTEM_PROMPT = """你是一个 Python 程序员。用户会用自然语言描述他想要的路网。
你需要写一段完整的、可直接运行的 Python 代码，调用 roadgen 库生成路网，并导出为 SUMO 格式。

roadgen 的核心用法：
```python
import roadgen

m = roadgen.Map()

# 一条路由 start=(x,y,z) 到 end=(x,y,z)，lanes 描述车道
a = m.add_road(
    start=(0.0, 0.0, 0.0),
    end=(100.0, 0.0, 0.0),
    lanes=[
        roadgen.Lane(width=3.5, direction="forward"),
        roadgen.Lane(width=3.5, direction="backward"),
    ],
)

b = m.add_road(
    start=(100.0, 0.0, 0.0),
    end=(100.0, 100.0, 0.0),
    lanes=[
        roadgen.Lane(width=3.5, direction="forward"),
        roadgen.Lane(width=3.5, direction="backward"),
    ],
)

m.connect(a, b)            # 把两条路连起来
m.export_sumo("output/")   # 导出 SUMO 路网到 output 文件夹
```

要求：
1. 只输出 Python 代码本身，不要任何解释，不要 markdown 代码块标记。
2. 代码必须能直接运行，不要写 if __name__ == "__main__" 之外的交互逻辑。
3. 最后必须调用 m.export_sumo("output/") 导出路网。
4. 根据用户描述合理设计道路数量、坐标、车道和连接关系。
5. 路口处互相连接的两条路，车道数量和方向要一致。
"""

# 模型未配置时返回的占位代码
PLACEHOLDER_CODE = """\
# 模型未配置：请在 backend/.env 中填写 MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME
print("模型未配置，当前为占位流程")
"""


def _strip_code_fence(code: str) -> str:
    """剥掉大模型可能加的 ```python ... ``` 包裹。"""
    code = re.sub(r"^```(?:python)?\s*\n?", "", code.strip())
    code = re.sub(r"\n?```\s*$", "", code.strip())
    return code.strip() + "\n"


def generate_code(description: str) -> str:
    """
    输入：用户的自然语言描述。
    输出：大模型生成的 Python 代码字符串。
    """
    if not config.MODEL_CONFIGURED:
        return PLACEHOLDER_CODE

    client = OpenAI(base_url=config.MODEL_BASE_URL, api_key=config.MODEL_API_KEY)
    resp = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
        temperature=0.2,
    )
    return _strip_code_fence(resp.choices[0].message.content)
