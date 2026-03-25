# API Client Base

Abstract, reusable base class for building and authenticating external service API clients (OpenAI, Telegram, Stripe, GitHub, and any REST API).

Provides a unified interface for HTTP communication, authentication, request routing, rate limiting, retries, response normalization, and error handling — so that concrete clients only need to define endpoints and business logic.

## Why This Package

Building API clients from scratch means re-implementing the same boilerplate every time: authentication, retries, rate limiting, error mapping, logging. This package extracts all of that into an abstract foundation:

- **Write less code** — a concrete client is ~30 lines, not 300.
- **Consistent behavior** — every client you build gets retries, circuit breakers, and structured errors for free.
- **Swap auth schemes** — go from API key to OAuth2 by changing one line.
- **Optional integrations** — plug in caching, structured logging, or alerting without coupling to them.

## Quick Start

### 1. Clone and set up

```bash
git clone <repo-url>
cd API_Base_cl

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the required dependency
pip install httpx

# Install optional sibling packages (from the Dependencies/ directory)
pip install Dependencies/cache_manager-0.1.0-py3-none-any.whl
pip install Dependencies/logger_pkg-0.1.0-py3-none-any.whl
pip install Dependencies/error_exception_handler-0.1.0-py3-none-any.whl
```

### 2. Build a concrete client

```python
from api_client_base import (
    AsyncAPIClient, APIKeyAuth, EndpointDefinition, APIClientConfig
)

class OpenAIClient(AsyncAPIClient):
    """Concrete client for the OpenAI API."""

    def __init__(self, api_key: str):
        config = APIClientConfig(
            base_url="https://api.openai.com",
            api_version="v1",
            auth_strategy=APIKeyAuth(
                api_key=api_key,
                header_name="Authorization",
                prefix="Bearer",
            ),
            timeout=60.0,
            max_retries=3,
        )
        super().__init__(config)

        self.endpoints.register(EndpointDefinition(
            name="create_completion",
            path="/chat/completions",
            method="POST",
        ))
        self.endpoints.register(EndpointDefinition(
            name="list_models",
            path="/models",
            method="GET",
            cache_ttl=3600,
        ))

    async def create_completion(self, model: str, messages: list) -> dict:
        ep = self.endpoints.get("create_completion")
        response = await self.request(ep.method, ep.path, json={
            "model": model, "messages": messages,
        })
        return response.body

    async def list_models(self) -> list:
        ep = self.endpoints.get("list_models")
        response = await self.request(ep.method, ep.path)
        return response.body["data"]
```

### 3. Use the client

```python
import asyncio

async def main():
    async with OpenAIClient(api_key="sk-...") as client:
        models = await client.list_models()
        print(models)

        result = await client.create_completion(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(result)

asyncio.run(main())
```

### 4. Synchronous usage

For codebases that don't use asyncio, use `SyncAPIClient` instead:

```python
from api_client_base import SyncAPIClient, APIKeyAuth, APIClientConfig

class MySyncClient(SyncAPIClient):
    def __init__(self, api_key: str):
        config = APIClientConfig(
            base_url="https://api.example.com",
            auth_strategy=APIKeyAuth(api_key=api_key),
        )
        super().__init__(config)

    def get_users(self) -> list:
        response = self.request_sync("GET", "/users")
        return response.body

# Usage — standard context manager, no async needed
with MySyncClient(api_key="key-123") as client:
    users = client.get_users()
```

## Authentication Strategies

The package ships with four auth strategies. Pick the one that matches your API:

### API Key (most common)

```python
from api_client_base import APIKeyAuth, AuthLocation

# Header-based (default): Authorization: Bearer sk-...
auth = APIKeyAuth(api_key="sk-...", prefix="Bearer")

# Custom header: X-API-Key: sk-...
auth = APIKeyAuth(api_key="sk-...", header_name="X-API-Key", prefix=None)

# Query parameter: ?api_key=sk-...
auth = APIKeyAuth(api_key="sk-...", location=AuthLocation.QUERY, param_name="api_key")
```

### Bearer Token (with optional refresh)

```python
from api_client_base import BearerTokenAuth

# Static token
auth = BearerTokenAuth(token="my-jwt-token")

# Auto-refreshing token
async def refresh_token():
    # Call your token endpoint
    return ("new-token", time.time() + 3600)

auth = BearerTokenAuth(
    token="initial-token",
    expires_at=time.time() + 3600,
    refresh_callback=refresh_token,
    refresh_buffer=30.0,  # refresh 30s before expiry
)
```

### OAuth2

