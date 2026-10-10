from __future__ import annotations

import httpcore
import httpx
import pytest

from breachgazette.clients.base import BoundedSourceClient, SourceClientError
from breachgazette.clients.deadline import DeadlineTransport

TRUNCATED = [
    b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nab",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n5\r\nab",
]
COMPLETE = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nabcde"

ERROR_PAIRS = [
    (httpcore.TimeoutException, httpx.TimeoutException),
    (httpcore.ConnectTimeout, httpx.ConnectTimeout),
    (httpcore.ReadTimeout, httpx.ReadTimeout),
    (httpcore.WriteTimeout, httpx.WriteTimeout),
    (httpcore.PoolTimeout, httpx.PoolTimeout),
    (httpcore.NetworkError, httpx.NetworkError),
    (httpcore.ConnectError, httpx.ConnectError),
    (httpcore.ReadError, httpx.ReadError),
    (httpcore.WriteError, httpx.WriteError),
    (httpcore.ProxyError, httpx.ProxyError),
    (httpcore.UnsupportedProtocol, httpx.UnsupportedProtocol),
    (httpcore.ProtocolError, httpx.ProtocolError),
    (httpcore.LocalProtocolError, httpx.LocalProtocolError),
    (httpcore.RemoteProtocolError, httpx.RemoteProtocolError),
]


@pytest.mark.parametrize("original,translated", ERROR_PAIRS)
@pytest.mark.parametrize("phase", ["request", "body", "close"])
def test_request_body_and_cleanup_use_the_same_specific_error_contract(original, translated, phase):
    class Stream:
        def __iter__(self):
            if phase == "body":
                raise original("synthetic untrusted diagnostic")
            yield b"ok"

        def close(self):
            pass

    class Pool:
        def handle_request(self, _):
            if phase == "request":
                raise original("synthetic untrusted diagnostic")
            return httpcore.Response(200, content=Stream())

        def close(self):
            if phase == "close":
                raise original("synthetic untrusted diagnostic")

    transport = DeadlineTransport(lambda: 1)
    transport.pool.close()
    transport.pool = Pool()
    with pytest.raises(translated) as error, httpx.Client(transport=transport) as client:
        assert client.get("https://synthetic.example/data").content == b"ok"
    assert type(error.value) is translated
    assert str(error.value) == "bounded source transport operation failed"
    assert isinstance(error.value.__cause__, original)


class SequenceBackend(httpcore.NetworkBackend):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.streams = []
        self.timeouts = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.timeouts.append(timeout)
        stream = httpcore.MockBackend([next(self.responses)]).connect_tcp(
            host, port, timeout, local_address, socket_options
        )
        self.streams.append(stream)
        return stream


def client_for(backend, monkeypatch, retries, *, deadline=90):
    monkeypatch.setattr("breachgazette.clients.base.time.sleep", lambda _: None)
    client = BoundedSourceClient(
        allowed_origins={"https://synthetic.example"},
        allowed_path_prefixes=("/",),
        max_response_bytes=100,
        max_retries=retries,
        total_deadline_seconds=deadline,
        rate_delay_seconds=0,
    )
    client._client.close()
    client._client = httpx.Client(transport=DeadlineTransport(client._remaining, backend=backend))
    return client


@pytest.mark.parametrize("phase", ["resolver", "addresses", "tls"])
def test_blocking_backend_overruns_are_rejected_after_return_and_closed(phase, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("breachgazette.clients.base.time.monotonic", lambda: now[0])

    class DelayedBackend(SequenceBackend):
        def connect_tcp(self, *args, **kwargs):
            stream = super().connect_tcp(*args, **kwargs)
            if phase == "resolver":
                # A resolver can block independently of the supplied socket timeout.
                now[0] += 1.1
            elif phase == "addresses":
                # Reusing a timeout across two address attempts can spend it twice.
                now[0] += 0.6
                now[0] += 0.6
            else:
                original = stream.start_tls

                def late_tls(*args, **kwargs):
                    now[0] += 1.1
                    return original(*args, **kwargs)

                monkeypatch.setattr(stream, "start_tls", late_tls)
            return stream

    backend = DelayedBackend([COMPLETE])
    with (
        client_for(backend, monkeypatch, 0, deadline=1) as client,
        pytest.raises(SourceClientError) as error,
    ):
        client.get_bytes("https://synthetic.example/data", accept="text/plain")
    assert now[0] > 1  # Rejecting a late return is not preempting the blocking operation.
    assert backend.timeouts == [1]
    assert isinstance(error.value.__cause__, SourceClientError)
    for stream in backend.streams:
        with pytest.raises(httpcore.ReadError):
            stream.read(1)


@pytest.mark.parametrize("broken", TRUNCATED)
def test_late_protocol_errors_retry_complete_response_and_close_streams(broken, monkeypatch):
    backend = SequenceBackend([broken, COMPLETE])
    with client_for(backend, monkeypatch, 1) as client:
        started = client._started
        content, _headers, _url = client.get_bytes(
            "https://synthetic.example/data", accept="text/plain"
        )
        assert content == b"abcde"
        assert client._started == started
    assert len(backend.streams) == 2
    for stream in backend.streams:
        with pytest.raises(httpcore.ReadError):
            stream.read(1)


@pytest.mark.parametrize("broken", TRUNCATED)
def test_late_protocol_retry_exhaustion_is_bounded_and_sanitised(broken, monkeypatch):
    backend = SequenceBackend([broken] * 3)
    with (
        client_for(backend, monkeypatch, 2) as client,
        pytest.raises(SourceClientError, match="official source request failed safely") as error,
    ):
        client.get_bytes("https://synthetic.example/data", accept="text/plain")
    assert len(backend.streams) == 3
    assert isinstance(error.value.__cause__, httpx.RemoteProtocolError)
    assert "synthetic.example" not in str(error.value.__cause__)
    for stream in backend.streams:
        with pytest.raises(httpcore.ReadError):
            stream.read(1)
