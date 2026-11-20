#!/usr/bin/env python3
"""Helper to call sellersprite MCP tools - fixed encoding"""
import sys, json, urllib.request, urllib.error, os

URL = "https://mcp.sellersprite.com/mcp"

def call_tool(name: str, arguments: dict):
    secret_key = os.environ.get("SELLERSPRITE_API_KEY")
    if not secret_key:
        return {"error": "SELLERSPRITE_API_KEY is not configured"}
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments}
    }).encode('utf-8')
    req = urllib.request.Request(URL, data=payload,
        headers={"Content-Type": "application/json", "secret-key": secret_key,
                 "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode('utf-8')
            if raw.lstrip().startswith("{"):
                data = json.loads(raw)
            else:
                data = next(
                    message for line in raw.splitlines() if line.startswith("data:")
                    if (message := json.loads(line[5:].strip())).get("id") == 1
                )
            text = data['result']['content'][0]['text']
            return json.loads(text)
    except Exception as e:
        return {"error": str(e)}

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    name = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    result = call_tool(name, args)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