```python
from api_client_base import OAuth2Auth, OAuth2Flow

# Client credentials (machine-to-machine)
auth = OAuth2Auth(
    token_url="https://auth.example.com/oauth/token",
    client_id="my-client-id",
    client_secret="my-secret",
    flow=OAuth2Flow.CLIENT_CREDENTIALS,
    scopes=["read", "write"],
)

# Authorization code (user-delegated, with pre-obtained tokens)
auth = OAuth2Auth(
    token_url="https://auth.example.com/oauth/token",
    client_id="my-client-id",
    client_secret="my-secret",
    flow=OAuth2Flow.AUTHORIZATION_CODE,
    access_token="existing-access-token",
    refresh_token_value="existing-refresh-token",
)
```

### Custom (HMAC, SigV4, etc.)

```python
from api_client_base import CustomAuth
import hmac, hashlib

async def hmac_signer(request):
    body_bytes = str(request.body or "").encode()
    sig = hmac.new(b"secret-key", body_bytes, hashlib.sha256).hexdigest()
    request.headers["X-Signature"] = sig
    return request

auth = CustomAuth(authenticate_fn=hmac_signer, name="hmac-sha256")
```

## Resilience

All resilience features are configured through `APIClientConfig` and work automatically:

```python
from api_client_base import (
    APIClientConfig, RateLimitConfig, CircuitBreakerConfig, RetryBackoff
)

config = APIClientConfig(
    base_url="https://api.example.com",

    # Retry — automatic retries on 429, 5xx, timeouts, and connection errors
    max_retries=3,
    retry_backoff=RetryBackoff.EXPONENTIAL_JITTER,
    retry_base_delay=1.0,
    retry_max_delay=60.0,

    # Rate limiting — token bucket, respects X-RateLimit-* headers
    rate_limit=RateLimitConfig(
        max_requests=60,
        period_seconds=60.0,
        per_endpoint=False,
    ),

    # Circuit breaker — fail-fast when the API is down
    circuit_breaker=CircuitBreakerConfig(
        failure_threshold=5,       # open after 5 consecutive failures
        recovery_timeout=30.0,     # probe after 30s
        success_threshold=2,       # close after 2 successes in half-open
    ),

    # Timeouts
    timeout=30.0,
    connect_timeout=10.0,
)
```

### Endpoint Registry

Declare endpoints once, reference them by name:

```python
from api_client_base import EndpointDefinition

# Register with path parameters
self.endpoints.register(EndpointDefinition(
    name="get_user",
    path="/users/{user_id}",
    method="GET",
    group="users",
    cache_ttl=300,
    timeout=10.0,
))

# Resolve path parameters
ep = self.endpoints.resolve("get_user", user_id=42)
# ep.path → "/users/42"
```

### Middleware

Add cross-cutting behavior to every request:

```python
from api_client_base import IdempotencyMiddleware, TimingMiddleware

client.middleware.add(IdempotencyMiddleware())  # auto Idempotency-Key on POST/PUT/PATCH
client.middleware.add(TimingMiddleware())        # timing metadata on every request
```

Write custom middleware by subclassing `RequestMiddleware`:

```python
from api_client_base import RequestMiddleware, APIRequest, APIResponse

class MyLoggingMiddleware(RequestMiddleware):
    async def before_request(self, request: APIRequest) -> APIRequest:
        print(f"→ {request.method} {request.url}")
        return request

    async def after_response(self, response: APIResponse, request: APIRequest) -> APIResponse:
        print(f"← {response.status_code} ({response.elapsed_ms:.0f}ms)")
        return response
```

### Lifecycle Hooks

Override hooks in your concrete client for custom behavior:

```python
class MyClient(AsyncAPIClient):
    async def pre_request(self, request):
        request.headers["X-Request-ID"] = str(uuid.uuid4())
        return request

    async def post_response(self, response):
        if response.status_code == 200:
            self.stats["success"] += 1
        return response

    async def on_error(self, error, request):
        print(f"Error on {request.url}: {error}")
```

## Error Handling

Every HTTP error is mapped to a typed exception:

| Status Code | Exception | Retryable |
|-------------|-----------|-----------|
| 400 / 422 | `ValidationError` | No |
| 401 | `AuthenticationError` | No |
| 403 | `AuthorizationError` | No |
| 404 | `NotFoundError` | No |
| 429 | `RateLimitError` | Yes |
| 5xx | `ServerError` | Yes |
| Timeout | `APITimeoutError` | Yes |
| Network | `APIConnectionError` | Yes |
| Circuit open | `CircuitOpenError` | No |

```python
from api_client_base import RateLimitError, AuthenticationError

try:
    response = await client.post("/data", json=payload)
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after}s")
except AuthenticationError:
    print("Invalid API key — check your credentials")
```

## Optional Integrations

The package integrates with sibling packages in this repository. Each integration is optional and degrades gracefully if the dependency is not installed.

