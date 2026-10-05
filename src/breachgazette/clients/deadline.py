"""Apply a client-lifetime budget to each blocking network operation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

import httpcore
import httpx


class DeadlineStream(httpcore.NetworkStream):
    def __init__(self, stream: httpcore.NetworkStream, remaining: Callable[[], float]) -> None:
        self.stream = stream
        self.remaining = remaining

    def _timeout(self, timeout: float | None) -> float:
        remaining = self.remaining()
        return min(timeout, remaining) if timeout is not None else remaining

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self.stream.read(max_bytes, timeout=self._timeout(timeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.stream.write(buffer, timeout=self._timeout(timeout))

    def close(self) -> None:
        self.stream.close()

    def start_tls(
        self, ssl_context: Any, server_hostname: str | None = None, timeout: float | None = None
    ) -> httpcore.NetworkStream:
        return DeadlineStream(
            self.stream.start_tls(
                ssl_context,
                server_hostname,
                timeout=self._timeout(timeout),
            ),
            self.remaining,
        )

    def get_extra_info(self, info: str) -> Any:
        return self.stream.get_extra_info(info)


class DeadlineBackend(httpcore.NetworkBackend):
    def __init__(
        self, remaining: Callable[[], float], backend: httpcore.NetworkBackend | None = None
    ) -> None:
        self.remaining = remaining
        self.backend = backend or httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        budget = self.remaining()
        stream = self.backend.connect_tcp(
            host,
            port,
            min(timeout, budget) if timeout is not None else budget,
            local_address,
            socket_options,
        )
        return DeadlineStream(stream, self.remaining)

    def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Any = None
    ) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("Unix sockets are outside the fixed HTTPS contract")


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, stream: Iterable[bytes]) -> None:
        self.stream = stream

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self.stream
        except httpcore.ReadTimeout as exc:
            raise httpx.ReadTimeout("bounded source read timed out") from exc
        except httpcore.ReadError as exc:
            raise httpx.ReadError("bounded source read failed") from exc

    def close(self) -> None:
        if hasattr(self.stream, "close"):
            self.stream.close()


class DeadlineTransport(httpx.BaseTransport):
    def __init__(
        self, remaining: Callable[[], float], *, backend: httpcore.NetworkBackend | None = None
    ) -> None:
        self.pool = httpcore.ConnectionPool(network_backend=DeadlineBackend(remaining, backend))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            response = self.pool.handle_request(
                httpcore.Request(
                    method=request.method,
                    url=httpcore.URL(
                        scheme=request.url.raw_scheme,
                        host=request.url.raw_host,
                        port=request.url.port,
                        target=request.url.raw_path,
                    ),
                    headers=request.headers.raw,
                    content=request.stream,
                    extensions=request.extensions,
                )
            )
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException("bounded source operation timed out") from exc
        except httpcore.NetworkError as exc:
            raise httpx.NetworkError("bounded source network operation failed") from exc
        except httpcore.ProtocolError as exc:
            raise httpx.ProtocolError("bounded source protocol operation failed") from exc
        if not isinstance(response.stream, Iterable):
            raise httpx.ProtocolError("bounded source returned an asynchronous stream")
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self.pool.close()
