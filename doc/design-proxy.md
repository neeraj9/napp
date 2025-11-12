# Proxy Server - Design Document

## 1. Overview

### 1.1 Purpose
The Proxy Server is a unified API gateway that provides a single entry point for multiple backend services including YaCy (web search), Meilisearch (document search), Ollama (local LLM), and LiteLLM (LLM proxy). It handles authentication, CORS, request routing, and provides comprehensive logging for all proxied requests.

### 1.2 Key Features
- **Multi-service proxy**: Routes requests to YaCy, Meilisearch, Ollama, and LiteLLM
- **Authentication management**: Handles Digest Auth (YaCy) and Bearer token authentication (Meilisearch, LiteLLM)
- **CORS support**: Configurable cross-origin resource sharing for web applications
- **Request tracking**: Unique request ID generation and tracking throughout request lifecycle
- **Streaming support**: Efficient streaming of responses for large payloads
- **Comprehensive logging**: Rotating file logs with configurable levels
- **Error handling**: Proper HTTP error codes and timeout management

### 1.3 Technology Stack
- **Framework**: FastAPI 
- **HTTP Client**: httpx (async)
- **Configuration**: Pydantic Settings with .env support
- **Server**: Uvicorn (ASGI server)
- **Python Version**: 3.7+

---

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────┐
│   Client    │
│ (Browser/   │
│   App)      │
└──────┬──────┘
       │ HTTP Request
       │
       ▼
┌─────────────────────────────────────┐
│    Proxy Server                     │
│    (FastAPI + Uvicorn)              │
│                                     │
│  ┌──────────────────────────────┐   │
│  │  Middleware Layer            │   │
│  │  - Request ID Generation     │   │
│  │  - CORS Handler              │   │
│  │  - Logging                   │   │
│  └──────────────────────────────┘   │
│                                     │
│  ┌──────────────────────────────┐   │
│  │  Routing Layer               │   │
│  │  - Path-based routing        │   │
│  │  - Service detection         │   │
│  └──────────────────────────────┘   │
│                                     │
│  ┌──────────────────────────────┐   │
│  │  Forwarding Layer            │   │
│  │  - Request transformation    │   │
│  │  - Authentication injection  │   │
│  │  - Response streaming        │   │
│  └──────────────────────────────┘   │
└─────────┬─────┬───────┬─────────┬───┘
          │     │       │         │
          ▼     ▼       ▼         ▼
       ┌────┐ ┌─────┐ ┌──────┐ ┌────────┐
       │YaCy│ │Meili│ │Ollama│ │LiteLLM │
       └────┘ └─────┘ └──────┘ └────────┘
