import pygame
import socket
import threading
import json
import time
import random
import sys
import traceback # For better error debugging
import select # Import the select module for non-blocking I/O

# --- Constants ---
WIDTH, HEIGHT = 1000, 650
FPS = 60
HEADER_LENGTH = 10 # Must match server's HEADER_LENGTH

# Colors
BG_COLOR = (25, 25, 35)
PANEL_COLOR = (40, 40, 55)
ACCENT_COLOR = (90, 150, 200)
TEXT_COLOR = (220, 220, 230)
HIGHLIGHT_COLOR = (120, 180, 250)
ERROR_COLOR = (255, 100, 100)

# Card Colors
RED_CARD = (190, 60, 60)
BLUE_CARD = (60, 60, 190)
INNOCENT_CARD = (120, 120, 120)
ASSASSIN_CARD = (30, 30, 30)
REVEALED_TEXT_COLOR = (255, 255, 255)
CARD_BORDER_COLOR = (80, 80, 80)

pygame.init()

# Fonts
FONT_SMALL = pygame.font.SysFont('Arial', 16)
FONT = pygame.font.SysFont('Arial', 20)
FONT_MEDIUM = pygame.font.SysFont('Arial', 24, bold=True)
FONT_LARGE = pygame.font.SysFont('Arial', 32, bold=True)
GAME_OVER_FONT = pygame.font.SysFont('Arial', 48, bold=True)

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5555

# --- UI Element Classes ---
class InputBox:
    """A simple input box for text entry."""
    def __init__(self, x, y, w, h, text='', placeholder='', font=FONT, is_enabled=True):
        self.rect = pygame.Rect(x, y, w, h)
        self.color = PANEL_COLOR
        self.text_color = TEXT_COLOR
        self.active_border_color = ACCENT_COLOR
        self.inactive_border_color = (80, 80, 95)
        self.disabled_color = (60, 60, 75)
        self.disabled_text_color = (150, 150, 150)
        self.text = text
        self.placeholder = placeholder
        self.font = font
        self.active = False
        self.is_enabled = is_enabled
        self.border_radius = 5
        self._update_surface()

    def _update_surface(self):
        """Renders the current text or placeholder to a surface."""
        current_text_color = self.text_color if self.is_enabled else self.disabled_text_color
        display_text = self.text if self.text else self.placeholder
        self.txt_surface = self.font.render(display_text, True, current_text_color)

    def handle_event(self, event):
        """Handles Pygame events for the input box."""
        if not self.is_enabled:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key != pygame.K_RETURN: # Ignore Enter key press
                self.text += event.unicode
            self._update_surface()
        return False

    def draw(self, screen):
        """Draws the input box on the screen."""
        current_bg_color = self.color if self.is_enabled else self.disabled_color
        pygame.draw.rect(screen, current_bg_color, self.rect, border_radius=self.border_radius)
        
        border_color = self.inactive_border_color
        if self.is_enabled:
            border_color = self.active_border_color if self.active else self.inactive_border_color
        pygame.draw.rect(screen, border_color, self.rect, 2, border_radius=self.border_radius)
        
        text_x = self.rect.x + 8
        text_y = self.rect.y + (self.rect.height - self.txt_surface.get_height()) // 2
        screen.blit(self.txt_surface, (text_x, text_y))

    def get_text(self):
        """Returns the current text in the input box."""
        return self.text

    def clear_text(self):
        """Clears the text in the input box."""
        self.text = ''
        self._update_surface()

    def set_enabled(self, enabled):
        """Enables or disables the input box."""
        self.is_enabled = enabled
        if not enabled:
            self.active = False
        self._update_surface() # Update surface to reflect disabled state color


class Button:
    """A clickable button."""
    def __init__(self, x, y, w, h, text, action=None, font=FONT, is_enabled=True, base_color=None, hover_color=None):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = text
        self.action = action
        self.font = font
        self.text_color = TEXT_COLOR
        self.base_color = base_color if base_color else (60, 60, 75)
        self.hover_color = hover_color if hover_color else ACCENT_COLOR
        # More distinct disabled colors
        self.disabled_color = (30, 30, 40) # Darker background
        self.disabled_text_color = (80, 80, 80) # More faded text
        self.border_radius = 8
        self.shadow_offset = 3
        self.shadow_color = (20, 20, 25)
        self.is_enabled = is_enabled

    def draw(self, screen, mouse_pos):
        """Draws the button on the screen."""
        current_bg_color = self.base_color
        current_text_color = self.text_color

        if not self.is_enabled:
            current_bg_color = self.disabled_color
            current_text_color = self.disabled_text_color
        elif self.rect.collidepoint(mouse_pos):
            current_bg_color = self.hover_color
        
        if self.is_enabled:
            shadow_rect = pygame.Rect(self.rect.x + self.shadow_offset, self.rect.y + self.shadow_offset,
                                      self.rect.width, self.rect.height)
            pygame.draw.rect(screen, self.shadow_color, shadow_rect, border_radius=self.border_radius)

        pygame.draw.rect(screen, current_bg_color, self.rect, border_radius=self.border_radius)
        
        text_surface = self.font.render(self.text, True, current_text_color)
        text_rect = text_surface.get_rect(center=self.rect.center)
        screen.blit(text_surface, text_rect)

    def handle_event(self, event):
        """Handles Pygame events for the button."""
        if not self.is_enabled:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                if self.action:
                    self.action()
                return True
        return False

    def set_enabled(self, enabled):
        """Enables or disables the button."""
        self.is_enabled = enabled


