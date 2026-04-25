PYTHON ?= python

.PHONY: run-server run-peer-a run-peer-b run-peer-c clean

# Start the centralized index server on the required demo port.
run-server:
	$(PYTHON) -m src.server --host 0.0.0.0 --port 7734

# Start Peer A with its own upload port and local RFC directory.
run-peer-a:
	$(PYTHON) -m src.peer --peer-host peerA --upload-port 5678 --server-host 127.0.0.1 --server-port 7734 --rfc-dir rfcs/peerA --download-dir downloads/peerA

# Start Peer B with its own upload port and local RFC directory.
run-peer-b:
	$(PYTHON) -m src.peer --peer-host peerB --upload-port 6789 --server-host 127.0.0.1 --server-port 7734 --rfc-dir rfcs/peerB --download-dir downloads/peerB

# Start Peer C with the same RFC as Peer B to test multi-location LOOKUP.
run-peer-c:
	$(PYTHON) -m src.peer --peer-host peerC --upload-port 6790 --server-host 127.0.0.1 --server-port 7734 --rfc-dir rfcs/peerC --download-dir downloads/peerC

# Remove downloaded files generated during test runs.
clean:
	-$(PYTHON) -c "import shutil; shutil.rmtree('downloads', ignore_errors=True)"
