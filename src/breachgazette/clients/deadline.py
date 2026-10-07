"""Apply a client-lifetime budget to each blocking network operation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import httpcore
import httpx

_ERROR_TYPES: dict[type[Exception], type[httpx.HTTPError]] = {
    httpcore.TimeoutException: httpx.TimeoutException,
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.WriteTimeout: httpx.WriteTimeout,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.NetworkError: httpx.NetworkError,
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.WriteError: httpx.WriteError,
    httpcore.ProxyError: httpx.ProxyError,
    httpcore.UnsupportedProtocol: httpx.UnsupportedProtocol,
    httpcore.ProtocolError: httpx.ProtocolError,
    httpcore.LocalProtocolError: httpx.LocalProtocolError,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
}


@contextmanager
def _translate_errors() -> Iterator[None]:
    """Keep request, body and cleanup errors in the same bounded retry contract."""
    try:
        yield
    except Exception as error:
        selected: type[httpx.HTTPError] | None = None
        for original, translated in _ERROR_TYPES.items():
            if isinstance(error, original) and (
                selected is None or issubclass(translated, selected)
            ):
                selected = translated
        if selected is None:
            raise
        raise selected("bounded source transport operation failed") from error


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
        stream = self.stream.start_tls(
            ssl_context,
            server_hostname,
            timeout=self._timeout(timeout),
        )
        try:
            self.remaining()
        except BaseException:
            stream.close()
            raise
        return DeadlineStream(stream, self.remaining)

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
        try:
            self.remaining()
        except BaseException:
            stream.close()
            raise
        return DeadlineStream(stream, self.remaining)

    def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Any = None
    ) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("Unix sockets are outside the fixed HTTPS contract")


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, stream: Iterable[bytes]) -> None:
        self.stream = stream

    def __iter__(self) -> Iterator[bytes]:
        with _translate_errors():
            yield from self.stream

    def close(self) -> None:
        with _translate_errors():
            if hasattr(self.stream, "close"):
                self.stream.close()


class DeadlineTransport(httpx.BaseTransport):
    def __init__(
        self, remaining: Callable[[], float], *, backend: httpcore.NetworkBackend | None = None
    ) -> None:
        self.pool = httpcore.ConnectionPool(network_backend=DeadlineBackend(remaining, backend))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with _translate_errors():
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
        if not isinstance(response.stream, Iterable):
            raise httpx.ProtocolError("bounded source returned an asynchronous stream")
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream),
            extensions=response.extensions,
        )

    def close(self) -> None:
        with _translate_errors():
            self.pool.close()
