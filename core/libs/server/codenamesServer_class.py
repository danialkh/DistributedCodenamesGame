import socket
import threading
import json
import time
import random
import traceback
import select
import pymongo
from datetime import datetime

from mongo_logger import MongoLogger
from gameRoom import GameRoom
from player import Player

# --- Constants ---
HOST = '127.0.0.1'
PORT = 5555
HEADER_LENGTH = 10


# --- Game Logic (Simplified Codenames Board) ---
ALL_WORDS = [
    "APPLE", "BAKER", "CLOUD", "DREAM", "EAGLE", "FENCE", "GLOVE", "HOUSE", "INDIA", "JUMBO",
    "KNIFE", "LAUNCH", "MISSION", "NEPTUNE", "ORBIT", "PULSE", "QUEEN", "ROBOT", "SATELLITE",
    "TIGER", "UMBRELLA", "VENUS", "VOYAGER", "ZORRO", "ZEBRA", "SPIDER", "MERCURY", "DESK",
    "DOG", "CAT", "STRAW", "GRAPE", "CAR", "PLANE", "DRIVE", "BIRD", "FISH", "CRANE", "BLOCK",
    "BOARD", "GAME", "PLAY", "RUN", "JUMP", "DANCE", "SING", "ART", "BOOK", "READ"
]

class CodenamesServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(5)
        print(f"Server listening on {self.host}:{self.port}")
        self.clients = {}
        self.connected_clients = {}
        self.rooms = {}
        self.lobby_chat = []
        self.running = True
        self.lock = threading.RLock()
        self.mongo_logger = MongoLogger()

        
    def start_heartbeat_sender(self, backup_host='127.0.0.1', backup_port=5556, interval=1):
        """Send UDP heartbeat packets periodically to the backup server."""
        self.heartbeat_running = True
        self.backup_addr = (backup_host, backup_port)
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        def heartbeat_loop():
            while self.heartbeat_running:
                try:
                    self.udp_sock.sendto(b"PRIMARY_HEARTBEAT", self.backup_addr)
                except Exception as e:
                    print(f"Heartbeat send error: {e}")
                time.sleep(interval)
        
        threading.Thread(target=heartbeat_loop, daemon=True).start()
    
    def stop_heartbeat_sender(self):
        self.heartbeat_running = False
        if hasattr(self, 'udp_sock'):
            self.udp_sock.close()

    def start(self):
        threading.Thread(target=self._accept_connections, daemon=True).start()
        threading.Thread(target=self._update_clients_periodically, daemon=True).start()
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Server shutting down...")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        with self.lock:
            for client_fileno in list(self.clients.keys()):
                try:
                    self.clients[client_fileno]["socket"].shutdown(socket.SHUT_RDWR)
                    self.clients[client_fileno]["socket"].close()
                except Exception as e:
                    print(f"Error closing client socket {client_fileno}: {e}")
            self.clients.clear()
            self.connected_clients.clear()
            self.rooms.clear()
        self.sock.close()
        print("Server stopped.")

    def _accept_connections(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
                conn.setblocking(False)
                client_fileno = conn.fileno()
                print(f"Accepted connection from {addr} (fileno: {client_fileno})")
                with self.lock:
                    self.connected_clients[client_fileno] = Player(client_fileno, f"Guest_{client_fileno}")
                    self.clients[client_fileno] = {"socket": conn, "player_obj": self.connected_clients[client_fileno]}
                self.mongo_logger.log_event("client_connected", {"fileno": client_fileno, "ip_address": addr[0], "port": addr[1]})
                threading.Thread(target=self._handle_client, args=(client_fileno,), daemon=True).start()
            except socket.timeout:
                pass
            except Exception as e:
                if self.running:
                    print(f"Error accepting connection: {e}")
                break

    def _handle_client(self, client_fileno):
        with self.lock:
            client_info = self.clients.get(client_fileno)
            if not client_info: return
            client_sock = client_info["socket"]
        try:
            while self.running:
                readable, _, _ = select.select([client_sock], [], [], 0.1)
                if client_sock in readable:
                    header = client_sock.recv(HEADER_LENGTH)
                    if not header:
                        print(f"Client {client_fileno} disconnected.")
                        break
                    msg_len = int(header.decode('utf-8').strip())
                    full_message_bytes = b''
                    while len(full_message_bytes) < msg_len:
                        chunk = client_sock.recv(msg_len - len(full_message_bytes))
                        if not chunk:
                            print(f"Client {client_fileno} disconnected during message body read.")
                            break
                        full_message_bytes += chunk
                    if len(full_message_bytes) < msg_len:
                        break
                    message = json.loads(full_message_bytes.decode('utf-8'))
                    self._process_message(client_fileno, message)
        except ConnectionResetError:
            print(f"Client {client_fileno} connection reset by peer.")
        except ValueError:
            print(f"Invalid message header from client {client_fileno}.")
        except json.JSONDecodeError:
            print(f"Invalid JSON message from client {client_fileno}.")
        except Exception as e:
            if self.running:
                print(f"Error in _handle_client for {client_fileno}: {e}\n{traceback.format_exc()}")
        finally:
            self._cleanup_client(client_fileno)

    def _process_message(self, client_fileno, message):
        mtype = message.get("type")
        with self.lock:
            player_obj = self.connected_clients.get(client_fileno)
            if not player_obj: return
            client_name = player_obj.name
            current_room_id = player_obj.room_id

            if mtype == "join":
                new_name = message.get("name", f"Guest_{client_fileno}")
                if any(p.name == new_name for f, p in self.connected_clients.items() if f != client_fileno):
                    self._send_to_client(client_fileno, {"type": "error", "message": f"Username '{new_name}' is already taken. Please choose another."})
                    return
                player_obj.name = new_name
                self._add_lobby_chat_message(f"{new_name} joined the lobby.", is_system=True)
                print(f"{client_name} (fileno {client_fileno}) changed name to {new_name}.")
                self.mongo_logger.log_event("player_named", {"fileno": client_fileno, "new_name": new_name})
                self._broadcast_lobby_update()
            elif mtype == "chat":
                text = message.get("text", "")
                if text:
                    if current_room_id:
                        room = self.rooms.get(current_room_id)
                        if room:
                            room.add_chat_message(f"{client_name}: {text}")
                            self.mongo_logger.log_event("room_chat", {"room_id": current_room_id, "player_name": client_name, "message": text})
                    else:
                        self._add_lobby_chat_message(f"{client_name}: {text}")
                        self.mongo_logger.log_event("lobby_chat", {"player_name": client_name, "message": text})
            elif mtype == "create_room":
                room_name = message.get("name", f"Room_{random.randint(1000, 9999)}")
                new_room_id = f"room_{len(self.rooms) + 1}"
                if current_room_id:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Please leave current room first."})
                    return
                new_room = GameRoom(new_room_id, client_fileno, self, room_name)
                self.rooms[new_room_id] = new_room
                new_room.add_client(client_fileno, client_name)
                self._add_lobby_chat_message(f"{client_name} created room '{room_name}'.", is_system=True)
                print(f"{client_name} created room {new_room_id}.")
                self.mongo_logger.log_event("room_created", {"room_id": new_room_id, "room_name": room_name, "owner_fileno": client_fileno, "owner_name": client_name})
                self._send_to_client(client_fileno, {"type": "room_created", "room_id": new_room_id, "name": room_name, "owner_fileno": client_fileno})
                self._broadcast_lobby_update()
            elif mtype == "join_room":
                target_room_id = message.get("room_id")
                room = self.rooms.get(target_room_id)
                if not room:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Room not found."})
                    return
                if room.game_in_progress:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Cannot join: Game in progress."})
                    return
                if current_room_id:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Please leave current room first."})
                    return
                room.add_client(client_fileno, client_name)
                self._add_lobby_chat_message(f"{client_name} joined room '{target_room_id}'.", is_system=True)
                print(f"{client_name} joined room {target_room_id}.")
                self.mongo_logger.log_event("room_joined", {"room_id": target_room_id, "player_fileno": client_fileno, "player_name": client_name})
                self._send_to_client(client_fileno, {"type": "room_joined", "room_id": target_room_id, "owner_fileno": room.owner_fileno})
                self._broadcast_lobby_update()
            elif mtype == "leave_room":
                if current_room_id:
                    room = self.rooms.get(current_room_id)
                    if room:
                        room.remove_client(client_fileno)
                        self.mongo_logger.log_event("room_left", {"room_id": current_room_id, "player_fileno": client_fileno, "player_name": client_name})
                        if not room.clients:
                            del self.rooms[current_room_id]
                            print(f"Room {current_room_id} deleted as it is empty.")
                            self.mongo_logger.log_event("room_deleted", {"room_id": current_room_id})
                        self._add_lobby_chat_message(f"{client_name} left room '{current_room_id}'.", is_system=True)
                    print(f"{client_name} left room {current_room_id}.")
                    self._send_to_client(client_fileno, {"type": "room_left"})
                    self._broadcast_lobby_update()
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Not in a room to leave."})
            elif mtype == "set_team":
                team_choice = message.get("team")
                if team_choice in ["red", "blue"] and player_obj.room_id:
                    player_obj.chosen_team = team_choice
                    print(f"Player {player_obj.name} (fileno {client_fileno}) chose team: {team_choice}")
                    self.mongo_logger.log_event("team_chosen", {"player_fileno": client_fileno, "player_name": player_obj.name, "chosen_team": team_choice})
                    self._send_to_client(client_fileno, {"type": "team_set_ack", "team": team_choice})
                    self._broadcast_lobby_update()
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Invalid team choice or not in a room."})
            elif mtype == "start_game_request":
                if current_room_id:
                    room = self.rooms.get(current_room_id)
                    if room and client_fileno == room.owner_fileno:
                        success, msg = room.start_game()
                        if not success:
                            self._send_to_client(client_fileno, {
                                "type": "guess_feedback",
                                "message": msg,
                                "guess": None,
                                "clue": room.clue_word,
                                "team": player_obj.team,
                                "turn": room.turn
                            })
                        else:
                            # self.mongo_logger.log_event("game_started", {"room_id": current_room_id})
                            self._send_to_client(client_fileno, {"type": "game_start_ack", "message": msg})
                            self._broadcast_lobby_update()
                    else:
                        self._send_to_client(client_fileno, {"type": "error", "message": "Only the room owner can start the game."})
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Not in a room to start a game."})
            
            
            elif mtype == "clue":
                word = message.get("word")
                number = message.get("number")
                if current_room_id:
                    room = self.rooms.get(current_room_id)
                    if room and room.game_in_progress:
                        success, msg = room.process_clue(client_fileno, word, number)
                        success, msg = room.process_guess(client_fileno, word)
                        if not success:
                            self._send_to_client(client_fileno, {
                                "type": "guess_feedback",
                                "message": msg,
                                "guess": word,
                                "clue": room.clue_word,
                                "team": player_obj.team,
                                "turn": room.turn
                            })
                    else:
                        self._send_to_client(client_fileno, {"type": "error", "message": "No game in progress in this room."})
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Not in a room."})



            elif mtype == "guess":
                word = message.get("word")
                if current_room_id:
                    room = self.rooms.get(current_room_id)
                    if room and room.game_in_progress:
                        success, msg = room.process_guess(client_fileno, word)
                        self.mongo_logger.log_event("guess_made", {"room_id": current_room_id, "player_fileno": client_fileno, "player_name": client_name, "guessed_word": word, "result": msg})
                        self._send_to_client(client_fileno, {"type": "info", "message": msg})
                        if success:
                            self._broadcast_game_state_to_room(current_room_id)
                    else:
                        self._send_to_client(client_fileno, {"type": "error", "message": "No game in progress in this room."})
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Not in a room."})
            
            elif mtype == "end_turn":
                if current_room_id:
                    room = self.rooms.get(current_room_id)
                    if room and room.game_in_progress:
                        success, msg = room.process_end_turn(client_fileno)
                        if not success:
                            self._send_to_client(client_fileno, {
                                "type": "guess_feedback",
                                "message": msg,
                                "guess": word,
                                "clue": room.clue_word,
                                "team": player_obj.team,
                                "turn": room.turn
                            })
                    else:
                        self._send_to_client(client_fileno, {"type": "error", "message": "No game in progress in this room."})
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Not in a room."})
            



            elif mtype == "refresh_lobby":
                self._broadcast_lobby_update()
            else:
                print(f"Unknown message type from {client_name} ({client_fileno}): {mtype}")

    def _add_lobby_chat_message(self, message, is_system=False):
        with self.lock:
            prefix = "[SYSTEM] " if is_system else ""
            self.lobby_chat.append(f"{prefix}{message}")
            if len(self.lobby_chat) > 50:
                self.lobby_chat = self.lobby_chat[-50:]

    def _send_to_client(self, client_fileno, message):
        with self.lock:
            client_info = self.clients.get(client_fileno)
            if client_info:
                try:
                    data = json.dumps(message).encode('utf-8')
                    header = f"{len(data):<{HEADER_LENGTH}}".encode('utf-8')
                    client_info["socket"].sendall(header + data)
                except Exception as e:
                    print(f"Error sending to client {client_fileno}: {e}")
                    self._cleanup_client(client_fileno)

    def _broadcast_to_lobby(self, message):
        with self.lock:
            for fileno, client_info in self.clients.items():
                if client_info["player_obj"].room_id is None:
                    self._send_to_client(fileno, message)

    def _broadcast_to_room(self, room_id, message):
        with self.lock:
            room = self.rooms.get(room_id)
            if room:
                for fileno in room.clients.keys():
                    self._send_to_client(fileno, message)

    def _broadcast_lobby_update(self):
        with self.lock:
            lobby_update_message = {
                "type": "lobby_update",
                "players": [p.name for p in self.connected_clients.values() if p.room_id is None],
                "rooms": [room.get_room_info() for room in self.rooms.values()],
                "chat": self.lobby_chat
            }
            self._broadcast_to_lobby(lobby_update_message)

    def _update_clients_periodically(self):
        while self.running:
            self._broadcast_lobby_update()
            with self.lock:
                for room_id, room in list(self.rooms.items()):
                    if room.game_in_progress:
                        for client_fileno in list(room.clients.keys()):
                            game_state_message = room.get_game_state_for_client(client_fileno)
                            self._send_to_client(client_fileno, game_state_message)
            time.sleep(0.1)

    def _cleanup_client(self, client_fileno):
        with self.lock:
            if client_fileno in self.clients:
                client_info = self.clients.pop(client_fileno)
                player_obj = client_info["player_obj"]
                client_name = player_obj.name
                room_id = player_obj.room_id
                self.mongo_logger.log_event("client_disconnected", {"fileno": client_fileno, "player_name": client_name})
                if room_id:
                    room = self.rooms.get(room_id)
                    if room:
                        room.remove_client(client_fileno)
                        if not room.clients:
                            del self.rooms[room_id]
                            self.mongo_logger.log_event("room_deleted", {"room_id": room_id})
                            print(f"Room {room_id} deleted as it is empty.")
                self.connected_clients.pop(client_fileno, None)
                try:
                    client_info["socket"].close()
                except Exception as e:
                    print(f"Error closing socket during cleanup for {client_fileno}: {e}")
                self._add_lobby_chat_message(f"{client_name} disconnected from the server.", is_system=True)
                self._broadcast_lobby_update()
                print(f"Cleaned up client {client_name} ({client_fileno}).")

    def _broadcast_game_state_to_room(self, room_id):
        room = self.rooms.get(room_id)
        if room:
            for fileno in room.clients:
                game_state = room.get_game_state_for_client(fileno)
                self._send_to_client(fileno, game_state)
