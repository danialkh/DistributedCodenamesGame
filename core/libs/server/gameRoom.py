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


        # print(f"Roles assigned for room {self.room_id}:")
        # print(f"  Red Spymaster: {self.server.connected_clients[self.red_spymaster_fileno].name if self.red_spymaster_fileno and self.red_spymaster_fileno in self.server.connected_clients else 'None'}")
        # print(f"  Red Operatives: {[self.server.connected_clients[f].name for f in self.red_operatives_filenos if f in self.server.connected_clients]}")
        # print(f"  Blue Spymaster: {self.server.connected_clients[self.blue_spymaster_fileno].name if self.blue_spymaster_fileno and self.blue_spymaster_fileno in self.server.connected_clients else 'None'}")
        # print(f"  Blue Operatives: {[self.server.connected_clients[f].name for f in self.blue_operatives_filenos if f in self.server.connected_clients]}")


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
