#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电网场景 Agent 测评脚本
功能：逐题发送 POST 请求到指定服务端点，保存原始响应与汇总结果。
"""

import json
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

import requests


# ===================== 配置区域 =====================
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_ENDPOINT = "/predict"
DEFAULT_TIMEOUT = 600  # 单题请求超时（秒）
DEFAULT_DELAY = 0.5    # 题与题之间间隔（秒），避免请求过快
# ===================================================


def load_questions(jsonl_path: str):
    """加载 .jsonl 题目文件，返回题目列表。"""
    questions = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("record_type") == "question":
                    questions.append(obj)
            except json.JSONDecodeError as e:
                print(f"[警告] 跳过无效 JSON 行: {e}")
    return questions


def send_question(host, port, endpoint, question_text, timeout):
    """
    向服务端发送单道题目。
    返回: (success: bool, response_text: str, status_code: int|None, elapsed_ms: float)
    """
    url = f"http://{host}:{port}{endpoint}"
    payload = {"question": question_text}
    headers = {"Content-Type": "application/json"}

    try:
        start = time.perf_counter()
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        return True, resp.text, resp.status_code, elapsed_ms
    except requests.exceptions.Timeout:
        return False, f"请求超时（>{timeout}s）", None, timeout * 1000
    except requests.exceptions.ConnectionError as e:
        return False, f"连接错误: {e}", None, 0.0
    except requests.exceptions.RequestException as e:
        return False, f"请求异常: {e}", None, 0.0


def run_evaluation(
    questions,
    output_dir: Path,
    host: str,
    port: int,
    endpoint: str,
    timeout: int,
    delay: float,
):
    """执行测评主流程。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 汇总结果文件
    summary_path = output_dir / "summary.json"
    summary = {
        "meta": {
            "host": host,
            "port": port,
            "endpoint": endpoint,
            "started_at": datetime.now().isoformat(),
            "total_questions": len(questions),
        },
        "results": [],
    }

    # 同时写一份 CSV 方便快速查看
    csv_path = output_dir / "summary.csv"
    with open(csv_path, "w", encoding="utf-8-sig") as csvf:
        csvf.write("id,section_id,section_name,status_code,success,elapsed_ms,timestamp\n")

    print(f"=" * 60)
    print(f"开始测评 | 共 {len(questions)} 题")
    print(f"服务端: http://{host}:{port}{endpoint}")
    print(f"结果保存: {output_dir.resolve()}")
    print(f"=" * 60)

    for idx, q in enumerate(questions, start=1):
        qid = q.get("id", f"#{idx}")
        section_id = q.get("section_id", "")
        section_name = q.get("section_name", "")
        content = q.get("content_markdown", "")

        print(f"\n[{idx}/{len(questions)}] 正在测评: {qid} ({section_name})")

        success, resp_text, status_code, elapsed_ms = send_question(
            host, port, endpoint, content, timeout
        )

        # 保存单题原始响应
        raw_file = output_dir / f"{qid}_response.json"
        raw_data = {
            "question_id": qid,
            "section_id": section_id,
            "section_name": section_name,
            "question_text": content,
            "success": success,
            "status_code": status_code,
            "elapsed_ms": round(elapsed_ms, 2),
            "timestamp": datetime.now().isoformat(),
            "response": resp_text,
        }
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=2)

        # 写入汇总
        result_entry = {
            "question_id": qid,
            "section_id": section_id,
            "section_name": section_name,
            "success": success,
            "status_code": status_code,
            "elapsed_ms": round(elapsed_ms, 2),
            "timestamp": datetime.now().isoformat(),
            "response_preview": resp_text[:500] + "..." if len(resp_text) > 500 else resp_text,
        }
        summary["results"].append(result_entry)

        # 追加 CSV
        with open(csv_path, "a", encoding="utf-8-sig") as csvf:
            safe_section = section_name.replace(",", ";")
            csvf.write(
                f"{qid},{section_id},{safe_section},{status_code},{success},{elapsed_ms:.2f},{result_entry['timestamp']}\n"
            )

        # 实时打印
        status_str = f"HTTP {status_code}" if status_code is not None else "异常"
        print(f"  状态: {'成功' if success else '失败'} | {status_str} | 耗时: {elapsed_ms:.1f}ms")
        print(f"  原始响应已保存: {raw_file.name}")

        # 题间延迟
        if idx < len(questions) and delay > 0:
            time.sleep(delay)

    # 保存汇总
    summary["meta"]["finished_at"] = datetime.now().isoformat()
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # 统计
    total = len(questions)
    ok_count = sum(1 for r in summary["results"] if r["success"])
    fail_count = total - ok_count

    print(f"\n{'=' * 60}")
    print("测评完成!")
    print(f"  总题数: {total}")
    print(f"  成功:   {ok_count}")
    print(f"  失败:   {fail_count}")
    print(f"  汇总JSON: {summary_path.resolve()}")
    print(f"  汇总CSV:  {csv_path.resolve()}")
    print(f"{'=' * 60}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="电网场景 Agent 测评脚本（仅测试数据）")
    parser.add_argument(
        "--output",
        "-o",
        default="results",
        help="结果输出文件夹 (默认: results)",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"服务端主机 (默认: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"服务端端口 (默认: {DEFAULT_PORT})")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"API路径 (默认: {DEFAULT_ENDPOINT})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"单题超时秒数 (默认: {DEFAULT_TIMEOUT})")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"题间延迟秒数 (默认: {DEFAULT_DELAY})")

    args = parser.parse_args()

    # 固定使用测试数据，不再支持切换或自定义输入
    input_path = "测试题目.jsonl"
    print(f"[INFO] 使用测试题目: {input_path}")

    if not os.path.exists(input_path):
        print(f"[错误] 输入文件不存在: {input_path}")
        sys.exit(1)

    questions = load_questions(input_path)
    if not questions:
        print("[错误] 未从文件中加载到任何题目，请检查文件格式。")
        sys.exit(1)

    run_evaluation(
        questions=questions,
        output_dir=Path(args.output),
        host=args.host,
        port=args.port,
        endpoint=args.endpoint,
        timeout=args.timeout,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
