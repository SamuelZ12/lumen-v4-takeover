"""How a CLI reaches the sidecar: HTTP to the ops service (host tests inject their own transport)."""

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://ops:8080"


class TransportError(Exception):
    pass


class HttpTransport:
    def __init__(self, base_url: str | None = None, timeout: float = 60.0):
        self.base_url = (base_url or os.environ.get("LUMEN_OPS_URL") or DEFAULT_URL).rstrip("/")
        self.timeout = timeout

    def call(self, api: str, args: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/v1/commands/{api}",
            data=json.dumps(args).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return json.loads(error.read())
            except ValueError:
                raise TransportError(f"ops service returned HTTP {error.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise TransportError(f"cannot reach the ops service at {self.base_url}: {error}") from None
