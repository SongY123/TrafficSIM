"""
代码执行模块：把大模型生成的代码存到一个独立的任务目录里执行，
并收集执行日志和生成的路网文件。
"""
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime

import config


def _new_task_dir() -> str:
    """为每次请求创建一个独立目录，避免多次请求互相覆盖。"""
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    task_dir = os.path.join(config.WORKSPACES_DIR, task_id)
    os.makedirs(os.path.join(task_dir, "output"), exist_ok=True)
    return task_dir


def _collect_artifacts(task_dir: str) -> list:
    """扫描 output 目录，收集生成的所有文件（相对路径）。"""
    output_dir = os.path.join(task_dir, "output")
    artifacts = []
    for root, _, files in os.walk(output_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, task_dir).replace(os.sep, "/")
            artifacts.append(rel)
    return sorted(artifacts)


def run_generated_code(code: str) -> dict:
    """
    执行大模型生成的代码。
    返回：task_id、退出码、标准输出、错误输出、耗时、生成的文件列表。
    """
    task_dir = _new_task_dir()
    script_path = os.path.join(task_dir, "generate_map.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)

    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "generate_map.py"],
            cwd=task_dir,
            capture_output=True,
            text=True,
            timeout=config.EXEC_TIMEOUT_SEC,
        )
        elapsed = round(time.time() - t0, 2)
        return {
            "task_id": os.path.basename(task_dir),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_sec": elapsed,
            "artifacts": _collect_artifacts(task_dir),
            "timeout": False,
        }
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - t0, 2)
        return {
            "task_id": os.path.basename(task_dir),
            "exit_code": -1,
            "stdout": "",
            "stderr": f"代码执行超过 {config.EXEC_TIMEOUT_SEC} 秒，已被终止",
            "elapsed_sec": elapsed,
            "artifacts": _collect_artifacts(task_dir),
            "timeout": True,
        }