```

### 2.2 Component Architecture

#### 2.2.1 Configuration Layer
- **AppConfig**: Pydantic-based settings class
- **Environment Loading**: `.env` file support
- **Validation**: Automatic configuration validation on startup

#### 2.2.2 Middleware Layer
- **Request ID Middleware**: Assigns UUID to each request
- **CORS Middleware**: Handles cross-origin requests
- **Logging Middleware**: Logs request/response cycle

#### 2.2.3 HTTP Client Layer
- **Connection Pooling**: Separate httpx clients per service
- **Authentication**: Pre-configured auth for each service
- **Timeout Management**: Configurable request timeouts
- **Connection Lifecycle**: Managed startup/shutdown

#### 2.2.4 Routing Layer
- **Path-based Routing**: Different endpoints for each service
- **Service Detection**: Intelligent path matching
- **HTTP Method Support**: GET, POST, PUT, PATCH, DELETE, OPTIONS

---

## 3. Detailed Component Design

### 3.1 Configuration (AppConfig)

#### 3.1.1 Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `PROXY_HOST` | str | localhost | Proxy server host |
| `PROXY_PORT` | int | 8882 | Proxy server port |
| `CORS_ALLOWED_ORIGINS_STR` | str | Required | Comma-separated allowed origins |
| `YACY_HOST_URL` | str | None | YaCy server URL |
| `YACY_USERNAME` | str | None | YaCy Digest Auth username |
| `YACY_PASSWORD` | str | None | YaCy Digest Auth password |
| `MEILISEARCH_HOST_URL` | str | None | Meilisearch server URL |
| `MEILISEARCH_API_KEY` | str | None | Meilisearch API key |
| `OLLAMA_HOST_URL` | str | http://localhost:11434 | Ollama server URL |
| `LITELLM_HOST_URL` | str | http://localhost:8000 | LiteLLM server URL |
| `LITELLM_API_KEY` | str | None | LiteLLM API key |
| `REQUEST_TIMEOUT` | int | 30 | Request timeout in seconds |
| `LOG_LEVEL` | str | INFO | Logging level |
| `LOG_FILE` | str | None | Log file path (optional) |
| `LOG_MAX_BYTES` | int | 10485760 | Max log file size (10MB) |
| `LOG_BACKUP_COUNT` | int | 5 | Number of backup log files |

#### 3.1.2 Configuration Loading
```python
# Order of precedence:
1. Environment variables
2. .env file
3. Default values
```

#### 3.1.3 Static Configuration Files

| File | Purpose | Location |
|------|---------|----------|
| `lightllm_api_version.json` | Ollama API version response | `tools/config/` |
| `lightllm_api_tags.json` | Ollama API models/tags response | `tools/config/` |

These files are loaded at startup and served for `/ollama-litellm/api/version` and `/ollama-litellm/api/tags` endpoints respectively.

### 3.2 Logging System

#### 3.2.1 Log Format
```
%(asctime)s - %(levelname)s - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s
```

#### 3.2.2 Log Handlers
- **Console Handler**: Always active for development
- **Rotating File Handler**: Optional, with size-based rotation
- **Request ID Filter**: Custom filter for request tracking (prepared but not currently in format)

#### 3.2.3 Log Levels by Component
- Application logs: Configurable (default: INFO)
- httpx: WARNING
- httpcore: WARNING  
- uvicorn.access: WARNING

### 3.3 Request Forwarding Mechanism

#### 3.3.1 Request Flow
```
1. Receive incoming request
2. Extract request body and headers
3. Filter hop-by-hop headers
4. Add authentication headers
5. Build target URL
6. Create httpx request
7. Send request to backend
8. Stream response back to client
```

#### 3.3.2 Header Handling

**Filtered Headers (not forwarded):**
- `host`
- `content-length`
- `transfer-encoding`
- `connection`

**Filtered Response Headers:**
- `content-encoding`
- `content-length`
- `transfer-encoding`
- `connection`

#### 3.3.3 Authentication Injection

**YaCy:**
- Type: HTTP Digest Authentication
- Configuration: Pre-configured in httpx client
- Headers: Managed by httpx.DigestAuth

**Meilisearch:**
- Type: Bearer Token
- Header: `Authorization: Bearer <MEILISEARCH_API_KEY>`
- Injection: Added to request headers

**LiteLLM:**
- Type: Bearer Token
- Header: `Authorization: Bearer <LITELLM_API_KEY>`
- Injection: Added to request headers

**Ollama:**
- Type: None (no authentication required)

### 3.4 Error Handling

#### 3.4.1 Error Types and HTTP Status Codes

| Error Type | HTTP Status | Description |
|------------|-------------|-------------|
| Service not configured | 503 | Backend service URL not set |
| Timeout | 504 | Gateway timeout from backend |
| Connection error | 502 | Cannot connect to backend |
| Request error | 500 | Error during request processing |
| Unknown error | 500 | Unexpected exception |
| Path not found | 404 | No matching route |

#### 3.4.2 Error Response Format
```json
{
  "detail": "Error message description"
}
```

---

## 4. API Endpoints

### 4.1 YaCy Proxy

**Endpoint:** `/Crawler_p.html`

**Methods:** GET

**Purpose:** Proxy requests to YaCy web crawler interface

**Authentication:** Digest Auth (automatic)

**Example:**
```
GET /Crawler_p.html?action=crawlStart
→ Proxied to: {YACY_HOST_URL}/Crawler_p.html?action=crawlStart
```

### 4.2 Ollama-LiteLLM Proxy

**Endpoint:** `/ollama-litellm/{path:path}`

**Methods:** GET, POST, PUT, PATCH, DELETE, OPTIONS

**Purpose:** Intelligent routing between Ollama and LiteLLM, which can be used
within github copilot via visual studio code. We are basically fooling github copilot
in thinking that its talking to Ollama when its talking to LiteLLM.

Github copilot needs at least the following interfaces from Ollama:

- GET /ollama-litellm/api/version (served from static JSON file)
- GET /ollama-litellm/api/tags (served from static JSON file)
- POST http://localhost:8000/v1/chat/completions
- Other calls are forwarded to Ollama

Note:
- api/tags is served from static json file for tighter control and allow serving non-ollama models as well.

The default port used by proxy is 8882, so we can setup
ollama endpoint as follows.

```json file:settings.json
{
    "github.copilot.chat.byok.ollamaEndpoint": "http://localhost:8882/ollama-litellm"
}
```

**Routing Logic:**
- Paths `api/version` → Static JSON response from `tools/config/lightllm_api_version.json`
- Paths `api/tags` → Static JSON response from `tools/config/lightllm_api_tags.json`
- Paths starting with `v1/chat/completions` → LiteLLM
- Paths starting with `v1/completions` → LiteLLM
- All other paths → Ollama

**Authentication:** 
- LiteLLM: Bearer token (if configured)
- Ollama: None

**Examples:**
```
POST /ollama-litellm/v1/chat/completions
→ Proxied to: {LITELLM_HOST_URL}/v1/chat/completions

