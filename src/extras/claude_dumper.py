import json
from mitmproxy import http

def response(flow: http.HTTPFlow) -> None:
    if "claude.ai" in flow.request.pretty_host:
        if flow.response.headers.get("content-type", "").startswith("application/json"):
            try:
                data = json.loads(flow.response.text)
                print(f"--- URL: {flow.request.path} ---")
                print(json.dumps(data, indent=2)[:500]) # Print first 500 chars to avoid massive logs
                print("-----------------------------------")
            except Exception as e:
                pass
