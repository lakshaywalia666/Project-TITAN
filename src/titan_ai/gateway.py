"""Policy, quota, routing, fallback and cost control for model access."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from titan_ai.models import (
    BackendResponse,
    ChatMessage,
    GenerateRequest,
    GenerateResponse,
    TokenUsage,
)


class GatewayError(RuntimeError):
    pass


class ModelAccessDenied(GatewayError):
    pass


class TokenBudgetExceeded(GatewayError):
    pass


class RequestRateExceeded(GatewayError):
    pass


class BackendUnavailable(GatewayError):
    pass


class InvalidModelResponse(GatewayError):
    pass


class ModelBackend(Protocol):
    name: str
    model: str

    def generate(self, request: GenerateRequest, correlation_id: str) -> BackendResponse: ...


@dataclass(frozen=True, slots=True)
class Route:
    name: str
    backend: ModelBackend
    input_cost_per_million: float
    output_cost_per_million: float
    complexity: str


class BudgetLedger:
    def __init__(self, limits: Mapping[str, int]) -> None:
        self._limits = dict(limits)
        self._used: dict[str, int] = {}
        self._lock = threading.Lock()

    def reserve(self, project_id: str, tokens: int) -> None:
        if tokens < 0:
            raise ValueError("token reservation must be non-negative")
        with self._lock:
            limit = self._limits.get(project_id, 0)
            used = self._used.get(project_id, 0)
            if used + tokens > limit:
                raise TokenBudgetExceeded(
                    f"token budget exceeded for project {project_id}: "
                    f"requested={tokens}, remaining={max(limit - used, 0)}"
                )
            self._used[project_id] = used + tokens

    def refund(self, project_id: str, tokens: int) -> None:
        with self._lock:
            self._used[project_id] = max(self._used.get(project_id, 0) - tokens, 0)

    def usage(self, project_id: str) -> dict[str, int]:
        with self._lock:
            used = self._used.get(project_id, 0)
            limit = self._limits.get(project_id, 0)
        return {"used": used, "limit": limit, "remaining": max(limit - used, 0)}


class RequestRateLimiter:
    def __init__(
        self,
        limits_per_minute: Mapping[str, int] | None = None,
        *,
        default_limit: int = 60,
    ) -> None:
        if default_limit < 1:
            raise ValueError("default request limit must be positive")
        self._limits = dict(limits_per_minute or {})
        self.default_limit = default_limit
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def consume(self, project_id: str) -> None:
        now = time.monotonic()
        cutoff = now - 60
        with self._lock:
            recent = [timestamp for timestamp in self._requests.get(project_id, []) if timestamp > cutoff]
            limit = self._limits.get(project_id, self.default_limit)
            if len(recent) >= limit:
                self._requests[project_id] = recent
                raise RequestRateExceeded(
                    f"request rate exceeded for project {project_id}: limit={limit}/minute"
                )
            recent.append(now)
            self._requests[project_id] = recent


@dataclass(slots=True)
class _CircuitState:
    failures: int = 0
    open_until: float = 0.0


class AIGateway:
    def __init__(
        self,
        *,
        routes: tuple[Route, ...],
        allowed_models: Mapping[str, tuple[str, ...]],
        budget_ledger: BudgetLedger,
        rate_limiter: RequestRateLimiter | None = None,
        simple_request_character_limit: int = 1_000,
        circuit_failure_threshold: int = 3,
        circuit_open_seconds: float = 30.0,
    ) -> None:
        if not routes:
            raise ValueError("at least one model route is required")
        self.routes = routes
        self.allowed_models = dict(allowed_models)
        self.budget_ledger = budget_ledger
        self.rate_limiter = rate_limiter
        self.simple_request_character_limit = simple_request_character_limit
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_open_seconds = circuit_open_seconds
        self._circuits = {route.name: _CircuitState() for route in routes}
        self._lock = threading.Lock()

    def generate(
        self, *, project_id: str, request: GenerateRequest, correlation_id: str
    ) -> GenerateResponse:
        self._validate_request(request)
        if self.rate_limiter is not None:
            self.rate_limiter.consume(project_id)
        # Resolve authorization before touching the usage ledger. A denied model
        # request must never consume another tenant's budget.
        candidates = self._candidate_routes(project_id, request)
        reservation = _reservation_input_tokens(request.messages) + request.max_output_tokens
        self.budget_ledger.reserve(project_id, reservation)
        reservation_open = True
        try:
            last_error: Exception | None = None
            for index, route in enumerate(candidates):
                if self._circuit_is_open(route.name):
                    last_error = BackendUnavailable(
                        f"circuit is open for backend route {route.name}"
                    )
                    continue
                try:
                    backend_response = route.backend.generate(request, correlation_id)
                    _validate_backend_response(backend_response, request, reservation)
                    self._record_success(route.name)
                    unused_reservation = reservation - backend_response.usage.total_tokens
                    self.budget_ledger.refund(project_id, unused_reservation)
                    reservation_open = False
                    cost = (
                        backend_response.usage.input_tokens
                        * route.input_cost_per_million
                        / 1_000_000
                        + backend_response.usage.output_tokens
                        * route.output_cost_per_million
                        / 1_000_000
                    )
                    return GenerateResponse(
                        text=backend_response.text,
                        model=backend_response.model,
                        backend=route.name,
                        usage=backend_response.usage,
                        estimated_cost=round(cost, 8),
                        correlation_id=correlation_id,
                        fallback_used=index > 0,
                    )
                except (BackendUnavailable, InvalidModelResponse, TimeoutError, OSError) as error:
                    last_error = error
                    self._record_failure(route.name)

            raise BackendUnavailable(
                f"all permitted model backends failed: {last_error or 'no route available'}"
            )
        finally:
            if reservation_open:
                self.budget_ledger.refund(project_id, reservation)

    def _candidate_routes(
        self, project_id: str, request: GenerateRequest
    ) -> list[Route]:
        allowed = set(self.allowed_models.get(project_id, ()))
        if not allowed:
            raise ModelAccessDenied(f"project {project_id} has no permitted models")

        if request.requested_model:
            if request.requested_model not in allowed:
                raise ModelAccessDenied(
                    f"model is not permitted for project {project_id}: "
                    f"{request.requested_model}"
                )
            selected = [
                route for route in self.routes if route.backend.model == request.requested_model
            ]
        else:
            character_count = sum(len(message.content) for message in request.messages)
            desired_complexity = (
                "simple"
                if character_count <= self.simple_request_character_limit
                else "complex"
            )
            selected = [
                route
                for route in self.routes
                if route.backend.model in allowed and route.complexity == desired_complexity
            ]
            selected.extend(
                route
                for route in self.routes
                if route.backend.model in allowed and route not in selected
            )

        if not selected:
            raise ModelAccessDenied("no configured route matches the permitted model set")
        return selected

    def _circuit_is_open(self, route_name: str) -> bool:
        with self._lock:
            return self._circuits[route_name].open_until > time.monotonic()

    def _record_success(self, route_name: str) -> None:
        with self._lock:
            self._circuits[route_name] = _CircuitState()

    def _record_failure(self, route_name: str) -> None:
        with self._lock:
            state = self._circuits[route_name]
            state.failures += 1
            if state.failures >= self.circuit_failure_threshold:
                state.open_until = time.monotonic() + self.circuit_open_seconds

    @staticmethod
    def _validate_request(request: GenerateRequest) -> None:
        if not request.messages:
            raise GatewayError("at least one message is required")
        if not 1 <= request.max_output_tokens <= 8_192:
            raise GatewayError("max_output_tokens must be between 1 and 8192")
        if not 0 <= request.temperature <= 2:
            raise GatewayError("temperature must be between 0 and 2")
        for message in request.messages:
            if message.role not in {"system", "user", "assistant", "tool"}:
                raise GatewayError(f"unsupported message role: {message.role}")
            if not message.content:
                raise GatewayError("message content must not be empty")


class VLLMBackend:
    def __init__(
        self,
        *,
        name: str,
        endpoint: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate(self, request: GenerateRequest, correlation_id: str) -> BackendResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        http_request = Request(
            f"{self.endpoint}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Request-ID": correlation_id,
            },
        )
        try:
            with urlopen(http_request, timeout=self.timeout_seconds) as response:
                document = json.load(response)
        except (HTTPError, URLError, TimeoutError) as error:
            raise BackendUnavailable(f"vLLM request failed: {error}") from error
        try:
            text = document["choices"][0]["message"]["content"]
            usage = document["usage"]
            return BackendResponse(
                text=str(text),
                model=str(document.get("model", self.model)),
                usage=TokenUsage(
                    input_tokens=int(usage["prompt_tokens"]),
                    output_tokens=int(usage["completion_tokens"]),
                ),
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise InvalidModelResponse("vLLM returned an invalid response") from error


class DeterministicBackend:
    """Offline backend for tests and local demonstrations without a model download."""

    def __init__(
        self, *, name: str, model: str, response_text: str, fail: bool = False
    ) -> None:
        self.name = name
        self.model = model
        self.response_text = response_text
        self.fail = fail
        self.calls = 0

    def generate(self, request: GenerateRequest, correlation_id: str) -> BackendResponse:
        self.calls += 1
        if self.fail:
            raise BackendUnavailable(f"deterministic backend unavailable: {self.name}")
        input_tokens = _estimate_tokens(
            "\n".join(message.content for message in request.messages)
        )
        return BackendResponse(
            text=self.response_text,
            model=self.model,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=_estimate_tokens(self.response_text),
            ),
        )


def _estimate_tokens(text: str) -> int:
    return max((len(text) + 3) // 4, 1)


def _reservation_input_tokens(messages: tuple[ChatMessage, ...]) -> int:
    """Conservative tokenizer-independent ceiling for admission control.

    Byte-pair tokenizers cannot emit more ordinary content tokens than UTF-8 bytes;
    the fixed allowance covers role and chat-template markers.
    """

    return sum(len(message.content.encode("utf-8")) + 16 for message in messages) + 16


def _validate_backend_response(
    response: BackendResponse, request: GenerateRequest, reservation: int
) -> None:
    usage = response.usage
    valid_usage_types = all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (usage.input_tokens, usage.output_tokens)
    )
    if (
        not isinstance(response.text, str)
        or not response.text
        or not isinstance(response.model, str)
        or not response.model
        or not valid_usage_types
        or usage.input_tokens < 0
        or usage.output_tokens < 0
        or usage.output_tokens > request.max_output_tokens
        or usage.total_tokens > reservation
    ):
        raise InvalidModelResponse("model backend returned invalid or unbudgeted usage")
