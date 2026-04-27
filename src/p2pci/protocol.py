from __future__ import annotations

from dataclasses import dataclass
from email.utils import format_datetime
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, TextIO

PROTOCOL_VERSION = "P2P-CI/1.0"

STATUS_PHRASES = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    505: "P2P-CI Version Not Supported",
}


@dataclass(frozen=True)
class RfcLocation:
    number: int
    title: str
    host: str
    port: int


@dataclass(frozen=True)
class ParsedRequest:
    method: str
    version: str
    headers: Dict[str, str]
    rfc_number: Optional[int] = None
    target: Optional[str] = None


def now_http_date() -> str:
    """Return a GMT timestamp string similar to HTTP date format."""
    return format_datetime(datetime.now(timezone.utc), usegmt=True)


def read_request_block(reader: TextIO) -> tuple[str, List[str]]:
    """Read one request message from a stream until an empty line."""
    first_line = reader.readline()
    if not first_line:
        raise EOFError("Peer closed the connection")

    first_line = first_line.rstrip("\r\n")
    header_lines: List[str] = []

    while True:
        line = reader.readline()
        if line == "":
            raise EOFError("Peer closed the connection while sending headers")

        line = line.rstrip("\r\n")
        if line == "":
            break
        header_lines.append(line)

    return first_line, header_lines


def parse_headers(header_lines: Iterable[str]) -> Dict[str, str]:
    """Parse Key: Value header lines into a dictionary."""
    headers: Dict[str, str] = {}
    for line in header_lines:
        if ":" not in line:
            raise ValueError(f"Invalid header line: {line}")
        key, value = line.split(":", 1)
        headers[key.strip()] = value.strip()
    return headers


def parse_p2s_request(first_line: str, headers: Dict[str, str]) -> ParsedRequest:
    """Parse a peer-to-server request line and validate protocol version."""
    tokens = first_line.split()
    if len(tokens) < 3:
        raise ValueError("Malformed request line")

    method = tokens[0].upper()

    if method == "LIST":
        if len(tokens) != 3 or tokens[1].upper() != "ALL":
            raise ValueError("LIST format must be: LIST ALL P2P-CI/1.0")
        version = tokens[2]
        _require_headers(headers, ["Host", "Port"])
        return ParsedRequest(method=method, version=version, headers=headers, target="ALL")

    if len(tokens) != 4 or tokens[1].upper() != "RFC":
        raise ValueError("Request format must include RFC number")

    try:
        rfc_number = int(tokens[2])
    except ValueError as exc:
        raise ValueError("RFC number must be an integer") from exc

    version = tokens[3]
    required = ["Host", "Port"]
    if method in {"ADD", "LOOKUP"}:
        required.append("Title")
    _require_headers(headers, required)

    return ParsedRequest(
        method=method,
        version=version,
        headers=headers,
        rfc_number=rfc_number,
    )


def parse_p2p_get_request(first_line: str, headers: Dict[str, str]) -> ParsedRequest:
    """Parse a peer-to-peer GET request."""
    tokens = first_line.split()
    if len(tokens) != 4:
        raise ValueError("GET format must be: GET RFC <number> P2P-CI/1.0")

    method = tokens[0].upper()
    if method != "GET" or tokens[1].upper() != "RFC":
        raise ValueError("Only GET RFC is supported for P2P requests")

    try:
        rfc_number = int(tokens[2])
    except ValueError as exc:
        raise ValueError("RFC number must be an integer") from exc

    version = tokens[3]
    _require_headers(headers, ["Host", "OS"])

    return ParsedRequest(method=method, version=version, headers=headers, rfc_number=rfc_number)


def build_p2s_response(status_code: int, records: Optional[List[RfcLocation]] = None) -> str:
    """Create a P2S response with optional RFC lines in the message body."""
    phrase = STATUS_PHRASES[status_code]
    lines = [f"{PROTOCOL_VERSION} {status_code} {phrase}", ""]

    if records:
        for record in records:
            lines.append(f"RFC {record.number} {record.title} {record.host} {record.port}")

    # End of message body marker.
    lines.append("")
    return "\r\n".join(lines) + "\r\n"


def build_p2p_response(
    status_code: int,
    body: str = "",
    responder_os: str = "Unknown",
    last_modified: Optional[str] = None,
) -> str:
    """Create a P2P response and include file metadata for successful GET."""
    phrase = STATUS_PHRASES[status_code]
    lines = [f"{PROTOCOL_VERSION} {status_code} {phrase}"]

    if status_code == 200:
        lines.extend(
            [
                f"Date: {now_http_date()}",
                f"OS: {responder_os}",
                f"Last-Modified: {last_modified or now_http_date()}",
                f"Content-Length: {len(body.encode('utf-8'))}",
                "Content-Type: text/plain",
                "",
            ]
        )
        lines.append(body)
    else:
        lines.append("")
        if body:
            lines.append(body)

    # End of message body marker.
    lines.append("")
    return "\r\n".join(lines)


def _require_headers(headers: Dict[str, str], required: List[str]) -> None:
    missing = [name for name in required if name not in headers or headers[name] == ""]
    if missing:
        raise ValueError(f"Missing required headers: {', '.join(missing)}")