| Integration | Sibling Package | What It Does |
|-------------|----------------|--------------|
| **Caching** | `Cache_Manager` | Cache API responses with namespace isolation and deterministic keys |
| **Logging** | `Logger_Package` | Structured logging with per-request context, PII redaction |
| **Error Normalization** | `Error-Exception_Handler` | Map API errors to the project's unified `BaseAppException` format |
| **Alerting** | `Notification_Manager` | Throttled alerts on circuit breaker trips, auth failures, rate limits |

### Caching example

```python
from api_client_base.integrations.cache_integration import create_response_cache

cache = create_response_cache(namespace="api:openai", backend="memory", default_ttl=300)
if cache:
    cache.connect()
    # Check cache before making a request
    cached = cache.get("GET", url)
    if cached is None:
        response = await client.get("/models")
        cache.set("GET", url, response.body)
```

### Logging example

```python
from api_client_base.integrations.logger_integration import (
    get_api_logger, bind_request_context, log_request, log_response
)

logger = get_api_logger("my_client")
token = bind_request_context(request, client_name="openai")
log_request(logger, request)
# ... send request ...
log_response(logger, response)
```

### Error normalization example

```python
from api_client_base.integrations.error_integration import handle_api_error

try:
    await client.get("/resource")
except APIClientError as e:
    result = handle_api_error(e)
    # result = {"status_code": 401, "body": {"error": {"code": "UNAUTHORIZED", ...}}}
```

## Package Structure

```
api_client_base/
├── __init__.py                 # 45 public exports
├── types.py                    # Enums: HttpMethod, ContentType, AuthLocation, RetryBackoff
├── client/
│   ├── abstract_client.py      # AbstractAPIClient — core base class
│   ├── async_client.py         # AsyncAPIClient (httpx.AsyncClient)
│   └── sync_client.py          # SyncAPIClient (httpx.Client)
├── auth/
│   ├── base.py                 # AbstractAuthStrategy
│   ├── api_key.py              # APIKeyAuth
│   ├── bearer_token.py         # BearerTokenAuth
│   ├── oauth2.py               # OAuth2Auth
│   └── custom.py               # CustomAuth
├── request/
│   ├── models.py               # APIRequest, APIResponse
│   ├── builder.py              # RequestBuilder (fluent API)
│   └── middleware.py            # MiddlewareChain + built-in middleware
├── routing/
│   ├── endpoint.py             # EndpointDefinition
│   ├── registry.py             # EndpointRegistry
│   └── url_builder.py          # URLBuilder
├── resilience/
│   ├── retry.py                # RetryPolicy
│   ├── rate_limiter.py         # RateLimiter (token bucket)
│   ├── circuit_breaker.py      # CircuitBreaker (CLOSED/OPEN/HALF_OPEN)
│   └── timeout.py              # TimeoutPolicy
├── exceptions/
│   └── api_exceptions.py       # 10 typed exceptions
├── config/
│   └── client_config.py        # APIClientConfig, RateLimitConfig, CircuitBreakerConfig
├── integrations/
│   ├── cache_integration.py    # Cache_Manager (optional)
│   ├── logger_integration.py   # Logger_Package (optional)
│   ├── error_integration.py    # Error-Exception_Handler (optional)
│   └── notification_integration.py  # Notification_Manager (optional)
└── utils/
    ├── serialization.py        # JSON, form encoding, cache key hashing
    └── headers.py              # User-Agent, Content-Type, auth redaction
```

## Dependencies

| Dependency | Type | Purpose |
|-----------|------|---------|
| `httpx` | **Required** | Async + sync HTTP client |
| `Cache_Manager` | Optional | Response caching |
| `Logger_Package` | Optional | Structured logging |
| `Error-Exception_Handler` | Optional | Error normalization |
| `Notification_Manager` | Optional | Failure alerting |

## Future Plans

This package is under active development. Planned enhancements include:

- **Webhook support** — inbound webhook receiver with signature verification and event dispatching
- **GraphQL client** — query builder, schema introspection, and persisted queries
- **WebSocket client** — persistent connections with auto-reconnection and heartbeat management
- **gRPC support** — protobuf integration with streaming RPCs
- **SDK generation** — auto-generate concrete clients from OpenAPI/Swagger specs
- **Observability** — OpenTelemetry tracing, Prometheus metrics, distributed trace propagation
- **Advanced resilience** — bulkhead pattern, adaptive rate limiting, fallback strategies, request hedging
- **Pagination & batching** — auto-pagination iterators, batch request combining, parallel fan-out
- **Multi-environment** — environment profiles (prod/staging/sandbox) and multi-tenant client pools
- **Response transformation** — typed model mapping, incremental stream processing, response diffing
- **Testing utilities** — built-in mock server, record/replay cassettes, contract testing

See [plan.md](plan.md) for the full roadmap with detailed descriptions of each enhancement.

## License

This project is part of the `Dev_util_prj` monorepo. See the repository root for license information.
