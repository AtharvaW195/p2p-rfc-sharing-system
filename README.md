# Project 1 - P2P-CI RFC Sharing System

This project implements a peer-to-peer RFC sharing system with a centralized index server.

## Folder Layout

- src/server.py: Centralized index server on port 7734
- src/peer.py: Peer process with upload server and CLI
- src/p2pci/protocol.py: Shared request and response formatting/parsing
- rfcs/peerA: Sample RFCs for Peer A
- rfcs/peerB: Sample RFCs for Peer B
- rfcs/peerC: Sample RFCs for Peer C (used for multi-location lookup demo)

## RFC File Naming Convention

Use this naming format:

RFC<number>_<title_words_with_underscores>.txt

Examples:

- RFC123_TCP_IP_Illustrated.txt
- RFC2345_Routing_Protocols.txt

## Run Commands (Windows, No make Needed)

Open 4 terminals in the project folder.

Terminal 1 - Server:

python -m src.server --host 0.0.0.0 --port 7734

Terminal 2 - Peer A:

python -m src.peer --peer-host peerA --upload-port 5678 --server-host 127.0.0.1 --server-port 7734 --rfc-dir rfcs/peerA --download-dir downloads/peerA

Terminal 3 - Peer B:

python -m src.peer --peer-host peerB --upload-port 6789 --server-host 127.0.0.1 --server-port 7734 --rfc-dir rfcs/peerB --download-dir downloads/peerB

Terminal 4 - Peer C:

python -m src.peer --peer-host peerC --upload-port 6790 --server-host 127.0.0.1 --server-port 7734 --rfc-dir rfcs/peerC --download-dir downloads/peerC

## Optional Make Targets (If make Is Installed)

- make run-server
- make run-peer-a
- make run-peer-b
- make run-peer-c

## Peer CLI Commands

After a peer starts and the prompt shows peer> , type:

- list
- lookup <rfc_number> <title>
- get <rfc_number> <peer_host> <peer_port>
- add-local
- exit

Examples:

- lookup 2345 Routing Protocols
- get 2345 127.0.0.1 6789

## Demo Test Flow and Commands

1. Start server, peerA, peerB, peerC.
2. In peerA terminal run:
	- list
	- lookup 2345 Routing Protocols
	- get 2345 127.0.0.1 6789
3. In peerB terminal run:
	- exit
4. In peerA terminal run:
	- list

## Error Case Commands (For Rubric)

Run these in a separate PowerShell terminal while peers are running.

400 Bad Request:

python -c "import socket; s=socket.create_connection(('127.0.0.1',5678)); s.sendall(b'HELLO RFC 123 P2P-CI/1.0\r\nHost: peerA\r\nOS: Windows 11\r\n\r\n'); print(s.recv(4096).decode()); s.close()"

404 Not Found:

python -c "import socket; s=socket.create_connection(('127.0.0.1',5678)); s.sendall(b'GET RFC 9999 P2P-CI/1.0\r\nHost: peerA\r\nOS: Windows 11\r\n\r\n'); print(s.recv(4096).decode()); s.close()"

505 P2P-CI Version Not Supported:

python -c "import socket; s=socket.create_connection(('127.0.0.1',5678)); s.sendall(b'GET RFC 123 P2P-CI/2.0\r\nHost: peerA\r\nOS: Windows 11\r\n\r\n'); print(s.recv(4096).decode()); s.close()"


## Stop All Running Processes

If Ctrl+C does not stop terminals, run:

taskkill /F /IM python.exe
