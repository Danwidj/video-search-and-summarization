# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A local stand-in for the model endpoint, so the experiment agent can be checked at no cost.

Answers every ``POST`` (``/v1/chat/completions``) with the contract's minimal valid report and a
fixed usage block. It never forwards anything. Standard library only::

    python3 experiments/agent/fake_upstream.py --port 8899
"""

import argparse
import http.server
import json
from pathlib import Path

REPORT = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "valid" / "minimal-report.json")
                    .read_text())
USAGE = {"prompt_tokens": 8708, "completion_tokens": 1190, "total_tokens": 9898}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (http.server's naming)
        self.rfile.read(int(self.headers.get("content-length", 0)))
        body = json.dumps({"choices": [{"message": {"content": json.dumps(REPORT)}, "finish_reason": "stop"}],
                           "usage": USAGE}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()
    http.server.HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
