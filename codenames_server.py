import socket
import threading
import json
import time
import random
import traceback
import select # Import the select module

# --- Constants ---
HOST = '127.0.0.1'
PORT = 5555
HEADER_LENGTH = 10 # For fixed-size message length header

# --- Game Logic (Simplified Codenames Board) ---
# A basic list of words for demonstration. In a full game, this would be much larger.
ALL_WORDS = [
    "APPLE", "BAKER", "CLOUD", "DREAM", "EAGLE", "FENCE", "GLOVE", "HOUSE", "INDIA", "JUMBO",
    "KNIFE", "LAUNCH", "MISSION", "NEPTUNE", "ORBIT", "PULSE", "QUEEN", "ROBOT", "SATELLITE",
    "TIGER", "UMBRELLA", "VENUS", "VOYAGER", "ZORRO", "ZEBRA", "SPIDER", "MERCURY", "DESK",
    "DOG", "CAT", "STRAW", "GRAPE", "CAR", "PLANE", "DRIVE", "BIRD", "FISH", "CRANE", "BLOCK",
    "BOARD", "GAME", "PLAY", "RUN", "JUMP", "DANCE", "SING", "ART", "BOOK", "READ"
]

class Player:
    """Represents a player connected to the server."""
    def __init__(self, fileno, name):
        self.fileno = fileno
        self.name = name
        self.room_id = None
        self.team = None # "red", "blue", or None (for lobby/spectator) - actual assigned team
        self.role = None # "spymaster", "operative", or None
        self.chosen_team = None # "red", "blue", or None - player's preferred team

    def to_dict(self):
        return {"fileno": self.fileno, "name": self.name, "team": self.team, "role": self.role, "chosen_team": self.chosen_team}