# --- Codenames Client Class ---
class CodenamesClient:
    """Manages the Codenames game client, including UI and network communication."""
    def __init__(self):
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Codenames Lobby & Game")

        self.clock = pygame.time.Clock()

        self.client = None
        self.connected = False
        self.logged_in = False
        self.username = ""
        self.client_fileno = None # This client's socket file descriptor

        self.lobby_players = [] # List of player names in lobby
        self.lobby_rooms = []   # List of room dicts in lobby
        self.lobby_chat = []    # List of chat messages

        self.current_room_id = None
        self.current_room_owner_fileno = None # Fileno of the owner of the current room

        # UI Elements
        self._init_ui_elements()

        # Game state
        self.game_active = False
        self.game_board = [] # List of {"word": str, "color": str, "revealed": bool}
        self.red_score = 0
        self.blue_score = 0
        self.current_turn = None # "red" or "blue"
        self.clue_word = ""
        self.clue_number = 0
        self.guesses_made = 0
        self.game_over = False
        self.winner = None

        # Role assignments for the current game
        self.is_spymaster = False # Is THIS client a spymaster (red OR blue)
        self.spymaster_red_fileno = None
        self.spymaster_blue_fileno = None
        self.operative_red_filenos = []
        self.operative_blue_filenos = []

        # Client's own assigned team/role (received from server)
        self.my_assigned_team = None # "red", "blue", or "neutral"
        self.my_assigned_role = None # "spymaster", "operative", or "spectator"

        # Player's preferred team (sent to server)
        self.my_chosen_team = None # "red", "blue", or None

        self.running = True
        self.listen_thread = None
        self.game_start_requested = False # Flag to avoid multiple start requests

    def _init_ui_elements(self):
        """Initializes all UI elements."""
        self.name_input = InputBox(WIDTH // 2 - 100, HEIGHT // 2 - 20, 200, 40, placeholder="Enter your name")
        self.connect_button = Button(WIDTH // 2 - 75, HEIGHT // 2 + 40, 150, 40, "Connect", self._try_connect)

        self.create_room_input = InputBox(50, HEIGHT - 60, 200, 40, placeholder="New room name")
        self.create_room_button = Button(260, HEIGHT - 60, 120, 40, "Create Room", self._send_create_room)
        self.chat_input = InputBox(400, HEIGHT - 60, 350, 40, placeholder="Type chat message")
        self.send_chat_button = Button(760, HEIGHT - 60, 80, 40, "Send", self._send_chat_message)
        
        self.refresh_lobby_button = Button(WIDTH - 120, 30, 100, 35, "Refresh", self._send_lobby_refresh_request, font=FONT_SMALL)

        # Team selection buttons
        self.red_team_button = Button(WIDTH // 2 - 120, HEIGHT // 2 - 50, 100, 40, "Join Red", 
                                      lambda: self._send_set_team("red"), base_color=RED_CARD, hover_color=(220, 80, 80))
        self.blue_team_button = Button(WIDTH // 2 + 20, HEIGHT // 2 - 50, 100, 40, "Join Blue", 
                                       lambda: self._send_set_team("blue"), base_color=BLUE_CARD, hover_color=(80, 80, 220))

        self.clue_word_input = InputBox(50, HEIGHT - 100, 150, 40, placeholder="Clue Word")
        
        self.send_clue_button = Button(300, HEIGHT - 100, 100, 40, "Send Clue", self._send_clue)
        self.end_turn_button = Button(WIDTH - 150, HEIGHT - 100, 120, 40, "End Turn", self._send_end_turn)

    def _draw_text(self, text, font, color, x, y, center=True):
        """Helper to draw text on the screen."""
        text_surface = font.render(text, True, color)
        text_rect = text_surface.get_rect()
        if center:
            text_rect.center = (x, y)
        else:
            text_rect.topleft = (x, y)
        self.screen.blit(text_surface, text_rect)

    def _send_message(self, message):
        """Sends a JSON message with a fixed-size header to the server."""
        if self.connected and self.client:
            try:
                json_message = json.dumps(message)
                message_header = f"{len(json_message):<{HEADER_LENGTH}}".encode('utf-8')
                self.client.sendall(message_header + json_message.encode('utf-8'))
                print(f"[CLIENT] messageSent message_header: {message_header.decode('utf-8')}")
                print(f"[CLIENT] messageSent json_message: {json_message}")
                print(f"[CLIENT] messageSent json_messageEncode: {json_message.encode('utf-8')}")
                print(f"[CLIENT] messageSent type: {message.get('type')}")
            except Exception as e:
                print(f"[CLIENT ERROR] Error sending message: {e}")
                self._reset_connection_state()

    def _receive_message(self):
        """Receives a JSON message with a fixed-size header from the server."""
        try:
            message_header = self.client.recv(HEADER_LENGTH)
            if not len(message_header):
                return None # Server disconnected

            message_length = int(message_header.decode('utf-8').strip())
            full_message = b''
            while len(full_message) < message_length:
                chunk = self.client.recv(message_length - len(full_message))
                if not chunk:
                    return None # Server disconnected during message receive
                full_message += chunk
            
            if not full_message: # Handle case where chunk was empty and loop ended
                return None

            message = json.loads(full_message.decode('utf-8'))


            #  To see the receive_messages
            # print(f"[CLIENT] receive_message message_header: {message_header.decode('utf-8')}")
            # print(f"[CLIENT] receive_message full_message: {full_message.decode('utf-8')}")
            # print(f"[CLIENT] receive_message message: {message}")
            # print(f"[CLIENT] receive_message type: {message.get('type')}")




            return message

        except ValueError:
            print(f"[CLIENT ERROR] Malformed header from server.")
            return None
        except json.JSONDecodeError:
            print(f"[CLIENT ERROR] Malformed JSON from server.")
            return None
        except BlockingIOError: # Catch this specific error for non-blocking sockets
            return "NO_DATA" # Indicate no data available yet
        except Exception as e:
            # print(f"[CLIENT ERROR] Error receiving message: {e}")
            return None

    def _try_connect(self):
        """Attempts to connect to the server."""
        self.username = self.name_input.get_text().strip()
        if not self.username:
            print("[CLIENT] Please enter a username.")
            return

        try:
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.connect((SERVER_HOST, SERVER_PORT))
            self.client.setblocking(False) # Set to non-blocking for event loop
            self.connected = True
            
            # Send join message immediately upon connection
            join_message = {"type": "join", "name": self.username}
            self._send_message(join_message)
            self.client_fileno = self.client.fileno() # Get client's socket fileno
            print(f"[CLIENT] Connected to server as {self.username} (socket {self.client_fileno}).")

            self.listen_thread = threading.Thread(target=self._listen_server, daemon=True)
            self.listen_thread.start()
            self.logged_in = True # Assume login success after sending join, server will validate
        except Exception as e:
            print(f"[CLIENT] Connection failed: {e}")
            self._reset_connection_state()

    def _listen_server(self):
        """Listens for messages from the server."""
        while self.running:
            try:
                # Use select to check if the socket is readable before attempting to recv
                readable, _, _ = select.select([self.client], [], [], 0.05) # Small timeout
                if self.client in readable:
                    message = self._receive_message()
                    if message is None: # Server disconnected or error during receive
                        print("[CLIENT] Server disconnected or error during receive.")
                        self._reset_connection_state()
                        break
                    elif message == "NO_DATA": # No data available yet, continue loop
                        continue
                    
                    self._handle_message(message)
                else:
                    # No data to read, continue checking self.running and re-select
                    pass
            except Exception as e:
                print(f"[CLIENT] Error in listen_server: {e}\n{traceback.format_exc()}")
                self._reset_connection_state()
                break

    def _handle_message(self, message):
        """Processes incoming messages from the server."""
        mtype = message.get("type")
        # print(f"[CLIENT_DEBUG] handle_message called for type: {mtype}") # Too verbose

        if mtype == "lobby_update":
            self.lobby_players = message.get("players", [])
            self.lobby_rooms = message.get("rooms", [])
            self.lobby_chat = message.get("chat", [])
            # print("[CLIENT] Lobby updated.")
            
            # Update current_room_owner_fileno from lobby_update if in a room
            if self.current_room_id:
                for room_info in self.lobby_rooms:
                    if room_info['id'] == self.current_room_id:
                        self.current_room_owner_fileno = room_info.get('owner_fileno')
                        # print(f"[CLIENT_DEBUG] Updated current_room_owner_fileno from lobby_update: {self.current_room_owner_fileno}")
                        break
            
            # Reset game_start_requested if game was supposed to start but isn't
            if self.game_start_requested and not any(r['game_in_progress'] for r in self.lobby_rooms if r['id'] == self.current_room_id):
                self.game_start_requested = False 

        elif mtype == "game_state_update":
            # print(f"[RECV] Game state update: {message}")
            self.game_board = message["board"]
            self.red_score = message["red_score"]
            self.blue_score = message["blue_score"]
            self.current_turn = message["turn"]
            self.clue_word = message["clue_word"]
            self.clue_number = message["clue_number"]
            self.guesses_made = message["guesses_made"]
            self.game_over = message["game_over"]
            self.winner = message["winner"]
            
            # Update role assignments from server
            self.is_spymaster = message["is_spymaster"]
            self.spymaster_red_fileno = message["spymaster_red"]
            self.spymaster_blue_fileno = message["spymaster_blue"]
            self.operative_red_filenos = message["operative_red"]
            self.operative_blue_filenos = message["operative_blue"]

            # Update client's own assigned team and role
            self.my_assigned_team = message.get("my_team")
            self.my_assigned_role = message.get("my_role")
            
            # Debug prints for role and turn
            # print(f"[CLIENT_DEBUG] Client Fileno: {self.client_fileno}")
            # print(f"[CLIENT_DEBUG] Red Spymaster Fileno: {self.spymaster_red_fileno}")
            # print(f"[CLIENT_DEBUG] Blue Spymaster Fileno: {self.spymaster_blue_fileno}")
            # print(f"[CLIENT_DEBUG] Is this client a Spymaster? {self.is_spymaster}")
            # print(f"[CLIENT_DEBUG] Current Turn: {self.current_turn}")
            # print(f"[CLIENT_DEBUG] Operative Red: {self.operative_red_filenos}")
            # print(f"[CLIENT_DEBUG] Operative Blue: {self.operative_blue_filenos}")
            # print(f"[CLIENT_DEBUG] My Assigned Team: {self.my_assigned_team}, My Assigned Role: {self.my_assigned_role}")
            
            self.game_active = True
            self.game_start_requested = False # Reset this flag
            # print("[CLIENT] Game state updated. Switching to game view.")
        
        elif mtype == "room_created":
            room_id = message.get("room_id")
            room_name = message.get("name")
            owner_fileno = message.get("owner_fileno")
            print(f"[CLIENT] Room '{room_name}' (ID: {room_id}) created!")
            self.current_room_id = room_id
            self.current_room_owner_fileno = owner_fileno
            self.game_active = False # Not active until game starts
            self.my_chosen_team = None # Reset chosen team when entering a new room

        elif mtype == "room_joined":
            room_id = message.get("room_id")
            owner_fileno = message.get("owner_fileno")
            print(f"[CLIENT] Joined room: {room_id}")
            self.current_room_id = room_id
            self.current_room_owner_fileno = owner_fileno
            self.game_active = False
            self.my_chosen_team = None # Reset chosen team when entering a new room

        elif mtype == "room_left":
            print("[CLIENT] Left room.")
            self.current_room_id = None
            self.current_room_owner_fileno = None
            self.game_active = False # Game is no longer active for this client
            self.my_chosen_team = None # Reset chosen team when leaving room
            self.my_assigned_team = None
            self.my_assigned_role = None

        elif mtype == "team_set_ack":
            self.my_chosen_team = message.get("team")
            print(f"[CLIENT] Team choice acknowledged: {self.my_chosen_team}")

        elif mtype == "game_start_ack":
            print(f"[CLIENT] Game start acknowledged: {message.get('message', 'Game started!')}")

        elif mtype == "error":
            print(f"[CLIENT] Server Error: {message.get('message', 'An unknown error occurred.')}")

        else:
            print(f"[CLIENT] Unknown message type: {mtype}")

    def _send_chat_message(self):
        """Sends a chat message to the server."""
        text = self.chat_input.get_text()
        if text:
            message = {"type": "chat", "text": text}
            self._send_message(message)
            self.chat_input.clear_text()

    def _send_create_room(self):
        """Sends a request to create a new room."""
        room_name = self.create_room_input.get_text()
        if not room_name:
            room_name = f"Room {random.randint(1000, 9999)}"
        message = {"type": "create_room", "name": room_name}
        self._send_message(message)
        self.create_room_input.clear_text()

    def _send_join_room(self, room_id):
        """Sends a request to join a specific room."""
        message = {"type": "join_room", "room_id": room_id}
        self._send_message(message)

    def _send_leave_room(self):
        """Sends a request to leave the current room."""
        message = {"type": "leave_room"}
        self._send_message(message)

    def _send_set_team(self, team_choice):
        """Sends the player's chosen team to the server."""
        if self.current_room_id and not self.game_active:
            message = {"type": "set_team", "team": team_choice}
            self._send_message(message)
        else:
            print("[CLIENT] Cannot set team: Not in a room or game is active.")

    def _send_start_game_request(self):
        """Sends a request to start the game in the current room."""
        if self.current_room_id and not self.game_start_requested:
            message = {"type": "start_game_request"}
            self._send_message(message)
            self.game_start_requested = True # Set flag to prevent spamming
            print("[CLIENT] Sent start game request.")
        elif self.game_start_requested:
            print("[CLIENT] Game start already requested. Waiting for server.")
        else:
            print("[CLIENT] Not in a room to start a game.")

    def _send_clue(self):
        """Sends a clue to the server (Spymaster action)."""
        clue_word = self.clue_word_input.get_text().strip()
        
        try:
            clue_number = int(1)
            if not clue_word or not (1 <= clue_number <= 9): # Clue number should be 1-9
                print("[CLIENT] Invalid clue. Word and number (1-9) are required.")
                return


            # self._send_guess(clue_word)


            message = {"type": "clue", "word": clue_word, "number": clue_number}
            self._send_message(message)
            self.clue_word_input.clear_text()
        except ValueError:
            print("[CLIENT] Clue number must be an integer.")

    def _send_guess(self, word):
        """Sends a guess to the server (Operative action)."""
        message = {"type": "guess", "word": word}
        self._send_message(message)
        # No immediate game state update here, wait for server response
        # time.sleep(0.1) # Small delay to prevent multiple rapid clicks, but server response is better

    def _send_end_turn(self):
        """Sends a request to end the current turn."""
        message = {"type": "end_turn"}
        self._send_message(message)

    def _send_lobby_refresh_request(self):
        """Sends a request to the server to refresh the lobby."""
        message = {"type": "refresh_lobby"}
        self._send_message(message)
        print("[CLIENT] Sent lobby refresh request.")

    def _reset_connection_state(self):
        """Resets client state upon disconnection."""
        self.connected = False
        self.logged_in = False
        self.game_active = False
        self.current_room_id = None
        self.current_room_owner_fileno = None
        self.game_start_requested = False
        self.lobby_players = []
        self.lobby_rooms = []
        self.lobby_chat = []
        # Clear game state as well
        self.game_board = []
        self.red_score = 0
        self.blue_score = 0
        self.current_turn = None
        self.clue_word = ""
        self.clue_number = 0
        self.guesses_made = 0
        self.game_over = False
        self.winner = None
        self.is_spymaster = False
        self.spymaster_red_fileno = None
        self.spymaster_blue_fileno = None
        self.operative_red_filenos = []
        self.operative_blue_filenos = []
        self.my_assigned_team = None
        self.my_assigned_role = None
        self.my_chosen_team = None

        if self.client:
            self.client.close()
        print("[CLIENT] Connection state reset.")

    def _draw_lobby(self, mouse_pos):
        """Draws the main lobby screen."""
        ui_elements = []
        self.screen.fill(BG_COLOR)

        self._draw_text("Codenames Lobby", FONT_LARGE, TEXT_COLOR, WIDTH // 2, 30)

        # Refresh button
        self.refresh_lobby_button.rect.topright = (WIDTH - 20, 30)
        self.refresh_lobby_button.draw(self.screen, mouse_pos)
        ui_elements.append(self.refresh_lobby_button)

        # Players List Panel
        player_panel_rect = pygame.Rect(20, 70, 250, HEIGHT - 250)
        pygame.draw.rect(self.screen, PANEL_COLOR, player_panel_rect, border_radius=10)
        self._draw_text("Online Players:", FONT_MEDIUM, TEXT_COLOR, player_panel_rect.x + 10, player_panel_rect.y + 10, center=False)
        
        y_offset = player_panel_rect.y + 50
        for i, pname in enumerate(self.lobby_players):
            self._draw_text(pname, FONT_SMALL, HIGHLIGHT_COLOR if pname == self.username else TEXT_COLOR, player_panel_rect.x + 20, y_offset + i * 25, center=False)

        # Rooms List Panel
        room_panel_rect = pygame.Rect(290, 70, WIDTH - 310, HEIGHT - 250)
        pygame.draw.rect(self.screen, PANEL_COLOR, room_panel_rect, border_radius=10)
        self._draw_text("Available Rooms:", FONT_MEDIUM, TEXT_COLOR, room_panel_rect.x + 10, room_panel_rect.y + 10, center=False)

        # Create Room Input & Button
        self.create_room_input.rect.topleft = (room_panel_rect.x + 10, room_panel_rect.y + 50)
        self.create_room_input.rect.width = 200 # Fixed width
        self.create_room_input.draw(self.screen)
        ui_elements.append(self.create_room_input)

        self.create_room_button.rect.topleft = (self.create_room_input.rect.right + 10, room_panel_rect.y + 50)
        self.create_room_button.draw(self.screen, mouse_pos)
        ui_elements.append(self.create_room_button)


        # Room List Display
        room_list_start_y = room_panel_rect.y + 100
        for i, room in enumerate(self.lobby_rooms):
            y = room_list_start_y + i * 45
            room_entry_rect = pygame.Rect(room_panel_rect.x + 10, y, room_panel_rect.width - 20, 40)
            pygame.draw.rect(self.screen, (50, 50, 65), room_entry_rect, border_radius=5)
            
            status_text = "In Progress" if room.get('game_in_progress', False) else "Waiting"
            room_info_text = f"ID: {room['id']} - {room['name']} (Players: {room['players']}/8) - {status_text}"
            self._draw_text(room_info_text, FONT_SMALL, TEXT_COLOR, room_entry_rect.x + 10, room_entry_rect.y + 10, center=False)
            
            can_join = not room.get('game_in_progress', False) and self.current_room_id is None and room['players'] < 8
            join_btn = Button(room_entry_rect.right - 80, room_entry_rect.y + 5, 70, 30, "Join", 
                              lambda r_id=room['id']: self._send_join_room(r_id), font=FONT_SMALL, is_enabled=can_join)
            join_btn.draw(self.screen, mouse_pos)
            ui_elements.append(join_btn)

        # Chat Panel (bottom)
        chat_panel_rect = pygame.Rect(20, HEIGHT - 170, WIDTH - 40, 150)
        pygame.draw.rect(self.screen, PANEL_COLOR, chat_panel_rect, border_radius=10)
        self._draw_text("Lobby Chat", FONT_MEDIUM, TEXT_COLOR, chat_panel_rect.x + 10, chat_panel_rect.y + 15, center=False)

        # Display last chat message
        chat_msg_area_rect = pygame.Rect(chat_panel_rect.x + 10, chat_panel_rect.y + 50, chat_panel_rect.width - 20, 30)
        pygame.draw.rect(self.screen, (20, 20, 30), chat_msg_area_rect, border_radius=5)
        
        if self.lobby_chat:
            last_msg = self.lobby_chat[-1]
            self._draw_text(last_msg, FONT_SMALL, TEXT_COLOR, chat_msg_area_rect.x + 5, chat_msg_area_rect.y + 5, center=False)

        # Chat Input & Send Button
        self.chat_input.rect.topleft = (chat_panel_rect.x + 10, chat_panel_rect.y + 90)
        self.chat_input.rect.width = chat_panel_rect.width - 120
        self.chat_input.draw(self.screen)
        ui_elements.append(self.chat_input)
        
        self.send_chat_button.rect.topleft = (self.chat_input.rect.right + 5, chat_panel_rect.y + 90)
        self.send_chat_button.draw(self.screen, mouse_pos)
        ui_elements.append(self.send_chat_button)

        return ui_elements

    def _draw_room_lobby(self, mouse_pos):
        """Draws the room-specific lobby (waiting for game start)."""
        ui_elements = []
        self.screen.fill(BG_COLOR)

        current_room_info = next((r for r in self.lobby_rooms if r['id'] == self.current_room_id), None)
        
        room_name = current_room_info['name'] if current_room_info else "Unknown Room"
        
        self._draw_text(f"Room: {room_name} (ID: {self.current_room_id})", FONT_LARGE, TEXT_COLOR, WIDTH // 2, 50)
        self._draw_text("Waiting for game to start...", FONT_MEDIUM, HIGHLIGHT_COLOR, WIDTH // 2, 100)

        # Refresh button in room lobby
        self.refresh_lobby_button.rect.topright = (WIDTH - 20, 30)
        self.refresh_lobby_button.draw(self.screen, mouse_pos)
        ui_elements.append(self.refresh_lobby_button)

        # Display players in the room
        self._draw_text("Players in Room:", FONT_MEDIUM, TEXT_COLOR, WIDTH // 2, 150, center=True)
        
        y_offset = 180
        if current_room_info:
            players_in_room_count = current_room_info['players']
            owner_name = current_room_info['owner']

            self._draw_text(f"Current Players: {players_in_room_count}", FONT_MEDIUM, TEXT_COLOR, WIDTH // 2, y_offset, center=True)
            y_offset += 30
            self._draw_text(f"Room Owner: {owner_name}", FONT_MEDIUM, TEXT_COLOR, WIDTH // 2, y_offset, center=True)
            y_offset += 50 # Extra space for team choice

        # Team Selection
        self._draw_text("Choose your team:", FONT_MEDIUM, TEXT_COLOR, WIDTH // 2, y_offset, center=True)
        y_offset += 40

        self.red_team_button.rect.topleft = (WIDTH // 2 - 120, y_offset)
        self.blue_team_button.rect.topleft = (WIDTH // 2 + 20, y_offset)

        # Enable/disable team buttons based on current chosen team
        red_button_enabled = self.my_chosen_team != "red"
        blue_button_enabled = self.my_chosen_team != "blue"

        self.red_team_button.set_enabled(red_button_enabled)
        self.blue_team_button.set_enabled(blue_button_enabled)

        self.red_team_button.draw(self.screen, mouse_pos)
        self.blue_team_button.draw(self.screen, mouse_pos)
        ui_elements.append(self.red_team_button)
        ui_elements.append(self.blue_team_button)

        y_offset += 90
        if self.my_chosen_team:
            chosen_team_color = RED_CARD if self.my_chosen_team == "red" else BLUE_CARD
            self._draw_text(f"Your choice: {self.my_chosen_team.upper()}", FONT_MEDIUM, chosen_team_color, WIDTH // 2, y_offset, center=True)
        else:
            self._draw_text("No team chosen yet.", FONT_MEDIUM, TEXT_COLOR, WIDTH // 2, y_offset, center=True)

        y_offset += 30 # Space for start/leave buttons

        # Start Game Button (always enabled for room owner)
        is_owner = True
        players_in_room_count = current_room_info['players'] if current_room_info else 0
        
        start_game_btn = Button(WIDTH // 2 - 100, y_offset, 200, 50, "Start Game", self._send_start_game_request, is_enabled=is_owner)
        start_game_btn.draw(self.screen, mouse_pos)

        
        ui_elements.append(start_game_btn)

        # Add instructional text for the owner if game cannot start yet
        if is_owner and players_in_room_count < 2:
            self._draw_text("Need at least 2 players to start the game.", FONT_SMALL, ERROR_COLOR, WIDTH // 2, y_offset + 80, center=True)
        elif not is_owner:
            self._draw_text("Only the room owner can start the game.", FONT_SMALL, TEXT_COLOR, WIDTH // 2, y_offset + 80, center=True)


        # Leave Room Button
        leave_room_btn = Button(WIDTH // 2 - 100, y_offset + 110, 200, 50, "Leave Room", self._send_leave_room)
        leave_room_btn.draw(self.screen, mouse_pos)
        ui_elements.append(leave_room_btn)

        return ui_elements


    def _draw_game(self, mouse_pos):
        """Draws the active game board and controls."""
        ui_elements = []
        self.screen.fill(BG_COLOR)

        # Use assigned team and role from server
        my_team = self.my_assigned_team.capitalize() if self.my_assigned_team else "Neutral"
        my_role = self.my_assigned_role.capitalize() if self.my_assigned_role else "Spectator"
        
        # Game Info Bar (Top)
        info_bar_height = 100
        info_bar_rect = pygame.Rect(20, 20, WIDTH - 40, info_bar_height)
        pygame.draw.rect(self.screen, PANEL_COLOR, info_bar_rect, border_radius=10)
        
        self._draw_text(f"Room: {self.current_room_id}", FONT_MEDIUM, TEXT_COLOR, info_bar_rect.x + 20, info_bar_rect.y + 15, center=False)
        self._draw_text(f"RED: {self.red_score}", FONT_MEDIUM, RED_CARD, info_bar_rect.x + 250, info_bar_rect.y + 15, center=True)
        self._draw_text(f"BLUE: {self.blue_score}", FONT_MEDIUM, BLUE_CARD, info_bar_rect.x + 450, info_bar_rect.y + 15, center=True)
        
        turn_text_color = RED_CARD if self.current_turn == "red" else BLUE_CARD
        self._draw_text(f"Turn: {self.current_turn.upper()}", FONT_LARGE, turn_text_color, info_bar_rect.x + 650, info_bar_rect.y + 15, center=False)

        # Display player's team and role
        player_role_text = f"You are: {my_team} {my_role}"
        player_role_color = RED_CARD if my_team.lower() == "red" else (BLUE_CARD if my_team.lower() == "blue" else TEXT_COLOR)
        self._draw_text(player_role_text, FONT_MEDIUM, player_role_color, info_bar_rect.x + 20, info_bar_rect.y + 55, center=False)

        clue_display_y_in_bar = info_bar_rect.y + 55
        # Adjust clue display position if player role text is present
        if my_team != "Neutral": # If player has a team/role, shift clue display
             clue_display_y_in_bar = info_bar_rect.y + 55
             # Adjust x-position to avoid overlap, or use a different layout
             # For now, let's keep it centered but be aware of potential overlap on smaller screens
        
        if self.clue_word:
            self._draw_text(f"Clue: '{self.clue_word}' - Guesses: {self.guesses_made}", 
                      FONT_MEDIUM, TEXT_COLOR, info_bar_rect.centerx, clue_display_y_in_bar, center=True)
        else:
            self._draw_text("Waiting for Spymaster's clue...", FONT_MEDIUM, TEXT_COLOR, info_bar_rect.centerx, clue_display_y_in_bar, center=True)

        # Game Board
        card_width = 170
        card_height = 65
        card_margin = 10
        start_x = (WIDTH - (5 * card_width + 4 * card_margin)) // 2
        start_y = info_bar_rect.bottom + 20

        card_rects = []
        for i, card in enumerate(self.game_board):
            row = i // 5
            col = i % 5
            x = start_x + col * (card_width + card_margin)
            y = start_y + row * (card_height + card_margin)
            
            card_rect = pygame.Rect(x, y, card_width, card_height)
            card_rects.append((card_rect, card["word"]))

            card_color = (100, 100, 100) # Default unrevealed color
            text_color = TEXT_COLOR

            if card.get("revealed"):
                if card.get("color") == "red": card_color = RED_CARD
                elif card.get("color") == "blue": card_color = BLUE_CARD
                elif card.get("color") == "innocent": card_color = INNOCENT_CARD
                elif card.get("color") == "assassin": card_color = ASSASSIN_CARD
                text_color = REVEALED_TEXT_COLOR
            elif self.is_spymaster and card.get("color"):
                if card.get("color") == "red": card_color = RED_CARD
                elif card.get("color") == "blue": card_color = BLUE_CARD
                elif card.get("color") == "innocent": card_color = INNOCENT_CARD
                elif card.get("color") == "assassin": card_color = ASSASSIN_CARD
            
            pygame.draw.rect(self.screen, card_color, card_rect, border_radius=8)
            pygame.draw.rect(self.screen, CARD_BORDER_COLOR, card_rect, 2, border_radius=8)
            self._draw_text(card["word"], FONT_MEDIUM, text_color, card_rect.centerx, card_rect.centery, center=True)
        
        # Action Panel at the bottom
        action_bar_rect = pygame.Rect(20, HEIGHT - 110, WIDTH - 40, 80)
        pygame.draw.rect(self.screen, PANEL_COLOR, action_bar_rect, border_radius=10)

        # Determine current player's role and turn status
        is_current_spymaster_for_turn = (self.my_assigned_role == "spymaster" and self.my_assigned_team == self.current_turn)
        is_current_operative_for_turn = (self.my_assigned_role == "operative" and self.my_assigned_team == self.current_turn)
        
        is_current_operative_for_turn_forBTNState = (self.my_assigned_team == self.current_turn)

        # print(f"[CLIENT_DEBUG] In draw_game: Client Fileno={self.client_fileno}, Current Turn={self.current_turn}")
        # print(f"[CLIENT_DEBUG] My Assigned Team={self.my_assigned_team}, My Assigned Role={self.my_assigned_role}")
        # print(f"[CLIENT_DEBUG] Is Current Spymaster for turn: {is_current_spymaster_for_turn}")
        # print(f"[CLIENT_DEBUG] Is Current Operative for turn: {is_current_operative_for_turn}")



        # print(f"self.blue_score={self.blue_score}, self.red_score={self.red_score}")

        # Enable/Disable controls based on role and turn
        can_give_clue = is_current_spymaster_for_turn and not self.clue_word and not self.game_over
        can_guess_or_end_turn = is_current_operative_for_turn and self.clue_word and not self.game_over

        self.clue_word_input.set_enabled(can_give_clue)
        self.send_clue_button.set_enabled(can_give_clue)
        self.end_turn_button.set_enabled(True)

        # Draw clue input elements
        self.clue_word_input.rect.topleft = (action_bar_rect.x + 10, action_bar_rect.y + 10)
        self.clue_word_input.draw(self.screen)
        ui_elements.append(self.clue_word_input)
        
        self.send_clue_button.rect.topleft = (self.clue_word_input.rect.right + 10, action_bar_rect.y + 10)
        self.send_clue_button.draw(self.screen, mouse_pos)
        ui_elements.append(self.send_clue_button)
        
        # Draw end turn button
        self.end_turn_button.rect.topleft = (action_bar_rect.right - self.end_turn_button.rect.width - 10, action_bar_rect.y + 10)
        self.end_turn_button.draw(self.screen, mouse_pos)
        ui_elements.append(self.end_turn_button)

        # Display instructions/status for current player
        if self.game_over:
            winner_color = RED_CARD if self.winner == "red" else BLUE_CARD
            winner_text = f"{self.winner.upper()} TEAM WINS!" if self.winner else "GAME OVER!"
            self._draw_text(winner_text, GAME_OVER_FONT, winner_color, WIDTH // 2, HEIGHT // 2 - 100, center=True)
            
            back_to_lobby_button = Button(WIDTH // 2 - 100, HEIGHT // 2 - 30, 200, 50, "Back to Lobby", self._send_leave_room, font=FONT_MEDIUM)
            back_to_lobby_button.draw(self.screen, mouse_pos)
            ui_elements.append(back_to_lobby_button)
        elif is_current_spymaster_for_turn and not self.clue_word:
            self._draw_text("It's your turn to give a clue!", FONT_MEDIUM, HIGHLIGHT_COLOR, action_bar_rect.centerx, action_bar_rect.y + 30, center=True)
            self.end_turn_button.text  = "End Turn"



        elif is_current_operative_for_turn and self.clue_word:
            self._draw_text(f"Click a word to guess (Guesses left: {self.clue_number + 1 - self.guesses_made})", 
                           FONT_MEDIUM, HIGHLIGHT_COLOR, action_bar_rect.centerx, action_bar_rect.y + 50, center=True)
            # Add click handling for game board cards for operatives if it's their turn
            for rect, word in card_rects:
                if rect.collidepoint(mouse_pos) and pygame.mouse.get_pressed()[0] and \
                   not next((c for c in self.game_board if c["word"] == word), {}).get('revealed', False):
                    # self._send_guess(word)
                    break
        else:
            self._draw_text("Waiting for opponent's turn...", FONT_MEDIUM, TEXT_COLOR, action_bar_rect.centerx, action_bar_rect.y + 30, center=True)

            if(is_current_operative_for_turn_forBTNState):
                self.end_turn_button.text  = "End Turn"
            else:
                self.end_turn_button.text  = "Leave the Room"

        return ui_elements

    def run(self):
        """Main client application loop."""
        ui_elements = []

        while self.running:
            mouse_pos = pygame.mouse.get_pos()
            
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                
                for element in ui_elements:
                    element.handle_event(event)

            self.screen.fill(BG_COLOR)

            if not self.connected:
                self._draw_text("Connect to Server", FONT_LARGE, TEXT_COLOR, WIDTH // 2, HEIGHT // 2 - 80, center=True)
                self.name_input.draw(self.screen)
                self.connect_button.draw(self.screen, mouse_pos)
                ui_elements = [self.name_input, self.connect_button]
            elif not self.logged_in:
                self._draw_text("Logging in...", FONT_LARGE, TEXT_COLOR, WIDTH // 2, HEIGHT // 2, center=True)
                ui_elements = []
            else:
                if self.current_room_id is None:
                    ui_elements = self._draw_lobby(mouse_pos)
                elif self.game_active:
                    ui_elements = self._draw_game(mouse_pos)
                else:
                    ui_elements = self._draw_room_lobby(mouse_pos)

            pygame.display.flip()
            self.clock.tick(FPS)

        if self.client:
            self.client.close()
        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    client = CodenamesClient()
    client.run()
