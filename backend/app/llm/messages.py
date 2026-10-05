"""OpenAI writer for vendor messages: subject, opening and closing only (strict JSON).

It receives vendor-safe facts only. The checklist is inserted by code; the output is safety-filtered by
app.messages.compose before use.
"""

from __future__ import annotations

import json
from typing import Any

from openai import BadRequestError, OpenAI

from app.config import Settings, get_settings
from app.messages.compose import Draft

MESSAGE_PROMPT_VERSION = "message-v3"

INSTRUCTIONS = """\
You write short, polite emails from our procurement team to a vendor about the vendor's onboarding application.
vendor_company is the applicant — the recipient's company that wants to become our vendor (not us).
Write only three parts: a subject line, an opening paragraph (1–2 sentences) and a closing paragraph (1–2 sentences).

The system inserts a numbered list of requested items between your opening and closing. Do not list, repeat,
add, summarise or rephrase any items. If item_count > 0, end the opening by introducing the list (e.g. "please
send us the following:"). Never explain reasons, checks, verifications, risks or internal processes. Never promise
timelines or outcomes. Refer to the applicant by vendor_company. Plain text, no markdown. The system adds the greeting line
("Dear …,") and the signature: do not start the opening with a greeting and do not sign off.

Meaning of kind:
- approved: onboarding is complete; nothing further is needed.
- action_needed: we need the listed items to continue.
- under_review: the application is being reviewed; if item_count > 0, ask for the listed items meanwhile.
- rejected: we are unable to proceed with the application; invite questions by reply. Give no reason.
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "intro": {"type": "string"}, "closing": {"type": "string"}},
    "required": ["subject", "intro", "closing"],
    "additionalProperties": False,
}


class OpenAIMessageWriter:
    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None):
        s = settings or get_settings()
        if not s.openai_api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.model = s.openai_model
        self._client = client or OpenAI(api_key=s.openai_api_key, timeout=20, max_retries=1)

    def write(self, facts: dict[str, Any]) -> Draft:
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": INSTRUCTIONS,
            "input": [{"role": "user", "content": json.dumps(facts)}],
            "text": {"format": {"type": "json_schema", "name": "vendor_message", "schema": SCHEMA, "strict": True}},
        }
        try:
            resp = self._client.responses.create(**request, temperature=0.3)
        except BadRequestError as e:
            if "temperature" not in str(e):
                raise
            resp = self._client.responses.create(**request)
        data = json.loads(resp.output_text)
        return Draft(subject=data["subject"], intro=data["intro"], closing=data["closing"])


def make_message_writer(settings: Settings | None = None) -> OpenAIMessageWriter | None:
    """The AI writer, or None (template only) when disabled or no key is configured."""
    s = settings or get_settings()
    if not s.messages_ai or not s.openai_api_key:
        return None
    return OpenAIMessageWriter(s)