class GameRoom:
    def __init__(self, room_id, owner_fileno, server_instance, room_name="Unnamed Room"):
        self.room_id = room_id
        self.owner_fileno = owner_fileno # The client who created the room
        self.name = room_name # Store the room name
        self.clients = {}  # {client_fileno: client_name} - for quick lookup of names in room
        self.game_in_progress = False
        self.server = server_instance # Reference to the server instance to access connected_clients

        # Game state specific variables
        self.board = [] # List of {"word": str, "color": str, "revealed": bool}
        self.red_score = 0
        self.blue_score = 0
        self.turn = "" # "red" or "blue"
        self.clue_word = ""
        self.clue_number = 0
        self.guesses_made = 0
        self.game_over = False
        self.winner = None

        # Role assignments (client filenos)
        self.red_spymaster_fileno = None
        self.blue_spymaster_fileno = None
        self.red_operatives_filenos = []
        self.blue_operatives_filenos = []

        self.chat_messages = [] # Room-specific chat
        self.lock = threading.RLock() # Re-entrant lock for thread safety

    def add_client(self, client_fileno, client_name):
        with self.lock:
            if client_fileno not in self.clients:
                self.clients[client_fileno] = client_name
                # Update the Player object's room_id
                player_obj = self.server.connected_clients.get(client_fileno)
                if player_obj:
                    player_obj.room_id = self.room_id
                    player_obj.team = None # Reset assigned team when joining room
                    player_obj.role = None # Reset assigned role when joining room
                    player_obj.chosen_team = None # Reset chosen team when joining room
                self.add_chat_message(f"{client_name} joined the room.")
                print(f"Client {client_name} ({client_fileno}) joined room {self.room_id}.")
                return True
            return False

    def remove_client(self, client_fileno):
        with self.lock:
            if client_fileno in self.clients:
                client_name = self.clients.pop(client_fileno)
                # Reset the Player object's room_id, team, and role
                player_obj = self.server.connected_clients.get(client_fileno)
                if player_obj:
                    player_obj.room_id = None
                    player_obj.team = None
                    player_obj.role = None
                    player_obj.chosen_team = None # Reset chosen team when leaving room

                self.add_chat_message(f"{client_name} left the room.")
                print(f"Client {client_name} ({client_fileno}) left room {self.room_id}.")
                
                # If game was in progress and a spymaster left, end game (simplistic)
                if self.game_in_progress:
                    if client_fileno == self.red_spymaster_fileno or \
                       client_fileno == self.blue_spymaster_fileno:
                        self.game_over = True
                        self.winner = "draw" # Or assign winner to remaining team
                        self.add_chat_message("A spymaster left. Game ended prematurely.", is_system=True)
                        print(f"Room {self.room_id}: Game ended due to spymaster leaving.")
                
                # If no more players, the room might be dissolved by the server logic
                return True
            return False

    def add_chat_message(self, message, is_system=False):
        with self.lock:
            prefix = "[SYSTEM] " if is_system else ""
            self.chat_messages.append(f"{prefix}{message}")
            # Keep chat history to a reasonable length
            if len(self.chat_messages) > 50:
                self.chat_messages = self.chat_messages[-50:]

    def get_room_info(self):
        with self.lock:
            room_info = {
                "id": self.room_id,
                "name": self.name,
                "players": len(self.clients),
                "game_in_progress": self.game_in_progress,
                "owner": self.clients.get(self.owner_fileno, "Unknown"),
                "owner_fileno": self.owner_fileno # Explicitly include owner_fileno
            }
            # print(f"[SERVER_DEBUG] get_room_info for room {self.room_id}: {room_info}") # DEBUG PRINT
            return room_info
            
    def _generate_random_board(self):
        """Generates a new Codenames board with assigned colors."""
        available_words = random.sample(ALL_WORDS, 25) # Pick 25 unique words
        
        # Standard Codenames distribution (assuming Red starts)
        # 8 Red, 8 Blue, 7 Innocent, 2 Assassin
        colors_distribution = ["red"] * 8 + ["blue"] * 8 + ["innocent"] * 7 + ["assassin"] * 2
        random.shuffle(colors_distribution)

        board = []
        current_red_score = 0
        current_blue_score = 0

        for i in range(25):
            word = available_words[i]
            color = colors_distribution[i]
            board.append({
                "word": word,
                "color": color,
                "revealed": False
            })
            if color == "red":
                current_red_score += 1
            elif color == "blue":
                current_blue_score += 1
        
        self.red_score = current_red_score # Should be 9
        self.blue_score = current_blue_score # Should be 8
        return board

    def start_game(self):
        with self.lock:
            if len(self.clients) < 2:
                return False, "Not enough players to start game (minimum 2 required)."
            if self.game_in_progress:
                return False, "Game is already in progress."

            self.game_in_progress = True
            self.board = self._generate_random_board()
            self.turn = random.choice(["red", "blue"]) # Randomly decide who starts
            self.clue_word = ""
            self.clue_number = 0
            self.guesses_made = 0
            self.game_over = False
            self.winner = None

            self._assign_teams_and_roles() # Call the new assignment method
            
            self.add_chat_message("A new game has started!", is_system=True)
            self.add_chat_message(f"Red Spymaster: {self.server.connected_clients[self.red_spymaster_fileno].name if self.red_spymaster_fileno else 'None'}", is_system=True)
            self.add_chat_message(f"Blue Spymaster: {self.server.connected_clients[self.blue_spymaster_fileno].name if self.blue_spymaster_fileno else 'None'}", is_system=True)
            print(f"Room {self.room_id}: Game started. Roles assigned.")
            return True, "Game started!"

    def _assign_teams_and_roles(self):
        """Assigns players to opposing teams, respecting player choice if available."""
        current_room_clients = list(self.clients.keys())
        random.shuffle(current_room_clients)  # Shuffle for randomness

        # Reset all roles and teams for a clean assignment
        for fileno in current_room_clients:
            player_obj = self.server.connected_clients.get(fileno)
            if player_obj:
                player_obj.team = None
                player_obj.role = None
        
        # Clear previous assignments
        self.red_spymaster_fileno = None
        self.blue_spymaster_fileno = None
        self.red_operatives_filenos = []
        self.blue_operatives_filenos = []

        # Separate players based on their chosen team
        chosen_red_players = []
        chosen_blue_players = []
        no_choice_players = []

        for fileno in current_room_clients:
            player_obj = self.server.connected_clients.get(fileno)
            if player_obj:
                if player_obj.chosen_team == "red":
                    chosen_red_players.append(fileno)
                elif player_obj.chosen_team == "blue":
                    chosen_blue_players.append(fileno)
                else:
                    no_choice_players.append(fileno)
        
        # Randomly distribute players with no choice to balance teams
        random.shuffle(no_choice_players)
        
        temp_red_players = list(chosen_red_players)
        temp_blue_players = list(chosen_blue_players)

        for fileno in no_choice_players:
            # Distribute remaining players to try and balance teams
            if len(temp_red_players) <= len(temp_blue_players):
                temp_red_players.append(fileno)
            else:
                temp_blue_players.append(fileno)

        # Ensure both teams have at least one player for competitive play, even if choices are uneven
        # This might override a player's initial choice if necessary for game viability.
        if not temp_red_players and temp_blue_players:
            # Move one player from blue to red if red is empty
            temp_red_players.append(temp_blue_players.pop(0))
            print(f"[DEBUG_ASSIGN] Moved a player from Blue to Red to ensure Red team is not empty.")
        if not temp_blue_players and temp_red_players:
            # Move one player from red to blue if blue is empty
            temp_blue_players.append(temp_red_players.pop(0))
            print(f"[DEBUG_ASSIGN] Moved a player from Red to Blue to ensure Blue team is not empty.")

        # Update player objects with their assigned teams
        for fileno in temp_red_players:
            player_obj = self.server.connected_clients.get(fileno)
            if player_obj:
                player_obj.team = "red"
                print(f"[DEBUG_ASSIGN] Player {player_obj.name} (fileno {fileno}) assigned to Red team.")
        for fileno in temp_blue_players:
            player_obj = self.server.connected_clients.get(fileno)
            if player_obj:
                player_obj.team = "blue"
                print(f"[DEBUG_ASSIGN] Player {player_obj.name} (fileno {fileno}) assigned to Blue team.")

        # Assign spymasters: pick one from each team
        if temp_red_players:
            self.red_spymaster_fileno = random.choice(temp_red_players)
            player_obj = self.server.connected_clients.get(self.red_spymaster_fileno)
            if player_obj:
                player_obj.role = "spymaster"
                print(f"[DEBUG_ASSIGN] {player_obj.name} (fileno {self.red_spymaster_fileno}) assigned as Red Spymaster.")
        if temp_blue_players:
            self.blue_spymaster_fileno = random.choice(temp_blue_players)
            player_obj = self.server.connected_clients.get(self.blue_spymaster_fileno)
            if player_obj:
                player_obj.role = "spymaster"
                print(f"[DEBUG_ASSIGN] {player_obj.name} (fileno {self.blue_spymaster_fileno}) assigned as Blue Spymaster.")

        # Assign remaining players as operatives
        for fileno in temp_red_players:
            if fileno != self.red_spymaster_fileno:
                self.red_operatives_filenos.append(fileno)
                player_obj = self.server.connected_clients.get(fileno)
                if player_obj:
                    player_obj.role = "operative"
                    print(f"[DEBUG_ASSIGN] {player_obj.name} (fileno {fileno}) assigned as Red Operative.")
        
        for fileno in temp_blue_players:
            if fileno != self.blue_spymaster_fileno:
                self.blue_operatives_filenos.append(fileno)
                player_obj = self.server.connected_clients.get(fileno)
                if player_obj:
                    player_obj.role = "operative"
                    print(f"[DEBUG_ASSIGN] {player_obj.name} (fileno {fileno}) assigned as Blue Operative.")

        # Crucial: If a spymaster is the only player on their team, they also act as an operative.
        # This handles 2-player competitive mode where each player is both spymaster and operative.
        # Ensure spymaster is always in their operative list for the client to correctly identify as operative
        if self.red_spymaster_fileno and self.red_spymaster_fileno not in self.red_operatives_filenos:
            self.red_operatives_filenos.append(self.red_spymaster_fileno)
            player_obj = self.server.connected_clients.get(self.red_spymaster_fileno)
            if player_obj and player_obj.role != "spymaster": # Only if not already spymaster
                player_obj.role = "operative" # This line might be redundant if spymaster is primary role
        
        if self.blue_spymaster_fileno and self.blue_spymaster_fileno not in self.blue_operatives_filenos:
            self.blue_operatives_filenos.append(self.blue_spymaster_fileno)
            player_obj = self.server.connected_clients.get(self.blue_spymaster_fileno)
            if player_obj and player_obj.role != "spymaster": # Only if not already spymaster
                player_obj.role = "operative" # This line might be redundant if spymaster is primary role


        print(f"Roles assigned for room {self.room_id}:")
        print(f"  Red Spymaster: {self.server.connected_clients[self.red_spymaster_fileno].name if self.red_spymaster_fileno and self.red_spymaster_fileno in self.server.connected_clients else 'None'}")
        print(f"  Red Operatives: {[self.server.connected_clients[f].name for f in self.red_operatives_filenos if f in self.server.connected_clients]}")
        print(f"  Blue Spymaster: {self.server.connected_clients[self.blue_spymaster_fileno].name if self.blue_spymaster_fileno and self.blue_spymaster_fileno in self.server.connected_clients else 'None'}")
        print(f"  Blue Operatives: {[self.server.connected_clients[f].name for f in self.blue_operatives_filenos if f in self.server.connected_clients]}")


    def get_game_state_for_client(self, client_fileno):
        """Prepares the game state dictionary for a specific client."""
        with self.lock:
            board_for_client = []
            
            # Retrieve the player's actual team and role from the Player object
            player_obj = self.server.connected_clients.get(client_fileno)
            
            # Determine if the requesting client is a spymaster based on their assigned role
            is_spymaster_for_this_client = (player_obj and player_obj.role == "spymaster")

            for card in self.board:
                if card["revealed"] or is_spymaster_for_this_client:
                    # Spymasters and revealed cards show full info
                    board_for_client.append(card)
                else:
                    # Operatives only see the word and revealed status
                    board_for_client.append({"word": card["word"], "revealed": card["revealed"]})

            return {
                "type": "game_state_update",
                "board": board_for_client,
                "red_score": self.red_score,
                "blue_score": self.blue_score,
                "turn": self.turn,
                "clue_word": self.clue_word,
                "clue_number": self.clue_number,
                "guesses_made": self.guesses_made,
                "game_over": self.game_over,
                "winner": self.winner,
                "is_spymaster": is_spymaster_for_this_client, # Crucial for client UI
                "spymaster_red": self.red_spymaster_fileno,
                "spymaster_blue": self.blue_spymaster_fileno,
                "operative_red": self.red_operatives_filenos,
                "operative_blue": self.blue_operatives_filenos,
                "my_team": player_obj.team if player_obj else "neutral", # Send client's assigned team
                "my_role": player_obj.role if player_obj else "spectator", # Send client's assigned role
            }

    def process_clue(self, client_fileno, word, number):
        with self.lock:
            if self.game_over: return False, "Game is over."
            if not self.game_in_progress: return False, "Game not in progress."

            # Check if it's the correct Spymaster's turn
            if self.turn == "red" and client_fileno != self.red_spymaster_fileno:
                return False, "It's Red's turn, but you are not the Red Spymaster."
            if self.turn == "blue" and client_fileno != self.blue_spymaster_fileno:
                return False, "It's Blue's turn, but you are not the Blue Spymaster."

            # Check if a clue has already been given for this turn
            if self.clue_word:
                return False, "A clue has already been given this turn."
            
            # Basic validation
            if not word or not isinstance(word, str) or not (isinstance(number, int) and 0 <= number <= 9):
                return False, "Invalid clue word or number."

            self.clue_word = word.upper()
            self.clue_number = number
            self.guesses_made = 0 # Reset guesses for the new clue
            self.add_chat_message(f"{self.clients.get(client_fileno, 'Unknown')} gave clue: '{self.clue_word}'")
            print(f"Room {self.room_id}: Clue '{word}' ({number}) given by {self.clients.get(client_fileno, 'Unknown')}.")



            for card in self.board:
                print(f"cycle word:{card["word"].lower()}")

            
            # self.add_chat_message(f"{self.clients.get(client_fileno, 'Unknown')} process clue: '{self.clue_word}' ({self.clue_number})")
            # room = self.rooms.get(current_room_id)
            # room.process_guess(self, self.clients.get(client_fileno, 'Unknown'), self.clue_word)



            return True, "Clue received."
    def process_guess(self, client_fileno, guessed_word):
        print(f"--- Entering process_guess for client {client_fileno}, guessed_word: '{guessed_word}' ---")

        with self.lock:
            print(f"Acquired lock for processing guess.")
            if self.game_over:
                print(f"Game is over. Returning False.")
                return False, "Game is over."
            if not self.game_in_progress:
                print(f"Game not in progress. Returning False.")
                return False, "Game not in progress."

            # Check if a clue has been given yet
            if not self.clue_word:
                print(f"No clue has been given yet. Returning False.")
                return False, "No clue has been given yet."
            print(f"Current clue word: '{self.clue_word}', clue number: {self.clue_number}")

            # Check if it's the correct Operative's turn
            is_operative_of_current_team = False
            if self.turn == "red" and client_fileno in self.red_operatives_filenos:
                is_operative_of_current_team = True
                print(f"Client {client_fileno} is a red operative and it's red's turn.")
            elif self.turn == "blue" and client_fileno in self.blue_operatives_filenos:
                is_operative_of_current_team = True
                print(f"Client {client_fileno} is a blue operative and it's blue's turn.")
            
            if not is_operative_of_current_team:
                print(f"Client {client_fileno} is not an operative for the current turn ({self.turn}). Returning False.")
                return False, "It's not your team's turn or you are not an operative for the current turn."

            # Check if guess limit reached (clue_number + 1 bonus guess)
            print(f"Guesses made: {self.guesses_made}, Allowed guesses: {self.clue_number + 1}")
            if self.guesses_made >= (self.clue_number + 1):
                print(f"Guess limit reached. Returning False.")
                # If they try to guess beyond their allowed guesses, it's an invalid move
                # and doesn't end the turn, but tells them they can't.
                return False, "You have used all your guesses for this clue. Please end your turn."

            found_card = None
            print(f"Searching for '{guessed_word}' on the board.")
            for card in self.board:
                if card["word"].lower() == guessed_word.lower():
                    found_card = card
                    print(f"Found card: {found_card['word']} with color {found_card['color']}.")
                    break

            if not found_card:
                self.guesses_made += 1 # A guess on a non-existent word still counts towards total guesses
                self.add_chat_message(f"{self.clients.get(client_fileno, 'Unknown')} guessed '{guessed_word}' (not on board).")
                print(f"Room {self.room_id}: {self.clients.get(client_fileno, 'Unknown')} guessed '{guessed_word}' (not on board). Guesses made: {self.guesses_made}.")
                # If they guess a word not on the board, the turn usually ends immediately.
                print(f"Word not found on board. Ending turn.")
                self._end_turn()    
                return False, "Word not found on the board. Your turn ends."


            alreadyRevealedCart = False
            if found_card["revealed"]:
                print(f"Card '{found_card['word']}' already revealed. Returning False.")
                alreadyRevealedCart = True
                result_message = ""
                turn_ends = False
                # return False, "That word has already been revealed."

            if not alreadyRevealedCart:
                found_card["revealed"] = True
                self.guesses_made += 1
                print(f"Card '{found_card['word']}' revealed. Guesses made: {self.guesses_made}.")

                result_message = ""
                turn_ends = False

                print(f"Guessed card color: {found_card['color']}, Current turn: {self.turn}")
                if found_card["color"] == self.turn:
                    # Correct team's word
                    if self.turn == "red":
                        self.red_score -= 1
                        print(f"Red team guessed own word. Red score: {self.red_score}")
                    else: # blue
                        self.blue_score -= 1
                        print(f"Blue team guessed own word. Blue score: {self.blue_score}")
                    result_message = f"{self.clients.get(client_fileno, 'Unknown')} guessed their own word: {found_card['word']}."
                    self.add_chat_message(result_message)
                elif found_card["color"] == "innocent":
                    # Innocent bystander
                    result_message = f"{self.clients.get(client_fileno, 'Unknown')} guessed an Innocent bystander: {found_card['word']}. Turn ends!"
                    self.add_chat_message(result_message)
                    turn_ends = True
                    print(f"Innocent bystander guessed. Turn ends: {turn_ends}.")
                elif found_card["color"] == "assassin":
                    # Assassin
                    result_message = f"{self.clients.get(client_fileno, 'Unknown')} guessed the Assassin word: {found_card['word']}! Game Over!"
                    self.add_chat_message(result_message)
                    self.game_over = True
                    self.winner = "blue" if self.turn == "red" else "red" # Assassin causes immediate loss for guessing team
                    turn_ends = True # Game over, so turn ends
                    print(f"Assassin guessed! Game Over: {self.game_over}, Winner: {self.winner}. Turn ends: {turn_ends}.")
                else:
                    # Opponent's word
                    if self.turn == "red": # Red guessed blue's word
                        self.blue_score -= 1
                        print(f"Red guessed opponent's word. Blue score: {self.blue_score}")
                    else: # Blue guessed red's word
                        self.red_score -= 1
                        print(f"Blue guessed opponent's word. Red score: {self.red_score}")
                    result_message = f"{self.clients.get(client_fileno, 'Unknown')} guessed opponent's word: {found_card['word']}. Turn ends!"
                    self.add_chat_message(result_message)
                    turn_ends = True
                    print(f"Opponent's word guessed. Turn ends: {turn_ends}.")
                
                print(f"Room {self.room_id}: {result_message}")

                # Check for win conditions
                print(f"Checking win conditions. Red score: {self.red_score}, Blue score: {self.blue_score}.")
                if self.red_score == 0:
                    self.game_over = True
                    self.winner = "red"
                    self.add_chat_message("RED TEAM WINS!", is_system=True)
                    print(f"Room {self.room_id}: RED TEAM WINS! Game Over: {self.game_over}, Winner: {self.winner}.")
                elif self.blue_score == 0:
                    self.game_over = True
                    self.winner = "blue"
                    self.add_chat_message("BLUE TEAM WINS!", is_system=True)
                    print(f"Room {self.room_id}: BLUE TEAM WINS! Game Over: {self.game_over}, Winner: {self.winner}.")
                
                # End turn if criteria met
                print(f"Evaluating turn end conditions: turn_ends={turn_ends}, game_over={self.game_over}, guesses_made={self.guesses_made}, clue_number={self.clue_number}.")
                if turn_ends or self.game_over or self.guesses_made > self.clue_number:
                    print(f"Calling _end_turn().")
                    self._end_turn()
                else:
                    print(f"Turn continues.")

            print(f"--- Exiting process_guess. Result: True, Message: '{result_message}' ---")
            return True, result_message

    def _end_turn(self):
        with self.lock:
            if self.game_over: return
            print(f"Room {self.room_id}: {self.turn.upper()}'s turn ends.")
            self.add_chat_message(f"{self.turn.upper()}'s turn has ended.", is_system=True)
            
            # Clear clue for next turn
            self.clue_word = ""
            self.clue_number = 0
            self.guesses_made = 0
            # Switch turn
            self.turn = "blue" if self.turn == "red" else "red"

    def process_end_turn(self, client_fileno):
        with self.lock:
            if self.game_over: return False, "Game is already over."
            if not self.game_in_progress: return False, "Game not in progress."

            is_operative_of_current_team = False
            if self.turn == "red" and client_fileno in self.red_operatives_filenos:
                is_operative_of_current_team = True
            elif self.turn == "blue" and client_fileno in self.blue_operatives_filenos:
                is_operative_of_current_team = True

            if not is_operative_of_current_team:
                return False, "It's not your team's turn or you are not an operative for the current turn."
            
            if not self.clue_word: # Can't end turn if no clue was given yet
                return False, "No clue has been given yet."

            self._end_turn()
            self.add_chat_message(f"{self.clients.get(client_fileno, 'Unknown')} explicitly ended turn.")
            print(f"Room {self.room_id}: {self.clients.get(client_fileno, 'Unknown')} explicitly ended turn.")
            return True, "Turn ended."


