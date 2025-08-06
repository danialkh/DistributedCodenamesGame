# Implementation based on provided/previously-discussed logic
import socket
import threading
import time
import os
import sys

# Get the absolute path for the ../core/ folder relative to this script
core_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), './', 'core'))

# Add the core directory to sys.path to make it importable
sys.path.append(core_dir)

from heartbeat import BackupCodenamesServer

if __name__ == "__main__":
    
    backup_server = BackupCodenamesServer(
        backup_host='127.0.0.1', backup_port=5556,     # Where backup listens for heartbeat
        primary_host='127.0.0.1', primary_port=5555    # Where backup would take over TCP if promoted
    )
    backup_server.start()

