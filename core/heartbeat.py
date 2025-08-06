# Implementation based on provided/previously-discussed logic
import socket
import threading
import time
import os
import sys

# Get the absolute path for the ../core/ folder relative to this script
core_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), './libs/', 'server'))

# Add the core directory to sys.path to make it importable
sys.path.append(core_dir)


from codenamesServer_class import CodenamesServer

class BackupCodenamesServer:
    PRIMARY_TIMEOUT = 4  # seconds without heartbeat before failover
    HEARTBEAT_PORT = 5555

    def __init__(self, backup_host='127.0.0.1', backup_port=5555, primary_host='127.0.0.1', primary_port=5555):
        self.primary_addr = (primary_host, primary_port)
        self.backup_addr = (backup_host, backup_port)

        # UDP socket for heartbeat listening
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(self.backup_addr)
        self.sock.settimeout(1)  # timeout for socket.recvfrom to regularly check

        self.last_heartbeat = time.time()
        self.running = True
        self.active = False  # Will be True if promoted to primary
        self.primary_server_instance = None

    def start(self):

        self.promote_to_primary()

        print(f"Backup server running at {self.backup_addr}, monitoring primary at {self.primary_addr}")
        try:
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024)
                    msg = data.decode('utf-8')
                    if msg == "PRIMARY_HEARTBEAT":
                        self.last_heartbeat = time.time()
                        if self.active:
                            # Primary recovered or was restarted elsewhere, stop acting as primary
                            print("Heartbeat received while active as primary. Demoting self back to backup.")
                            # self.stop_primary_mode()
                except socket.timeout:
                    if not self.active and time.time() - self.last_heartbeat > self.PRIMARY_TIMEOUT:
                        print("Primary heartbeat lost. Promoting self to primary.")


                        self.promote_to_primary()
        except KeyboardInterrupt:
            print("Backup server shutting down.")
            self.running = False
            self.stop_primary_mode()
            self.sock.close()

    def promote_to_primary(self):
        if self.active:
            return
        self.primary_server_instance = CodenamesServer(self.backup_addr[0], 5555)  # Use primary port or backup port?
        self.active = True

        # Start TCP server threads of promoted primary
        threading.Thread(target=self.primary_server_instance.start, daemon=True).start()

        # Also start heartbeat sender to other backups (if any)
        self.primary_server_instance.start_heartbeat_sender(backup_host=self.primary_addr[0], backup_port=self.backup_addr[1])
        print("Backup server promoted to primary.")

    def stop_primary_mode(self):
        if self.primary_server_instance:
            self.primary_server_instance.stop()
            self.primary_server_instance.stop_heartbeat_sender()
        self.active = False

        

# Usage:

# On backup machine or process
# backup_server = BackupCodenamesServer()
# backup_server.start()


backup_server = BackupCodenamesServer(
    backup_host='127.0.0.1', backup_port=5556,     # Where backup listens for heartbeat
    primary_host='127.0.0.1', primary_port=5555    # Where backup would take over TCP if promoted
)
backup_server.start()