# --- Server Class ---
class CodenamesServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(5)
        print(f"Server listening on {self.host}:{self.port}")

        self.clients = {}  # client_socket: {"name": str, "room_id": str or None}
        self.connected_clients = {} # {fileno: Player_object} - This is the canonical list of Player objects
        self.rooms = {}    # {room_id: GameRoom_obj}
        self.lobby_chat = [] # Global lobby chat
        self.running = True
        self.lock = threading.RLock() # Global lock for server state

    def start(self):
        threading.Thread(target=self._accept_connections, daemon=True).start()
        threading.Thread(target=self._update_clients_periodically, daemon=True).start()

        try:
            while self.running:
                time.sleep(1) # Keep main thread alive
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
                conn.setblocking(False) # Non-blocking for reading
                client_fileno = conn.fileno()
                print(f"Accepted connection from {addr} (fileno: {client_fileno})")
                
                with self.lock:
                    # Create a dummy Player object initially, name will be set by 'join' message
                    self.connected_clients[client_fileno] = Player(client_fileno, f"Guest_{client_fileno}")
                    self.clients[client_fileno] = {"socket": conn, "player_obj": self.connected_clients[client_fileno]}
                
                threading.Thread(target=self._handle_client, args=(client_fileno,), daemon=True).start()
            except socket.timeout:
                pass
            except Exception as e:
                if self.running:
                    print(f"Error accepting connection: {e}")
                break # Exit loop if server is shutting down

    def _handle_client(self, client_fileno):
        with self.lock: # Acquire lock before accessing self.clients
            client_info = self.clients.get(client_fileno)
            if not client_info: # Client might have been cleaned up already
                return
            client_sock = client_info["socket"]

        try:
            while self.running:
                # Use select to wait for data to be available for reading
                # Timeout of 0.1 seconds to allow the loop to check self.running regularly
                readable, _, _ = select.select([client_sock], [], [], 0.1)
                if client_sock in readable:
                    # Read header first
                    header = client_sock.recv(HEADER_LENGTH)
                    if not header: # Client disconnected
                        print(f"Client {client_fileno} disconnected.")
                        break
                    
                    msg_len = int(header.decode('utf-8').strip())
                    
                    # Read the full message body
                    full_message_bytes = b''
                    while len(full_message_bytes) < msg_len:
                        chunk = client_sock.recv(msg_len - len(full_message_bytes))
                        if not chunk: # Client disconnected during body read
                            print(f"Client {client_fileno} disconnected during message body read.")
                            break
                        full_message_bytes += chunk
                    
                    if len(full_message_bytes) < msg_len: # Incomplete message
                        break # Disconnect client or handle as error
                    
                    message = json.loads(full_message_bytes.decode('utf-8'))
                    self._process_message(client_fileno, message)
                # If not readable, loop continues and checks self.running
        except ConnectionResetError:
            print(f"Client {client_fileno} connection reset by peer.")
        except ValueError: # For int(header.decode())
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
            if not player_obj: return # Client might have disconnected or not fully joined

            client_name = player_obj.name
            current_room_id = player_obj.room_id

            if mtype == "join":
                new_name = message.get("name", f"Guest_{client_fileno}")
                # Check if username already exists among currently connected clients
                if any(p.name == new_name for f, p in self.connected_clients.items() if f != client_fileno):
                    self._send_to_client(client_fileno, {"type": "error", "message": f"Username '{new_name}' is already taken. Please choose another."})
                    return # Do not set name if taken

                player_obj.name = new_name # Update the Player object's name
                self._add_lobby_chat_message(f"{new_name} joined the lobby.", is_system=True)
                print(f"{client_name} (fileno {client_fileno}) changed name to {new_name}.")
                self._broadcast_lobby_update() # Immediate update on join

            elif mtype == "chat":
                text = message.get("text", "")
                if text:
                    if current_room_id:
                        room = self.rooms.get(current_room_id)
                        if room: room.add_chat_message(f"{client_name}: {text}")
                    else:
                        self._add_lobby_chat_message(f"{client_name}: {text}")

            elif mtype == "create_room":
                room_name = message.get("name", f"Room_{random.randint(1000, 9999)}")
                new_room_id = f"room_{len(self.rooms) + 1}" # Simple ID generation
                
                if current_room_id: # If client is already in a room, they must leave first
                    self._send_to_client(client_fileno, {"type": "error", "message": "Please leave current room first."})
                    return

                new_room = GameRoom(new_room_id, client_fileno, self, room_name) # Pass server instance and room_name
                self.rooms[new_room_id] = new_room
                new_room.add_client(client_fileno, client_name) # This also updates player_obj.room_id
                self._add_lobby_chat_message(f"{client_name} created room '{room_name}'.", is_system=True)
                print(f"{client_name} created room {new_room_id}.")
                # Send room_created message with owner_fileno
                self._send_to_client(client_fileno, {"type": "room_created", "room_id": new_room_id, "name": room_name, "owner_fileno": client_fileno})
                self._broadcast_lobby_update() # Immediate update after room creation

            elif mtype == "join_room":
                target_room_id = message.get("room_id")
                room = self.rooms.get(target_room_id)
                if not room:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Room not found."})
                    return
                if room.game_in_progress:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Cannot join: Game in progress."})
                    return
                if current_room_id: # If client is already in a room, they must leave first
                    self._send_to_client(client_fileno, {"type": "error", "message": "Please leave current room first."})
                    return
                
                room.add_client(client_fileno, client_name) # This also updates player_obj.room_id
                self._add_lobby_chat_message(f"{client_name} joined room '{target_room_id}'.", is_system=True)
                print(f"{client_name} joined room {target_room_id}.")
                # Send room_joined message with owner_fileno
                self._send_to_client(client_fileno, {"type": "room_joined", "room_id": target_room_id, "owner_fileno": room.owner_fileno})
                self._broadcast_lobby_update() # Immediate update after joining a room

            elif mtype == "leave_room":
                if current_room_id:
                    room = self.rooms.get(current_room_id)
                    if room:
                        room.remove_client(client_fileno) # This also resets player_obj.room_id, team, role
                        if not room.clients: # If room is empty, delete it
                            del self.rooms[current_room_id]
                            print(f"Room {current_room_id} deleted as it is empty.")
                        self._add_lobby_chat_message(f"{client_name} left room '{current_room_id}'.", is_system=True)
                    # client_info["room_id"] is already None via room.remove_client
                    print(f"{client_name} left room {current_room_id}.")
                    self._send_to_client(client_fileno, {"type": "room_left"})
                    self._broadcast_lobby_update() # Immediate update after leaving a room
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Not in a room to leave."})

            elif mtype == "set_team":
                team_choice = message.get("team")
                if team_choice in ["red", "blue"] and player_obj.room_id:
                    player_obj.chosen_team = team_choice
                    print(f"Player {player_obj.name} (fileno {client_fileno}) chose team: {team_choice}")
                    # Optionally, send an acknowledgement back to the client
                    self._send_to_client(client_fileno, {"type": "team_set_ack", "team": team_choice})
                    self._broadcast_lobby_update() # Update lobby to show chosen teams if desired
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Invalid team choice or not in a room."})

            elif mtype == "start_game_request":
                if current_room_id:
                    room = self.rooms.get(current_room_id)
                    if room and client_fileno == room.owner_fileno: # Only room owner can start
                        success, msg = room.start_game()
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
                            # Game started, state updates will be sent periodically
                            self._send_to_client(client_fileno, {"type": "game_start_ack", "message": msg})
                            self._broadcast_lobby_update() # Update lobby to show game in progress
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

            elif mtype == "chat":
                text = message.get("text", "")
                if text:
                    room.add_chat_message(player_obj.name, text)
                    self._broadcast_room_chat_update(room.id)
                     
            elif mtype == "guess":
                word = message.get("word")
                if current_room_id:
                    room = self.rooms.get(current_room_id)
                    if room and room.game_in_progress:
                        # success, msg = room.process_guess(client_fileno, word)
                        self._send_to_client(client_fileno, {"type": "info", "message": msg})
                        if success:
                            self._broadcast_game_state_to_room(current_room_id)
                    else:
                        self._send_to_client(client_fileno, {"type": "error", "message": "No game in progress in this room."})
                else:
                    self._send_to_client(client_fileno, {"type": "error", "message": "Not in a room."})
                if success:
                    self._broadcast_game_state_to_room(current_room_id)
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
                # Client explicitly requested a lobby refresh
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
                    # Prepend header with message length
                    header = f"{len(data):<{HEADER_LENGTH}}".encode('utf-8')
                    client_info["socket"].sendall(header + data)
                except Exception as e:
                    print(f"Error sending to client {client_fileno}: {e}")
                    self._cleanup_client(client_fileno)

    def _broadcast_to_lobby(self, message):
        with self.lock:
            for fileno, client_info in self.clients.items():
                # Use the player_obj's room_id to determine if they are in the lobby
                if client_info["player_obj"].room_id is None: 
                    self._send_to_client(fileno, message)

    def _broadcast_to_room(self, room_id, message):
        with self.lock:
            room = self.rooms.get(room_id)
            if room:
                for fileno in room.clients.keys():
                    self._send_to_client(fileno, message)

    def _broadcast_lobby_update(self):
        """Helper method to create and broadcast the latest lobby state."""
        with self.lock:
            lobby_update_message = {
                "type": "lobby_update",
                "players": [p.name for p in self.connected_clients.values() if p.room_id is None],
                "rooms": [room.get_room_info() for room in self.rooms.values()],
                "chat": self.lobby_chat # Send full lobby chat for now
            }
            self._broadcast_to_lobby(lobby_update_message)

    def _update_clients_periodically(self):
        while self.running:
            # The periodic update now just calls the helper method
            self._broadcast_lobby_update()

            # Update clients in active game rooms (this remains the same)
            with self.lock:
                for room_id, room in list(self.rooms.items()): # Use list to iterate to allow modification
                    if room.game_in_progress:
                        for client_fileno in list(room.clients.keys()): # Iterate copy in case client disconnects
                            game_state_message = room.get_game_state_for_client(client_fileno)
                            self._send_to_client(client_fileno, game_state_message)
            time.sleep(0.1) # Update every 100ms (adjust as needed)

    def _cleanup_client(self, client_fileno):
        with self.lock:
            if client_fileno in self.clients:
                client_info = self.clients.pop(client_fileno)
                player_obj = client_info["player_obj"]
                client_name = player_obj.name
                room_id = player_obj.room_id
                
                if room_id:
                    room = self.rooms.get(room_id)
                    if room:
                        room.remove_client(client_fileno) # This also removes from room.clients and updates player_obj
                        if not room.clients: # If room is empty after client leaves, delete it
                            del self.rooms[room_id]
                            print(f"Room {room_id} deleted as it is empty.")
                
                # Remove from connected_clients
                self.connected_clients.pop(client_fileno, None)

                try:
                    client_info["socket"].close()
                except Exception as e:
                    print(f"Error closing socket during cleanup for {client_fileno}: {e}")
                
                self._add_lobby_chat_message(f"{client_name} disconnected from the server.", is_system=True)
                self._broadcast_lobby_update() # Immediate update after client disconnects
                print(f"Cleaned up client {client_name} ({client_fileno}).")


    def _broadcast_game_state_to_room(self, room_id):
        room = self.rooms.get(room_id)
        if room:
            for fileno in room.clients:
                game_state = room.get_game_state_for_client(fileno)
                self._send_to_client(fileno, game_state)


if __name__ == "__main__":
    server = CodenamesServer(HOST, PORT)
    server.start()
