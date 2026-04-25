from __future__ import annotations

import argparse
import socket
import threading
from dataclasses import dataclass
from typing import Dict, List, Tuple

from src.p2pci.protocol import (
    PROTOCOL_VERSION,
    ParsedRequest,
    RfcLocation,
    build_p2s_response,
    parse_headers,
    parse_p2s_request,
    read_request_block,
)


@dataclass(frozen=True)
class PeerRecord:
    host: str
    port: int


class CentralIndex:
    """Thread-safe in-memory state for active peers and their RFCs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._peers: Dict[Tuple[str, int], PeerRecord] = {}
        self._rfcs: List[RfcLocation] = []

    def add_peer(self, host: str, port: int) -> None:
        with self._lock:
            key = (host, port)
            if key not in self._peers:
                self._peers[key] = PeerRecord(host=host, port=port)
                print(f"[Server] Added {host}:{port}")
            self._print_snapshot_locked()

    def add_rfc(self, number: int, title: str, host: str, port: int) -> None:
        with self._lock:
            record = RfcLocation(number=number, title=title, host=host, port=port)
            if record not in self._rfcs:
                self._rfcs.insert(0, record)
                print(f"[Server] Added RFC {number} from {host}")
            self._print_snapshot_locked()

    def lookup(self, number: int, title: str) -> List[RfcLocation]:
        with self._lock:
            return [
                r
                for r in self._rfcs
                if r.number == number and r.title.lower() == title.lower()
            ]

    def list_all(self) -> List[RfcLocation]:
        with self._lock:
            return list(self._rfcs)

    def remove_peer_and_rfcs(self, host: str, port: int) -> None:
        with self._lock:
            before = len(self._rfcs)
            self._rfcs = [r for r in self._rfcs if not (r.host == host and r.port == port)]
            removed_rfcs = before - len(self._rfcs)

            removed_peer = self._peers.pop((host, port), None)
            if removed_peer:
                print(f"[Server] Removed {host}:{port} and {removed_rfcs} RFC records")
            self._print_snapshot_locked()

    def _print_snapshot_locked(self) -> None:
        peers = sorted(self._peers.values(), key=lambda p: (p.host.lower(), p.port))
        if peers:
            peer_str = ", ".join(f"{p.host}:{p.port}" for p in peers)
        else:
            peer_str = "none"

        if self._rfcs:
            rfc_str = " | ".join(
                f"RFC {r.number} {r.title} {r.host}:{r.port}" for r in self._rfcs
            )
        else:
            rfc_str = "none"

        print(f"[Server] Active peers: {peer_str}")
        print(f"[Server] RFC index: {rfc_str}")


class P2PCentralServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.index = CentralIndex()

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen()

            print(f"[Server] Listening on {self.host}:{self.port}")

            while True:
                conn, addr = listener.accept()
                thread = threading.Thread(
                    target=self._handle_peer,
                    args=(conn, addr),
                    daemon=True,
                )
                thread.start()

    def _handle_peer(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        peer_identity: tuple[str, int] | None = None

        with conn:
            stream = conn.makefile("r", encoding="utf-8", newline="\n")
            while True:
                try:
                    first_line, header_lines = read_request_block(stream)
                except EOFError:
                    break
                except ConnectionResetError:
                    # Treat abrupt peer close as a normal disconnect path.
                    break
                except Exception:
                    try:
                        conn.sendall(build_p2s_response(400).encode("utf-8"))
                    except OSError:
                        # Socket is already gone; just terminate this handler.
                        break
                    break

                try:
                    headers = parse_headers(header_lines)
                    request = parse_p2s_request(first_line, headers)
                except ValueError:
                    try:
                        conn.sendall(build_p2s_response(400).encode("utf-8"))
                    except OSError:
                        break
                    continue

                if request.version != PROTOCOL_VERSION:
                    try:
                        conn.sendall(build_p2s_response(505).encode("utf-8"))
                    except OSError:
                        break
                    continue

                host = request.headers["Host"]
                port = int(request.headers["Port"])

                if peer_identity is None:
                    peer_identity = (host, port)
                    print(f"[Server] Connection from host {host} at {addr[0]}:{addr[1]}")

                self.index.add_peer(host, port)
                response = self._dispatch(request)
                try:
                    conn.sendall(response.encode("utf-8"))
                except OSError:
                    break

        if peer_identity:
            self.index.remove_peer_and_rfcs(peer_identity[0], peer_identity[1])

    def _dispatch(self, request: ParsedRequest) -> str:
        if request.method == "ADD":
            assert request.rfc_number is not None
            title = request.headers["Title"]
            host = request.headers["Host"]
            port = int(request.headers["Port"])
            self.index.add_rfc(request.rfc_number, title, host, port)
            return build_p2s_response(
                200,
                [
                    RfcLocation(
                        number=request.rfc_number,
                        title=title,
                        host=host,
                        port=port,
                    )
                ],
            )

        if request.method == "LOOKUP":
            assert request.rfc_number is not None
            results = self.index.lookup(request.rfc_number, request.headers["Title"])
            if not results:
                return build_p2s_response(404)
            return build_p2s_response(200, results)

        if request.method == "LIST":
            records = self.index.list_all()
            if not records:
                return build_p2s_response(404)
            return build_p2s_response(200, records)

        return build_p2s_response(400)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P2P-CI centralized index server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=7734, help="Server port (default: 7734)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = P2PCentralServer(args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
