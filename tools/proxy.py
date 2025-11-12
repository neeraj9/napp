# (c) 2025 Neeraj Sharma
# LICENSE: MIT

# Dependencies
#
# ```console
# python -m venv venv
# ```
#
# Windows:
# ```console
# venv\Scripts\activate
# ```
#
# GNU/Linux or Mac OSX
# ```console
# source venv/bin/activate
# ```
#
# ```console
# pip install python-dotenv requests
# pip install "fastapi[all]" uvicorn python-dotenv httpx pydantic-settings
# ```


# Running
# uvicorn proxy:app --host localhost --port 8882 --reload

import logging
import logging.handlers
import os
import uuid
import httpx # Async HTTP client
from contextvars import ContextVar # For request-scoped context like request_id
from typing import List, Optional, Union, Dict, Any

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import validator
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# --- Configuration using Pydantic ---
class AppConfig(BaseSettings):
    PROXY_HOST: str = "localhost"
    PROXY_PORT: int = 8882

    CORS_ALLOWED_ORIGINS_STR: str
    CORS_ALLOWED_ORIGINS: List[str] = []

    YACY_HOST_URL: Optional[str] = None
    YACY_USERNAME: Optional[str] = None
    YACY_PASSWORD: Optional[str] = None

    MEILISEARCH_HOST_URL: Optional[str] = None
    MEILISEARCH_API_KEY: Optional[str] = None

    OLLAMA_HOST_URL: str = "http://localhost:11434"
    LITELLM_HOST_URL: str = "http://localhost:8000"
    LITELLM_API_KEY: Optional[str] = None

    REQUEST_TIMEOUT: int = 30  # Timeout for outgoing requests in seconds
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[str] = None
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT: int = 5

    @validator("CORS_ALLOWED_ORIGINS", pre=True, always=True)
    def _assemble_cors_origins(cls, v, values):
        if isinstance(v, list) and v: # If already populated (e.g. by direct init)
            return v
        origins_str = values.get("CORS_ALLOWED_ORIGINS_STR")
        if not origins_str:
            raise ValueError("CORS_ALLOWED_ORIGINS_STR environment variable is not set.")
        return [origin.strip() for origin in origins_str.split(',')]

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

# --- Context Variables ---
# For storing request-specific data like request_id
request_id_var: ContextVar[str] = ContextVar("request_id")

# --- Logging Setup ---
# Custom filter to add request_id to log records
class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get(None) # Get request_id, default to None if not set
        return True

def setup_logging(config: AppConfig):
    # log_format = '%(asctime)s - %(levelname)s - [%(request_id)s] - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s'
    log_format = '%(asctime)s - %(levelname)s - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s'
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(config.LOG_LEVEL.upper())
    root_logger.addFilter(RequestIdFilter()) # Add our custom filter

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    if not root_logger.handlers: # Add console handler if no handlers are configured yet
         root_logger.addHandler(console_handler)
    else: # Ensure console handler is present if other handlers (like uvicorn's) exist
        if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
            root_logger.addHandler(console_handler)


    # File Handler (if specified)
    if config.LOG_FILE:
        file_handler = logging.handlers.RotatingFileHandler(
            config.LOG_FILE,
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT
        )
        file_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(file_handler)

    # Adjust log levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING) # Uvicorn access logs can be noisy
    
    # Logger for this application
    return logging.getLogger(__name__)


# --- Initialize ---
try:
    load_dotenv() # Load .env before AppConfig tries to read it
    app_config = AppConfig()
    logger = setup_logging(app_config)
except ValueError as e:
    # Minimal logging for startup error
    logging.basicConfig(level=logging.ERROR)
    logging.error(f"Configuration error: {e}")
    exit(1)


# --- FastAPI Application ---
app = FastAPI(title="NApp.pro Proxy Server", version="1.0.0")

# --- HTTP Client ---
# Use a single client instance for connection pooling
if app_config.YACY_USERNAME and app_config.YACY_PASSWORD:
    auth = httpx.DigestAuth(app_config.YACY_USERNAME, app_config.YACY_PASSWORD)
else:
    auth = None
yacy_http_client = httpx.AsyncClient(auth=auth, timeout=app_config.REQUEST_TIMEOUT, follow_redirects=True)
meilisearch_http_client = httpx.AsyncClient(timeout=app_config.REQUEST_TIMEOUT, follow_redirects=True)
litellm_http_client = httpx.AsyncClient(timeout=app_config.REQUEST_TIMEOUT, follow_redirects=True)

@app.on_event("startup")
async def startup_event():
    logger.info("Application startup: Initializing HTTP client.")
    # Client is already initialized globally, could do more here if needed

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutdown: Closing HTTP client.")
    await yacy_http_client.aclose()
    await meilisearch_http_client.aclose()
    await litellm_http_client.aclose()


