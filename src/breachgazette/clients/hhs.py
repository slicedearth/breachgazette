"""Explicitly deferred HHS adapter boundary."""

from __future__ import annotations

from breachgazette.clients.base import SourceClientError


class HhsAdapter:
    source_id = "hhs"

    def collect(self) -> None:
        raise SourceClientError(
            "HHS is deferred: the verified public list is a stateful JSF portal "
            "without a reviewed bounded machine-readable export"
        )
