"""Quarantine tool protocol accidentally emitted on the assistant text channel.

Only native tool calls may execute. Even a complete tool-shaped JSON object in
prose is not authorization to dispatch. Code examples are preserved. Ambiguous
suffixes are held until end of turn so rejected bytes never reach SSE/history.
"""

import json
import re
from dataclasses import dataclass

_CODE = re.compile(r"```[\s\S]*?(?:```|$)|`[^`\n]*`")
_DSML = re.compile(r"</?[|｜]{1,2}DSML[|｜]{1,2}", re.IGNORECASE)
_CALL_PREFIX = re.compile(r'"name"\s*:\s*"[^"\n]+"\s*,\s*"arguments"\s*:')


@dataclass(frozen=True)
class PublicText:
    text: str
    protocol_error: bool


def clean_protocol_text(text: str) -> PublicText:
    """Drop an unquoted protocol suffix without repairing or executing it."""
    masked = _CODE.sub(lambda match: " " * len(match.group()), text)
    marker = _DSML.search(masked)
    cutoff = marker.start() if marker else len(text)
    decoder = json.JSONDecoder()
    cursor = 0
    while cursor < cutoff:
        start = masked.find("{", cursor, cutoff)
        if start < 0:
            break
        try:
            value, length = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            # The reported response ends after arguments, with the outer object
            # still open. Recognize the call shape; never guess the missing bytes.
            if _CALL_PREFIX.search(masked[start:cutoff]):
                cutoff = start
                break
            cursor = start + 1
        else:
            if isinstance(value, dict) and isinstance(value.get("name"), str) and "arguments" in value:
                cutoff = start
                break
            cursor = start + length
    return PublicText(text=text[:cutoff], protocol_error=cutoff < len(text))


class ProtocolTextBuffer:
    """Stream unambiguous prose and defer JSON, tags and code to finalization."""

    _pending: str
    _holding: bool

    def __init__(self) -> None:
        self._pending = ""
        self._holding = False

    def push(self, text: str) -> str:
        if self._holding:
            self._pending += text
            return ""
        candidates = [index for char in "{<`" if (index := text.find(char)) >= 0]
        if not candidates:
            return text
        start = min(candidates)
        self._holding = True
        self._pending = text[start:]
        return text[:start]

    def finish(self) -> PublicText:
        result = clean_protocol_text(self._pending)
        self._pending = ""
        return result