# --- Middleware ---
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    # Assign a unique ID to each request
    request_id = str(uuid.uuid4())
    request_id_var.set(request_id) # Set it in context var

    logger.info(f"Incoming request: {request.method} {request.url.path} from {request.client.host}")
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id # Optionally add to response headers
    logger.info(f"Outgoing response: Status {response.status_code} for {request.url.path}")
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_config.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"], # Allows all standard methods
    allow_headers=["*"], # Allows all headers
)


# --- Helper for Forwarding ---
async def _forward_request(
    target_url: str,
    request: Request,
    http_client: httpx.AsyncClient,
    # auth: Optional[Union[httpx.Auth, Dict[str, str]]] = None, # Can be httpx.Auth or custom headers
    auth: Optional[Dict[str, str]] = None, # Can be httpx.Auth or custom headers
    service_name: str = "upstream"
):
    try:
        content = await request.body()
        
        # Prepare headers for the outgoing request
        outgoing_headers = {
            k.lower(): v for k, v in request.headers.items()
            if k.lower() not in ['host', 'content-length', 'transfer-encoding', 'connection']
        }
        logger.debug(f"Original Headers: {outgoing_headers}")

        lower_auth = auth
        # If auth is a dict, it means custom headers (e.g., Bearer token)
        if isinstance(auth, dict):
            # convert keys to lowercase for auth
            lower_auth = {k.lower(): v for k, v in (auth if auth else {}).items()}
            # for k, v in auth.items():
            #     outgoing_headers[k] = v
            # # if we update then duplicate Bearer can be added to Authorization header
            outgoing_headers.update(lower_auth)
            auth_obj = None
        else: # It's an httpx.Auth object (e.g., DigestAuth)
            auth_obj = lower_auth
        logger.debug(f"Final Outgoing Headers: {outgoing_headers}")

        url = httpx.URL(target_url)
        
        # Construct the request to the target server
        rp_req = http_client.build_request(
            method=request.method,
            url=url,
            headers=outgoing_headers,
            content=content
            # auth=auth_obj # httpx.Auth object or None
        )
        
        logger.debug(f"Forwarding to {service_name}: {rp_req.method} {rp_req.url} Headers: {rp_req.headers}")
        logger.debug(f"Authorization: {rp_req.headers.get('Authorization')}")
        
        # Send the request and stream the response
        rp_resp = await http_client.send(rp_req, stream=True)
        
        logger.info(f"Response from {service_name} ({rp_req.url}): Status {rp_resp.status_code}")

        # Prepare response headers for the client
        response_headers = {
            k: v for k, v in rp_resp.headers.items()
            if k.lower() not in [
                'content-encoding', # Let server/client handle compression negotiation if possible
                'content-length',   # Will be set by StreamingResponse or client
                'transfer-encoding',# Handled by HTTPX/ASGI
                'connection'        # Hop-by-hop
            ]
        }
        # Our CORS middleware handles Access-Control-Allow-Origin, etc.
        # but if backend sends it, it might conflict. Generally prefer our middleware's.

        return StreamingResponse(
            rp_resp.aiter_bytes(),
            status_code=rp_resp.status_code,
            headers=response_headers,
            media_type=rp_resp.headers.get("content-type")
        )

    except httpx.TimeoutException:
        logger.error(f"Timeout connecting to {service_name} at {target_url}")
        raise HTTPException(status_code=504, detail=f"Gateway Timeout: {service_name} did not respond.")
    except httpx.ConnectError:
        logger.error(f"Connection error to {service_name} at {target_url}")
        raise HTTPException(status_code=502, detail=f"Bad Gateway: Could not connect to {service_name}.")
    except httpx.RequestError as e:
        logger.error(f"Request error with {service_name} at {target_url}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error proxying to {service_name}.")
    except Exception as e:
        logger.exception(f"Unexpected error proxying to {service_name} at {target_url}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error.")

# --- Yacy Proxy Endpoints ---
YACY_PREFIX = "/Crawler_p.html" # This is a specific file, not a prefix

@app.api_route(YACY_PREFIX, methods=["GET"]) # Yacy only supports GET for this endpoint based on original
async def proxy_yacy(request: Request):
    if not app_config.YACY_HOST_URL:
        logger.error("Yacy service not configured.")
        raise HTTPException(status_code=503, detail="Yacy Service Unavailable (Not Configured)")

    target_path = request.url.path # Should be /Crawler_p.html
    target_url = f"{app_config.YACY_HOST_URL.rstrip('/')}{target_path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # auth = None
    # if app_config.YACY_USERNAME and app_config.YACY_PASSWORD:
    #     auth = httpx.DigestAuth(app_config.YACY_USERNAME, app_config.YACY_PASSWORD)
    
    return await _forward_request(target_url, request, http_client=yacy_http_client, service_name="Yacy")


