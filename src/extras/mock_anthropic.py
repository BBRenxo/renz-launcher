from flask import Flask, request
import json

app = Flask(__name__)

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def catch_all(path):
    print(f"[{request.method}] /{path}")
    print(f"Headers: {dict(request.headers)}")
    if request.is_json:
        print(f"Body: {request.json}")
    else:
        print(f"Body: {request.get_data()}")
    print("-" * 40)
    
    # Mock responses for known Anthropic endpoints
    if path == "v1/models" or path == "api/models" or "models" in path:
        return json.dumps({
            "type": "list",
            "data": [
                {
                    "type": "model",
                    "id": "claude-3-5-sonnet-20241022",
                    "display_name": "Claude 3.5 Sonnet",
                    "created_at": "2024-10-22T00:00:00Z"
                },
                {
                    "type": "model",
                    "id": "claude-3-5-haiku-20241022",
                    "display_name": "Claude 3.5 Haiku",
                    "created_at": "2024-10-22T00:00:00Z"
                }
            ]
        }), 200, {'Content-Type': 'application/json'}
        
    return json.dumps({"status": "mocked"}), 200, {'Content-Type': 'application/json'}

if __name__ == '__main__':
    app.run(port=5000)
