from __future__ import annotations

import argparse
import os
import platform
import re
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.p2pci.protocol import (
    PROTOCOL_VERSION,
    build_p2p_response,
    parse_headers,
    parse_p2p_get_request,
    read_request_block,
)


@dataclass(frozen=True)
class LocalRfc:
    number: int
    title: str
    path: Path


class PeerNode:
    """Peer process that talks to the central server and serves RFC files to peers."""

    def __init__(
        self,
        peer_host: str,
        upload_port: int,
        server_host: str,
        server_port: int,
        rfc_dir: Path,
        download_dir: Path,
    ) -> None:
        self.peer_host = peer_host
        self.upload_port = upload_port
        self.server_host = server_host
        self.server_port = server_port
        self.rfc_dir = rfc_dir
        self.download_dir = download_dir

        self.server_sock: Optional[socket.socket] = None
        self.server_reader = None
        self._shutdown = threading.Event()

        self.local_rfcs: Dict[int, LocalRfc] = {}
        self._load_local_rfcs()

    def _load_local_rfcs(self) -> None:
        """Load local RFC metadata from file names in the RFC directory."""
        self.rfc_dir.mkdir(parents=True, exist_ok=True)
        pattern = re.compile(r"^RFC(\d+)[ _-](.+)\.txt$", re.IGNORECASE)

        for file_path in self.rfc_dir.glob("*.txt"):
            match = pattern.match(file_path.name)
            if not match:
                continue

            number = int(match.group(1))
            # File names use underscores for readability in shells.
            title = match.group(2).replace("_", " ").strip()
            self.local_rfcs[number] = LocalRfc(number=number, title=title, path=file_path)

    def start_upload_server(self) -> None:
        thread = threading.Thread(target=self._upload_server_loop, daemon=True)
        thread.start()

    def connect_server(self) -> None:
        self.server_sock = socket.create_connection((self.server_host, self.server_port))
        self.server_reader = self.server_sock.makefile("r", encoding="utf-8", newline="\n")
        print(f"[Peer] Connected to server at port {self.server_port}")

    def register_all_local_rfcs(self) -> None:
        for rfc in self.local_rfcs.values():
            print(f"[Peer] Registering RFC {rfc.number}: {rfc.title}")
            request = (
                f"ADD RFC {rfc.number} {PROTOCOL_VERSION}\r\n"
                f"Host: {self.peer_host}\r\n"
                f"Port: {self.upload_port}\r\n"
                f"Title: {rfc.title}\r\n"
                "\r\n"
            )
            response = self._send_server_request(request)
            self._print_response(response)

    def run_cli(self) -> None:
        print("[Peer] Commands: list | lookup <rfc> <title> | get <rfc> <host> <port> | add-local | exit")
        while not self._shutdown.is_set():
            try:
                raw = input("peer> ").strip()
            except EOFError:
                raw = "exit"

            if not raw:
                continue

            if raw == "exit":
                self.close()
                break

            if raw == "add-local":
                self.register_all_local_rfcs()
                continue

            if raw == "list":
                self.list_all()
                continue

            if raw.startswith("lookup "):
                self._handle_lookup(raw)
                continue

            if raw.startswith("get "):
                self._handle_get(raw)
                continue

            print("[Peer] Unknown command")

    def list_all(self) -> None:
        request = (
            f"LIST ALL {PROTOCOL_VERSION}\r\n"
            f"Host: {self.peer_host}\r\n"
            f"Port: {self.upload_port}\r\n"
            "\r\n"
        )
        response = self._send_server_request(request)
        self._print_response(response)

    def lookup(self, rfc_number: int, title: str) -> None:
        request = (
            f"LOOKUP RFC {rfc_number} {PROTOCOL_VERSION}\r\n"
            f"Host: {self.peer_host}\r\n"
            f"Port: {self.upload_port}\r\n"
            f"Title: {title}\r\n"
            "\r\n"
        )
        response = self._send_server_request(request)
        self._print_response(response)

    def download_rfc(self, rfc_number: int, remote_host: str, remote_port: int) -> None:
        os_name = f"{platform.system()} {platform.release()}"
        request = (
            f"GET RFC {rfc_number} {PROTOCOL_VERSION}\r\n"
            f"Host: {remote_host}\r\n"
            f"OS: {os_name}\r\n"
            "\r\n"
        )

        with socket.create_connection((remote_host, remote_port)) as sock:
            sock.sendall(request.encode("utf-8"))
            chunks: List[bytes] = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)

        response_text = b"".join(chunks).decode("utf-8", errors="replace")
        print(response_text.strip())

        if response_text.startswith(f"{PROTOCOL_VERSION} 200"):
            body = ""
            if "\r\n\r\n" in response_text:
                body = response_text.split("\r\n\r\n", 1)[1]
            elif "\n\n" in response_text:
                body = response_text.split("\n\n", 1)[1]

            self.download_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.download_dir / f"RFC{rfc_number}.txt"
            out_path.write_text(body, encoding="utf-8")
            print(f"[Peer] Saved RFC {rfc_number} to {out_path}")

    def _upload_server_loop(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", self.upload_port))
            listener.listen()
            print(f"[Peer] Upload server listening on port {self.upload_port}")

            while not self._shutdown.is_set():
                conn, _ = listener.accept()
                thread = threading.Thread(target=self._handle_upload_request, args=(conn,), daemon=True)
                thread.start()

    def _handle_upload_request(self, conn: socket.socket) -> None:
        with conn:
            stream = conn.makefile("r", encoding="utf-8", newline="\n")
            try:
                first_line, header_lines = read_request_block(stream)
                headers = parse_headers(header_lines)
                request = parse_p2p_get_request(first_line, headers)
            except ValueError:
                conn.sendall(build_p2p_response(400).encode("utf-8"))
                return
            except EOFError:
                return

            if request.version != PROTOCOL_VERSION:
                conn.sendall(build_p2p_response(505).encode("utf-8"))
                return

            assert request.rfc_number is not None
            local = self.local_rfcs.get(request.rfc_number)
            if not local or not local.path.exists():
                conn.sendall(build_p2p_response(404).encode("utf-8"))
                return

            body = local.path.read_text(encoding="utf-8")
            mtime = datetime.fromtimestamp(local.path.stat().st_mtime, tz=timezone.utc)
            response = build_p2p_response(
                200,
                body=body,
                responder_os=f"{platform.system()} {platform.release()}",
                last_modified=format_datetime(mtime, usegmt=True),
            )
            conn.sendall(response.encode("utf-8"))

    def _send_server_request(self, request: str) -> List[str]:
        if not self.server_sock or not self.server_reader:
            raise RuntimeError("Peer is not connected to the server")

        self.server_sock.sendall(request.encode("utf-8"))

        status_line = self.server_reader.readline()
        if not status_line:
            raise RuntimeError("Server closed the connection")

        status_line = status_line.rstrip("\r\n")
        # Response format has one empty line after status line.
        _ = self.server_reader.readline()

        data_lines: List[str] = []
        while True:
            line = self.server_reader.readline()
            if line == "":
                break
            line = line.rstrip("\r\n")
            if line == "":
                break
            data_lines.append(line)

        return [status_line, "", *data_lines]

    @staticmethod
    def _print_response(lines: List[str]) -> None:
        for line in lines:
            print(line)

    def _handle_lookup(self, raw: str) -> None:
        parts = raw.split()
        if len(parts) < 3:
            print("Usage: lookup <rfc_number> <title>")
            return

        try:
            rfc_number = int(parts[1])
        except ValueError:
            print("RFC number must be an integer")
            return

        title = " ".join(parts[2:]).strip()
        self.lookup(rfc_number, title)

    def _handle_get(self, raw: str) -> None:
        parts = raw.split()
        if len(parts) != 4:
            print("Usage: get <rfc_number> <peer_host> <peer_port>")
            return

        try:
            rfc_number = int(parts[1])
            peer_port = int(parts[3])
        except ValueError:
            print("RFC number and peer port must be integers")
            return

        self.download_rfc(rfc_number, parts[2], peer_port)

    def close(self) -> None:
        self._shutdown.set()
        if self.server_sock:
            self.server_sock.close()
            self.server_sock = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P2P-CI peer node")
    parser.add_argument("--peer-host", required=True, help="Logical host name for this peer (e.g. peerA)")
    parser.add_argument("--upload-port", type=int, required=True, help="Port for peer upload server")
    parser.add_argument("--server-host", default="127.0.0.1", help="Central server host")
    parser.add_argument("--server-port", type=int, default=7734, help="Central server port")
    parser.add_argument("--rfc-dir", default="rfcs/peerA", help="Directory containing local RFC text files")
    parser.add_argument("--download-dir", default="downloads", help="Directory where downloaded RFCs are stored")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    peer = PeerNode(
        peer_host=args.peer_host,
        upload_port=args.upload_port,
        server_host=args.server_host,
        server_port=args.server_port,
        rfc_dir=Path(args.rfc_dir),
        download_dir=Path(args.download_dir),
    )

    peer.start_upload_server()
    peer.connect_server()
    peer.register_all_local_rfcs()
    peer.run_cli()


if __name__ == "__main__":
    main()
