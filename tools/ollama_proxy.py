# (c) 2025 Neeraj Sharma. All rights reserved.
# Licensed under the MIT License. See LICENSE in the project root for license information.

import copy
import os
import json
import uuid
import requests
from fastapi import FastAPI, Request, Response
from datetime import datetime
from typing import Dict, Any

app = FastAPI()

# Configuration
OLLAMA_URL = "http://localhost:11434"  # Default Ollama URL
SESSIONS_DIR = "sessions"  # Directory to store session files

# Create sessions directory if it doesn't exist
os.makedirs(SESSIONS_DIR, exist_ok=True)

def save_session_data(session_id: str, request_data: Dict[str, Any], response_data: Dict[str, Any]):
    """Save request and response data to a session file"""
    session_file = os.path.join(SESSIONS_DIR, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{session_id}.json")

    # dont change response_data directly, because it will be used later at call-site
    response_data_copy = copy.deepcopy(response_data)
    decoded_content = {}
    if "content" in response_data_copy:
        try:
            # if content starts with data: then it is a streaming jsonl type of response,
            # so we should add it as an array of dictionaries
            content = response_data_copy["content"].strip()
            if content.startswith("data:"):
                decoded_content = []
                for line in content.splitlines():
                    # DONE is the last message in a stream, skip it
                    if line.strip().startswith("data: [DONE]"):
                        continue
                    if line.startswith("data:"):
                        json_part = line[len("data:"):].strip()
                        if json_part:
                            decoded_content.append(json.loads(json_part))
            else:
                decoded_content = json.loads(content)

            del response_data_copy["content"]
            response_data_copy["decoded_content"] = decoded_content
        except Exception as e:
            print(f"Error parsing response content as JSON: {e}, content: {response_data['content']}")
    
    session_data = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "request": request_data,
        "response": response_data_copy
    }
    
    with open(session_file, 'w') as f:
        try:
            json.dump(session_data, f, indent=2)
        except Exception as e:
            print(f"Error saving session data: {e}")
            print(f"Session {session_id} data: {session_data}")


def get_session_id():
    """Generate a unique session ID"""
    return str(uuid.uuid4())

@app.api_route('/{subpath:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
async def proxy(subpath: str, request: Request):
    """Proxy all requests to Ollama and save session data"""
    # Get the full Ollama URL
    ollama_url = f"{OLLAMA_URL}/{subpath.lstrip('/')}"
    
    # Generate a session ID for this request
    session_id = get_session_id()
    
    # Prepare request data
    request_data = {
        "method": request.method,
        "url": ollama_url,
        "headers": dict(request.headers),
        "args": dict(request.query_params),
        "json": await request.json() if request.headers.get('content-type') == 'application/json' else None,
        "data": await request.body() if request.headers.get('content-type') != 'application/json' else None
    }
    # None results in error during json dump
    if request_data["json"] is None:
        del request_data["json"]
    if request_data["data"] is None:
        del request_data["data"]
    else:
        if isinstance(request_data["data"], bytes):
            request_data["data"] = request_data["data"].decode('utf-8')

    try:
        # Forward the request to Ollama
        if request.method == 'GET':
            ollama_response = requests.get(ollama_url, headers=dict(request.headers), params=request.query_params)
        elif request.method == 'POST':
            ollama_response = requests.post(ollama_url, headers=dict(request.headers), json=await request.json() if request.headers.get('content-type') == 'application/json' else None, data=await request.body() if request.headers.get('content-type') != 'application/json' else None)
        elif request.method == 'PUT':
            ollama_response = requests.put(ollama_url, headers=dict(request.headers), json=await request.json() if request.headers.get('content-type') == 'application/json' else None, data=await request.body() if request.headers.get('content-type') != 'application/json' else None)
        elif request.method == 'DELETE':
            ollama_response = requests.delete(ollama_url, headers=dict(request.headers), params=request.query_params)
        else:
            return Response(content="Method not supported", status_code=405)
        
        # Prepare response data
        response_data = {
            "status_code": ollama_response.status_code,
            "headers": dict(ollama_response.headers),
            "content": ollama_response.text
        }
        
        # Save session data
        save_session_data(session_id, request_data, response_data)
        
        # Return the response from Ollama
        return Response(
            content=response_data["content"],
            status_code=ollama_response.status_code,
            headers=ollama_response.headers
        )
        
    except Exception as e:
        # Save error information if request fails
        error_data = {
            "error": str(e),
            "request": request_data
        }
        save_session_data(session_id, request_data, error_data)
        return Response(content=f"Error: {str(e)}", status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=11435)