# --- Ollama-LiteLLM Proxy Endpoints ---
@app.api_route("/ollama-litellm/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_litellm(request: Request, path: str):
    if not app_config.LITELLM_HOST_URL or not app_config.OLLAMA_HOST_URL:
        logger.error("Ollama-LiteLLM service not configured.")
        raise HTTPException(status_code=503, detail="Ollama-LiteLLM Service Unavailable (Not Configured)")

    if path.startswith("v1/chat/completions") or path.startswith("v1/completions"):
        # Redirect to LiteLLM for these paths
        target_url = f"{app_config.LITELLM_HOST_URL.rstrip('/')}/{path}"
        if request.url.query:
            target_url += f"?{request.url.query}"

        auth_headers = {}
        if app_config.LITELLM_API_KEY:
            auth_headers["Authorization"] = f"Bearer {app_config.LITELLM_API_KEY}"
        else:
            logger.warning("LITELLM_API_KEY not set, LiteLLM request might fail.")
        
        return await _forward_request(target_url, request, http_client=litellm_http_client, auth=auth_headers, service_name="LiteLLM")
    
    # Otherwise, forward to Ollama
    target_url = f"{app_config.OLLAMA_HOST_URL.rstrip('/')}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    return await _forward_request(target_url, request, http_client=litellm_http_client, service_name="Ollama")


# --- LiteLLM Proxy Endpoints ---
@app.api_route("/litellm/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_litellm(request: Request, path: str):
    if not app_config.LITELLM_HOST_URL:
        logger.error("LiteLLM service not configured.")
        raise HTTPException(status_code=503, detail="LiteLLM Service Unavailable (Not Configured)")

    target_url = f"{app_config.LITELLM_HOST_URL.rstrip('/')}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    auth_headers = {}
    if app_config.LITELLM_API_KEY:
        auth_headers["Authorization"] = f"Bearer {app_config.LITELLM_API_KEY}"
    else:
        logger.warning("LITELLM_API_KEY not set, LiteLLM request might fail.")
    
    return await _forward_request(target_url, request, http_client=litellm_http_client, auth=auth_headers, service_name="LiteLLM")


# --- Meilisearch Proxy Endpoints ---
MEILI_PATHS = [
    "/indexes",             # POST, GET
    "/indexes/{index_uid:path}", # GET, POST, PUT, PATCH, DELETE
    "/version",             # GET
    "/health",              # GET
    "/stats",               # GET
]

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_meilisearch_or_others(request: Request, path: str):
    full_path = f"/{path}"
    if request.url.query:
        full_path += f"?{request.url.query}"

    # Determine if it's a Meilisearch path
    # This routing is a bit simplistic. For more complex scenarios, APIRouters would be better.
    is_meili_path = False
    if full_path.startswith("/indexes"): # Handles /indexes and /indexes/...
        is_meili_path = True
    elif full_path in ["/version", "/health", "/stats"]:
        is_meili_path = True
    
    if is_meili_path:
        if not app_config.MEILISEARCH_HOST_URL:
            logger.error("Meilisearch service not configured.")
            raise HTTPException(status_code=503, detail="Meilisearch Service Unavailable (Not Configured)")

        target_url = f"{app_config.MEILISEARCH_HOST_URL.rstrip('/')}{full_path}"
        
        auth_headers = {}
        if app_config.MEILISEARCH_API_KEY:
            auth_headers["Authorization"] = f"Bearer {app_config.MEILISEARCH_API_KEY}"
        else:
            logger.warning("MEILISEARCH_API_KEY not set, Meilisearch request might fail.")
        
        return await _forward_request(target_url, request, http_client=meilisearch_http_client, auth=auth_headers, service_name="Meilisearch")
    
    # If not Yacy and not Meili, it's a 404 (as per original logic)
    logger.warning(f"Path not found by proxy: {full_path}")
    raise HTTPException(status_code=404, detail="Not Found by Proxy")


# --- Main execution (for running with uvicorn directly) ---
if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting NApp.pro Proxy Server on http://{app_config.PROXY_HOST}:{app_config.PROXY_PORT}")
    logger.info(f"Allowed CORS origins: {app_config.CORS_ALLOWED_ORIGINS}")
    if app_config.YACY_HOST_URL:
        logger.info(f"Yacy backend: {app_config.YACY_HOST_URL}")
    if app_config.MEILISEARCH_HOST_URL:
        logger.info(f"Meilisearch backend: {app_config.MEILISEARCH_HOST_URL}")
    if app_config.LITELLM_HOST_URL:
        logger.info(f"LiteLLM backend: {app_config.LITELLM_HOST_URL}")
    if app_config.OLLAMA_HOST_URL:
        logger.info(f"Ollama backend: {app_config.OLLAMA_HOST_URL}")
    
    uvicorn.run(
        "fastapi_proxy:app", # app object in fastapi_proxy.py
        host=app_config.PROXY_HOST,
        port=app_config.PROXY_PORT,
        log_level=app_config.LOG_LEVEL.lower(), # Uvicorn has its own log level
        reload=True # For development, disable in production
    )