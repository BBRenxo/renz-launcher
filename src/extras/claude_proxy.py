import json
from mitmproxy import http

def request(flow: http.HTTPFlow) -> None:
    if "api.anthropic.com" in flow.request.pretty_host:
        flow.request.scheme = "http"
        flow.request.host = "127.0.0.1"
        flow.request.port = 11434
        
        # If it's a message request, we might need to intercept and modify the model name
        # if Claude Desktop forces a specific model name. But let's see if we can just pass it through first.
        if flow.request.path.endswith("/v1/messages") and flow.request.method == "POST":
            try:
                body = json.loads(flow.request.content)
                # If Claude sends an Anthropic model but we want an Ollama model, we'd map it here.
                # For now, we leave it, assuming the UI lets them pick the Ollama model directly.
                flow.request.content = json.dumps(body).encode('utf-8')
            except Exception as e:
                print(f"Error modifying request: {e}")

def response(flow: http.HTTPFlow) -> None:
    if flow.request.path.endswith("/v1/models") or "/models" in flow.request.path:
        try:
            original_data = json.loads(flow.response.content)
            ollama_models = original_data.get('data', [])
            
            anthropic_models = []
            for m in ollama_models:
                model_id = m.get('id', '')
                anthropic_models.append({
                    "type": "model",
                    "id": model_id,
                    "display_name": f"{model_id}", # Just use the ID as display name
                    "created_at": "2024-10-22T00:00:00Z"
                })
                
            # Add some standard ones just in case the UI strictly requires them to render the picker
            standard_models = [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229"
            ]
            for sm in standard_models:
                if not any(am['id'] == sm for am in anthropic_models):
                    anthropic_models.append({
                        "type": "model",
                        "id": sm,
                        "display_name": f"{sm} (Fallback)",
                        "created_at": "2024-10-22T00:00:00Z"
                    })
            
            mocked_response = {
                "type": "list",
                "data": anthropic_models
            }
            
            flow.response.content = json.dumps(mocked_response).encode('utf-8')
            flow.response.headers["content-type"] = "application/json"
        except Exception as e:
            print(f"Error modifying response: {e}")
