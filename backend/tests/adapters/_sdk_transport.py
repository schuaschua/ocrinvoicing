"""A fake HTTP transport for the real Azure SDK pipelines (Story 1.8): each request is
recorded and answered from a list, so nothing goes over the network."""

from typing import Any, Self

from azure.core.pipeline.transport import AsyncHttpResponse, AsyncHttpTransport


class FakeResponse(AsyncHttpResponse):
    def __init__(
        self, request: Any, status: int, body: bytes, headers: dict[str, str]
    ) -> None:
        super().__init__(request, None)
        self.status_code = status
        self.reason = "OK" if status < 400 else "Error"
        self.headers = headers
        self.content_type = headers.get("Content-Type")
        self._body = body

    def body(self) -> bytes:
        return self._body

    async def load_body(self) -> None:
        return None

    async def read(self) -> bytes:
        # A download's error path reads the body before raising (Story 2.1).
        return self._body

    def stream_download(self, pipeline: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class FakeTransport(AsyncHttpTransport):
    """Answers the n-th request with `answers[n]`: (status, body, headers)."""

    def __init__(self, answers: list[tuple[int, bytes, dict[str, str]]]) -> None:
        self.answers = list(answers)
        self.requests: list[Any] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def send(self, request: Any, **kwargs: Any) -> FakeResponse:
        self.requests.append(request)
        status, body, headers = self.answers.pop(0)
        return FakeResponse(request, status, body, headers)
