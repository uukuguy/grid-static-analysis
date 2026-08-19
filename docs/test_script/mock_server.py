#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock 服务端 — 电网场景 Agent 测评用
功能：
  1. 监听指定端口，接收 POST /predict 请求；
  2. 将收到的 JSON body 原样（或按配置包装后）返回；
  3. 自动记录每次请求的输入输出到日志文件夹。

启动示例：
    python mock_server.py          # 默认 8000 端口
    python mock_server.py -p 9000  # 指定 9000 端口
"""

import json
import os
import sys
import argparse
import time
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler


# ===================== 配置区域 =====================
DEFAULT_PORT = 8000
DEFAULT_LOG_DIR = "mock_logs"
# ===================================================


class MockHandler(BaseHTTPRequestHandler):
    """处理 /predict 请求的 Handler"""

    log_dir: Path = Path(DEFAULT_LOG_DIR)
    request_counter = 0

    def _send_json(self, status_code, data_dict):
        """发送 JSON 响应"""
        body = json.dumps(data_dict, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return body.decode("utf-8")

    def _save_log(self, record):
        """保存单条请求记录"""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = self.log_dir / f"req_{ts}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    def do_POST(self):
        MockHandler.request_counter += 1
        req_id = MockHandler.request_counter
        timestamp = datetime.now().isoformat()

        # 读取请求体
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""

        # 尝试解析 JSON
        try:
            parsed_body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            parsed_body = {"_parse_error": True, "_raw": raw_body}

        # 构造回显响应：原样返回收到的内容，并附加元信息
        response_data = {
            "mock": True,
            "echo": parsed_body,
            "meta": {
                "received_at": timestamp,
                "req_id": req_id,
                "path": self.path,
                "method": "POST",
                "content_type": self.headers.get("Content-Type", ""),
            },
        }

        # 发送响应
        resp_text = self._send_json(200, response_data)

        # 组装日志记录
        log_record = {
            "req_id": req_id,
            "timestamp": timestamp,
            "method": "POST",
            "path": self.path,
            "client": self.client_address,
            "headers": dict(self.headers),
            "request_body": parsed_body,
            "request_raw": raw_body,
            "response_status": 200,
            "response_body": response_data,
            "response_raw": resp_text,
        }
        self._save_log(log_record)

        # 终端打印简要信息
        q_preview = str(parsed_body)[:120] + "..." if len(str(parsed_body)) > 120 else str(parsed_body)
        print(f"[{req_id:04d}] {timestamp} | POST {self.path} | body={q_preview}")

    def do_GET(self):
        """GET 请求健康检查"""
        MockHandler.request_counter += 1
        req_id = MockHandler.request_counter
        timestamp = datetime.now().isoformat()

        response_data = {
            "mock": True,
            "status": "running",
            "message": "Mock server is up. Send POST /predict to test.",
            "meta": {
                "received_at": timestamp,
                "req_id": req_id,
                "path": self.path,
            },
        }
        resp_text = self._send_json(200, response_data)

        log_record = {
            "req_id": req_id,
            "timestamp": timestamp,
            "method": "GET",
            "path": self.path,
            "client": self.client_address,
            "headers": dict(self.headers),
            "response_status": 200,
            "response_body": response_data,
        }
        self._save_log(log_record)
        print(f"[{req_id:04d}] {timestamp} | GET  {self.path} | health check")

    def log_message(self, format, *args):
        """禁用默认的 http.server 访问日志（我们已自定义输出）"""
        pass


def run_server(port: int, log_dir: Path):
    MockHandler.log_dir = log_dir
    server_address = ("", port)
    httpd = HTTPServer(server_address, MockHandler)

    print("=" * 60)
    print("Mock 服务端已启动")
    print(f"  监听端口: {port}")
    print(f"  POST 地址: http://localhost:{port}/predict")
    print(f"  日志保存: {log_dir.resolve()}")
    print("=" * 60)
    print("按 Ctrl+C 停止服务\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n正在停止 Mock 服务端...")
        httpd.shutdown()
        print("已停止。")


def main():
    parser = argparse.ArgumentParser(description="电网场景 Agent Mock 服务端")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help=f"监听端口 (默认: {DEFAULT_PORT})")
    parser.add_argument("-l", "--log-dir", default=DEFAULT_LOG_DIR, help=f"日志文件夹 (默认: {DEFAULT_LOG_DIR})")
    args = parser.parse_args()

    run_server(args.port, Path(args.log_dir))


if __name__ == "__main__":
    main()