POST /ollama-litellm/api/generate
→ Proxied to: {OLLAMA_HOST_URL}/api/generate
```

### 4.3 LiteLLM Proxy

**Endpoint:** `/litellm/{path:path}`

**Methods:** GET, POST, PUT, PATCH, DELETE, OPTIONS

**Purpose:** Direct proxy to LiteLLM service

**Authentication:** Bearer token (if configured)

**Example:**
```
POST /litellm/v1/models
→ Proxied to: {LITELLM_HOST_URL}/v1/models
```

### 4.4 Meilisearch Proxy

**Endpoint:** Multiple paths

**Methods:** GET, POST, PUT, PATCH, DELETE

**Supported Paths:**
- `/indexes` - Index management
- `/indexes/{index_uid}` - Specific index operations
- `/version` - Server version
- `/health` - Health check
- `/stats` - Server statistics

**Authentication:** Bearer token (if configured)

**Examples:**
```
GET /indexes
→ Proxied to: {MEILISEARCH_HOST_URL}/indexes

POST /indexes/movies/search
→ Proxied to: {MEILISEARCH_HOST_URL}/indexes/movies/search
```

### 4.5 Routing Priority

```
1. /Crawler_p.html → YaCy
2. /ollama-litellm/* → Ollama/LiteLLM (intelligent routing)
3. /litellm/* → LiteLLM
4. /indexes*, /version, /health, /stats → Meilisearch
5. * → 404 Not Found
```

---

## 5. Request Lifecycle

### 5.1 Detailed Request Flow

```
┌─────────────────────────────────────────────────────────┐
│ 1. Client sends HTTP request                            │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Request ID Middleware                                │
│    - Generate UUID                                      │
│    - Store in context variable                          │
│    - Log incoming request                               │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 3. CORS Middleware                                      │
│    - Check origin against allowed origins               │
│    - Add CORS headers to response                       │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 4. Route Matching                                       │
│    - Match path to service endpoint                     │
│    - Check for static response paths (api/version, tags)│
│    - Check if service is configured                     │
│    - Return 503 if not configured                       │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Static Response OR Request Transformation            │
│    - If static path: Return loaded JSON data            │
│    - Otherwise: Continue with request forwarding        │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 6. Backend Request                                      │
│    - Build httpx request                                │
│    - Send via appropriate httpx client                  │
│    - Handle connection pooling                          │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 7. Response Streaming                                   │
│    - Receive backend response                           │
│    - Filter response headers                            │
│    - Stream response chunks to client                   │
└──────────────────┬──────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ 8. Response Completion                                  │
│    - Add X-Request-ID header                            │
│    - Log response status                                │
│    - Return to client                                   │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Error Handling Flow

```
                   [Error Occurs]
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    Timeout         ConnectError    RequestError
         │               │               │
         ▼               ▼               ▼
    504 Gateway    502 Bad Gateway  500 Internal
     Timeout                          Server Error
         │               │               │
         └───────────────┴───────────────┘
                         │
                         ▼
              Log error with context
                         │
                         ▼
            Return HTTPException to client
```

---

## 6. Security Considerations

### 6.1 Authentication Security
- **Credential Storage**: All credentials stored in .env file (not in code)
- **Digest Auth**: Used for YaCy (more secure than Basic Auth)
- **Bearer Tokens**: Used for Meilisearch and LiteLLM
- **Token Rotation**: Supported via environment variable updates

### 6.2 CORS Security
- **Whitelist Only**: Only explicitly allowed origins can access the proxy
- **No Wildcards**: Origins must be explicitly listed
- **Credentials Support**: Allows cookies and auth headers when needed

### 6.3 Header Security
- **Header Filtering**: Removes potentially dangerous hop-by-hop headers
- **Host Header**: Not forwarded to prevent host header injection
- **X-Request-ID**: Adds request tracking without exposing internal info

### 6.4 Error Message Security
- **Generic Errors**: Internal errors return generic messages
- **No Stack Traces**: Stack traces only logged, not returned to clients
- **Service Hiding**: Backend service details not exposed in errors

### 6.5 Potential Security Improvements
1. **Rate Limiting**: Add per-client rate limiting
2. **API Keys**: Add proxy-level API key authentication
3. **Request Validation**: Validate request bodies before forwarding
4. **IP Whitelisting**: Restrict access by client IP
5. **TLS/HTTPS**: Enforce HTTPS for all connections
6. **Secret Management**: Use secret management service instead of .env

---

## 7. Performance Considerations

### 7.1 Connection Pooling
- **Shared Clients**: One httpx.AsyncClient per backend service
- **Connection Reuse**: HTTP/1.1 connection pooling enabled
- **Keep-Alive**: Connections kept alive between requests

### 7.2 Streaming
- **Response Streaming**: Large responses streamed chunk-by-chunk
- **Memory Efficiency**: Avoids loading entire response into memory
- **Backpressure**: Automatic flow control between backend and client

### 7.3 Async Architecture
- **Non-blocking I/O**: All network operations are async
- **Concurrent Requests**: Multiple requests handled concurrently
- **Event Loop**: Uvicorn's efficient ASGI event loop

### 7.4 Timeout Management
- **Configurable Timeout**: Default 30 seconds, adjustable
- **Gateway Timeout**: Returns 504 if backend times out
- **Client Timeout**: Handled by client's timeout settings

### 7.5 Performance Metrics

**Expected Throughput:**
- Simple requests: 1000+ req/sec
- Streaming requests: Limited by backend speed
- Concurrent connections: 100+ (Uvicorn default)

**Latency Overhead:**
- Proxy overhead: ~1-5ms
- Auth header injection: ~0.1ms
- Logging: ~0.5ms

---

## 8. Deployment

### 8.1 Environment Setup

**Virtual Environment:**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

**Dependencies:**
```bash
pip install python-dotenv requests
pip install "fastapi[all]" uvicorn python-dotenv httpx pydantic-settings
```

### 8.2 Configuration File (.env)

```env
# Proxy Configuration
PROXY_HOST=localhost
PROXY_PORT=8882

# CORS Configuration
CORS_ALLOWED_ORIGINS_STR=http://localhost:3000,http://localhost:8080

# YaCy Configuration (optional)
YACY_HOST_URL=http://localhost:8090
YACY_USERNAME=admin
YACY_PASSWORD=yourpassword

# Meilisearch Configuration (optional)
MEILISEARCH_HOST_URL=http://localhost:7700
MEILISEARCH_API_KEY=your-meilisearch-key

# Ollama Configuration
OLLAMA_HOST_URL=http://localhost:11434

# LiteLLM Configuration
LITELLM_HOST_URL=http://localhost:8000
LITELLM_API_KEY=your-litellm-key

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=logs/proxy.log
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5

# Request Configuration
REQUEST_TIMEOUT=30
```

### 8.3 Running the Server

**Development Mode:**
```bash
uvicorn proxy:app --host localhost --port 8882 --reload
```

**Production Mode:**
```bash
uvicorn proxy:app --host 0.0.0.0 --port 8882 --workers 4
```

**Using Python Directly:**
```bash
python proxy.py
```

### 8.4 Docker Deployment

**Dockerfile Example:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proxy.py .
COPY .env .

EXPOSE 8882

CMD ["uvicorn", "proxy:app", "--host", "0.0.0.0", "--port", "8882"]
```

**Docker Compose Example:**
```yaml
version: '3.8'
services:
  proxy:
    build: .
    ports:
      - "8882:8882"
    environment:
      - PROXY_HOST=0.0.0.0
      - PROXY_PORT=8882
    env_file:
      - .env
    restart: unless-stopped
```

### 8.5 Production Considerations

1. **Workers**: Use multiple workers for better concurrency
   ```bash
   uvicorn proxy:app --workers 4
   ```

2. **Reverse Proxy**: Place behind Nginx or Traefik
   - SSL/TLS termination
   - Load balancing
   - Additional security headers

3. **Process Manager**: Use systemd or supervisor
   - Auto-restart on failure
   - Logging to syslog
   - Resource limits

4. **Monitoring**: Add health check endpoint
   ```python
   @app.get("/health")
   async def health():
       return {"status": "healthy"}
   ```

---

## 9. Testing

### 9.1 Unit Testing Strategy

**Test Categories:**
1. Configuration loading and validation
2. Request ID generation and tracking
3. Header filtering and transformation
4. Authentication header injection
5. Error handling for each error type
6. CORS header generation

### 9.2 Integration Testing

**Test Scenarios:**
1. YaCy proxy with Digest Auth
2. Meilisearch proxy with Bearer token
3. Ollama-LiteLLM routing logic
4. Streaming large responses
5. Timeout handling
6. Connection error handling

### 9.3 Testing Tools

```bash
# Install testing dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/
```

### 9.4 Manual Testing Examples

**Test YaCy Proxy:**
```bash
curl -X GET "http://localhost:8882/Crawler_p.html?action=status"
```

**Test Meilisearch Proxy:**
```bash
curl -X GET "http://localhost:8882/health"
curl -X GET "http://localhost:8882/indexes"
```

**Test Ollama:**
```bash
curl -X POST "http://localhost:8882/ollama-litellm/api/generate" \
  -H "Content-Type: application/json" \
  -d '{"model":"llama2","prompt":"Hello"}'
```

**Test LiteLLM:**
```bash
curl -X POST "http://localhost:8882/ollama-litellm/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"gpt-3.5-turbo",
    "messages":[{"role":"user","content":"Hello"}]
  }'
```

---

## 10. Monitoring and Logging

### 10.1 Log Levels

| Level | Usage |
|-------|-------|
| DEBUG | Detailed header inspection, request/response details |
| INFO | Request/response logging, startup/shutdown events |
| WARNING | Missing API keys, configuration warnings |
| ERROR | Connection failures, timeouts, request errors |
| CRITICAL | Startup failures, configuration errors |

### 10.2 Key Log Messages

**Startup:**
```
Starting Proxy Server on http://localhost:8882
Yacy backend: http://localhost:8090
Meilisearch backend: http://localhost:7700
```

**Request/Response:**
```
Incoming request: POST /indexes/movies/search from 127.0.0.1
Response from Meilisearch (http://localhost:7700/indexes/movies/search): Status 200
Outgoing response: Status 200 for /indexes/movies/search
```

**Errors:**
```
Timeout connecting to Meilisearch at http://localhost:7700/indexes
Connection error to Ollama at http://localhost:11434/api/generate
```

### 10.3 Monitoring Recommendations

1. **Application Metrics:**
   - Request rate per endpoint
   - Response time percentiles (p50, p95, p99)
   - Error rate by service
   - Active connections

2. **Infrastructure Metrics:**
   - CPU usage
   - Memory usage
   - Network I/O
   - Open file descriptors

3. **Business Metrics:**
   - Requests per service
   - Authentication failures
   - CORS rejections

### 10.4 Log Aggregation

**Recommended Tools:**
- ELK Stack (Elasticsearch, Logstash, Kibana)
- Grafana Loki
- CloudWatch Logs (AWS)
- Google Cloud Logging

---

## 11. Troubleshooting

### 11.1 Common Issues

**Issue: CORS errors in browser**
- Check `CORS_ALLOWED_ORIGINS_STR` includes client origin
- Verify no trailing slashes in origin URLs
- Check browser console for exact error

**Issue: 503 Service Unavailable**
- Verify backend service URL is configured in .env
- Check if backend service is running
- Test backend service directly

**Issue: 504 Gateway Timeout**
- Increase `REQUEST_TIMEOUT` value
- Check backend service performance
- Verify network connectivity to backend

**Issue: Authentication failures**
- Verify credentials in .env file
- Check credential format (Digest Auth vs Bearer)
- Test credentials directly with backend service

**Issue: 502 Bad Gateway**
- Check if backend service is accessible
- Verify backend service URL is correct
- Check firewall rules

### 11.2 Debug Mode

Enable detailed logging:
```env
LOG_LEVEL=DEBUG
```

This will show:
- All request headers
- All response headers
- Authorization headers
- Detailed routing decisions

### 11.3 Health Checks

**Check proxy is running:**
```bash
curl http://localhost:8882/health  # If health endpoint is added
```

**Check backend services:**
```bash
# YaCy
curl http://localhost:8090/status.html

# Meilisearch
curl http://localhost:7700/health

# Ollama
curl http://localhost:11434/api/tags

# LiteLLM
curl http://localhost:8000/health
```

---

## 12. Future Enhancements

### 12.1 Planned Features

1. **Health Check Endpoint**
   - Endpoint to check proxy status
   - Backend service health aggregation
   - Kubernetes readiness/liveness probes

2. **Metrics Endpoint**
   - Prometheus-compatible metrics
   - Request counters by service
   - Response time histograms

3. **Rate Limiting**
   - Per-client rate limiting
   - Per-endpoint rate limiting
   - Token bucket algorithm

4. **Caching Layer**
   - Cache GET requests
   - Configurable TTL
   - Redis backend support

5. **Request/Response Transformation**
   - Request body modification
   - Response body transformation
   - Header rewriting rules

6. **Circuit Breaker**
   - Auto-disable failing backends
   - Exponential backoff
   - Health check recovery

7. **Advanced Routing**
   - Load balancing across multiple backends
   - Weighted routing
   - A/B testing support

8. **Authentication Gateway**
   - Single sign-on integration
   - JWT validation
   - OAuth2 proxy

### 12.2 API Router Refactoring

Current implementation uses simple path matching. Future version should use FastAPI's APIRouter:

```python
# Proposed structure
from fastapi import APIRouter

yacy_router = APIRouter(prefix="/yacy", tags=["yacy"])
meili_router = APIRouter(prefix="/meili", tags=["meilisearch"])
ollama_router = APIRouter(prefix="/ollama", tags=["ollama"])
litellm_router = APIRouter(prefix="/litellm", tags=["litellm"])

app.include_router(yacy_router)
app.include_router(meili_router)
app.include_router(ollama_router)
app.include_router(litellm_router)
```

Benefits:
- Cleaner code organization
- Better OpenAPI documentation
- Easier testing
- Independent versioning per service

---

## 13. References

### 13.1 Dependencies Documentation
- [FastAPI](https://fastapi.tiangolo.com/)
- [httpx](https://www.python-httpx.org/)
- [Pydantic](https://docs.pydantic.dev/)
- [Uvicorn](https://www.uvicorn.org/)

### 13.2 Backend Services
- [YaCy](https://yacy.net/)
- [Meilisearch](https://www.meilisearch.com/)
- [Ollama](https://ollama.ai/)
- [LiteLLM](https://docs.litellm.ai/)

### 13.3 Related Documentation
- `readme-proxy.md` - User guide and quick start
- `.env.example` - Example configuration file

---

## 14. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-01 | Initial implementation with all four service proxies |

---

## 15. Contributing

### 15.1 Code Style
- Follow PEP 8 guidelines
- Use type hints
- Add docstrings to functions
- Keep functions focused and small

### 15.2 Testing Requirements
- Add unit tests for new features
- Maintain >80% code coverage
- Add integration tests for new endpoints

### 15.3 Documentation Requirements
- Update this design document for architectural changes
- Update readme-proxy.md for user-facing changes
- Add inline comments for complex logic

---

## License
MIT License (c) 2025 Neeraj Sharma
