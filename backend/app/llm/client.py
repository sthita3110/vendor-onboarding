"""OpenAI wrapper: one document in, schema-valid JSON out.

The rest of the app depends only on the `DocumentReader` protocol, so tests use a fake reader
and swapping provider means writing one new class.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from openai import BadRequestError, OpenAI

from app.config import Settings, get_settings
from app.llm.prompts import EXTRACTION_INSTRUCTIONS
from app.llm.schema import EXTRACTION_SCHEMA


@dataclass
class ReadResult:
    data: dict[str, Any]  # schema-valid extraction
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class DocumentReader(Protocol):
    model: str

    def read(self, data: bytes, filename: str, mime: str) -> ReadResult: ...


def _content_part(data: bytes, filename: str, mime: str) -> dict[str, Any]:
    b64 = base64.b64encode(data).decode()
    if mime == "application/pdf":
        # detail=high: render pages at full quality; "auto" can downsample scans and drop characters.
        return {"type": "input_file", "filename": filename, "file_data": f"data:application/pdf;base64,{b64}",
                "detail": "high"}
    if mime in ("image/png", "image/jpeg"):
        return {"type": "input_image", "image_url": f"data:{mime};base64,{b64}", "detail": "high"}
    raise ValueError(f"Unsupported file type: {mime}")


class OpenAIReader:
    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None):
        s = settings or get_settings()
        if not s.openai_api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.model = s.openai_model
        self._reasoning_effort = s.openai_reasoning_effort
        # SDK retries connection errors, 429 and 5xx; one retry keeps worst-case latency bounded.
        self._client = client or OpenAI(api_key=s.openai_api_key, timeout=s.openai_timeout_s, max_retries=1)
        self._send_temperature = True  # dropped automatically for models that reject it

    def read(self, data: bytes, filename: str, mime: str) -> ReadResult:
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": EXTRACTION_INSTRUCTIONS,
            "input": [{"role": "user", "content": [
                _content_part(data, filename, mime),
                {"type": "input_text", "text": "Identify this document and extract its fields."},
            ]}],
            "text": {"format": {"type": "json_schema", "name": "document_extraction",
                                "schema": EXTRACTION_SCHEMA, "strict": True}},
        }
        if self._reasoning_effort:
            request["reasoning"] = {"effort": self._reasoning_effort}

        start = time.monotonic()
        try:
            resp = self._client.responses.create(**request, **({"temperature": 0} if self._send_temperature else {}))
        except BadRequestError as e:
            # Reasoning models reject `temperature`; retry once without it and remember.
            if self._send_temperature and "temperature" in str(e):
                self._send_temperature = False
                resp = self._client.responses.create(**request)
            else:
                raise
        latency_ms = int((time.monotonic() - start) * 1000)

        usage = getattr(resp, "usage", None)
        return ReadResult(
            data=json.loads(resp.output_text),
            model=self.model,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
