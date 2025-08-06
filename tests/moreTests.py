import pytest
import json
import pygame

# Import the CodenamesClient class from your client module
from codenames_client import CodenamesClient, InputBox

# Helper to create a dummy socket mock that accepts sendall & recv
class DummySocket:
    def __init__(self, recv_messages=None):
        # recv_messages should be a list of binary data chunks to return on recv calls
        self.send_buffer = []
        self.recv_messages = recv_messages or []
        self.recv_index = 0
        self.closed = False

    def sendall(self, data):
        self.send_buffer.append(data)

    def recv(self, bufsize):
        if self.closed:
            return b''
        if self.recv_index < len(self.recv_messages):
            chunk = self.recv_messages[self.recv_index]
            self.recv_index += 1
            return chunk
        return b''  # simulate closed connection

    def close(self):
        self.closed = True

    def setblocking(self, flag):
        pass  # ignore for dummy

# Helper function to create an encoded message for the DummySocket
def _create_message(message_dict):
    encoded = json.dumps(message_dict).encode('utf-8')
    header = f"{len(encoded):<10}".encode('utf-8')
    return header + encoded

# Test initial client state and UI elements
def test_initial_state():
    """Verifies the initial state of a new CodenamesClient instance."""
    client = CodenamesClient()
    # Check initial values, which should be initialized in CodenamesClient.__init__
    assert client.connected is False
    assert client.logged_in is False
    assert client.current_room_id is None
    assert client.game_active is False
    assert isinstance(client.name_input, InputBox)
    assert client.name_input.get_text() == ''
    assert client.my_assigned_team is None
    assert client.my_assigned_role is None
    assert client.lobby_players == []
    assert client.lobby_rooms == []
    assert client.current_room_players == []
    assert client.game_board == []

# Test _receive_message can decode a full message correctly
def test_receive_message_receives_valid_json():
    """Ensures the client can receive and decode a full, valid JSON message."""
    test_msg = {"type": "lobby_update", "players": ["Alice"], "rooms": [], "chat": []}
    dummy_socket = DummySocket(recv_messages=[_create_message(test_msg)])
    client = CodenamesClient()
    client.client = dummy_socket

    msg = client._receive_message()
    assert isinstance(msg, dict)
    assert msg["type"] == "lobby_update"
    assert msg["players"] == ["Alice"]

# Test _receive_message returns None if server disconnects
def test_receive_message_disconnect():
    """Checks that a disconnected socket returns None from _receive_message."""
    dummy_socket = DummySocket(recv_messages=[b''])
    client = CodenamesClient()
    client.client = dummy_socket

    msg = client._receive_message()
    assert msg is None
    # The client should also reset its state upon receiving a disconnection
    assert client.connected is False

# Test handling lobby_update message updates client state properly
def test_handle_lobby_update_message():
    """Tests if a lobby_update message correctly populates the client's lobby state."""
    client = CodenamesClient()
    lobby_msg = {
        "type": "lobby_update",
        "players": ["Danial", "Bob"],
        "rooms": [{"id": "room_1", "name": "Test Room", "players": 2, "game_in_progress": False, "owner": "Danial", "owner_fileno": 1}],
        "chat": ["Welcome to lobby"]
    }
    client._handle_message(lobby_msg)

    assert client.lobby_players == ["Danial", "Bob"]
    assert len(client.lobby_rooms) == 1
    assert client.lobby_chat == ["Welcome to lobby"]
    assert client.lobby_rooms[0]["id"] == "room_1"

# Test resetting connection state clears important fields and closes socket
def test_reset_connection_state_closes_socket():
    """Ensures that the client's state is reset and the socket is closed upon disconnection."""
    dummy_socket = DummySocket(recv_messages=[])
    client = CodenamesClient()
    client.client = dummy_socket
    client.connected = True
    client.logged_in = True
    client.current_room_id = "room_1"
    client.game_active = True
    client.my_assigned_team = "red"
    client.my_assigned_role = "operative"

    client._reset_connection_state()
    assert client.connected is False
    assert client.logged_in is False
    assert client.current_room_id is None
    assert client.game_active is False
    assert client.my_assigned_team is None
    assert client.my_assigned_role is None
    assert dummy_socket.closed is True
    # The client's socket reference should be cleared
    assert client.client is None

# Test client can send a login message after connecting
def test_send_login_message():
    """Tests the client's ability to send a login message and update its logged_in state."""
    client = CodenamesClient()
    client.client = DummySocket()
    client.connected = True
    client.name_input.text = "TestPlayer"

    client._send_login()
    assert client.logged_in is True
    assert len(client.client.send_buffer) == 1

    sent_msg_body = json.loads(client.client.send_buffer[0][10:].decode('utf-8'))
    assert sent_msg_body["type"] == "login"
    assert sent_msg_body["name"] == "TestPlayer"

# Test client can send a create_room message
def test_send_create_room():
    """Verifies the client sends the correct message when creating a room."""
    client = CodenamesClient()
    client.client = DummySocket()
    client.connected = True
    client.logged_in = True
    client.create_room_input.text = "My New Room"

    client._send_create_room()
    assert len(client.client.send_buffer) == 1

    sent_msg_body = json.loads(client.client.send_buffer[0][10:].decode('utf-8'))
    assert sent_msg_body["type"] == "create_room"
    assert sent_msg_body["name"] == "My New Room"

# Test client can send a join_room message
def test_send_join_room():
    """Checks the client's ability to send a join_room message and update its room ID."""
    client = CodenamesClient()
    client.client = DummySocket()
    client.connected = True
    client.logged_in = True

    room_id_to_join = "room_abc"
    client._send_join_room(room_id_to_join)
    # The client should set its current_room_id to the joined room's ID
    assert client.current_room_id == room_id_to_join
    assert len(client.client.send_buffer) == 1

    sent_msg_body = json.loads(client.client.send_buffer[0][10:].decode('utf-8'))
    assert sent_msg_body["type"] == "join_room"
    assert sent_msg_body["room_id"] == room_id_to_join

# Test client can send a leave_room message
def test_send_leave_room():
    """Tests that a leave_room message is sent and the client's state is reset."""
    client = CodenamesClient()
    client.client = DummySocket()
    client.connected = True
    client.logged_in = True
    client.current_room_id = "room_xyz"

    client._send_leave_room()
    # The client should clear its current_room_id
    assert client.current_room_id is None
    assert len(client.client.send_buffer) == 1

    sent_msg_body = json.loads(client.client.send_buffer[0][10:].decode('utf-8'))
    assert sent_msg_body["type"] == "leave_room"
    assert sent_msg_body["room_id"] == "room_xyz"

# Test handling a game_state_update message
def test_handle_game_state_update():
    """Verifies that a game_state_update message correctly updates the client's game state."""
    client = CodenamesClient()
    game_state_msg = {
        "type": "game_state_update",
        "board": [{"word": "TEST", "color": "red", "revealed": False}],
        "red_score": 9,
        "blue_score": 8,
        "turn": "red",
        "clue_word": "CLUE",
        "clue_number": 2,
        "guesses_made": 0,
        "game_over": False,
        "winner": None,
        "is_spymaster": True,
        "my_team": "red",
        "my_role": "spymaster",
        "spymaster_red": 123,
        "spymaster_blue": 456,
        "operative_red": [789],
        "operative_blue": [1011],
    }
    client._handle_message(game_state_msg)

    assert client.game_active is True
    assert client.red_score == 9
    assert client.current_turn == "red"
    assert client.clue_word == "CLUE"
    assert client.is_spymaster is True
    assert client.my_assigned_team == "red"
    assert client.my_assigned_role == "spymaster"
    assert client.game_board[0]["word"] == "TEST"

# Test sending a clue when it's the client's turn as a spymaster
def test_send_clue_sends_correct_message_when_valid():
    """Verifies the client sends a clue message with the correct data."""
    client = CodenamesClient()
    client.client = DummySocket()
    client.connected = True
    client.current_room_id = "room_1"
    client.game_active = True
    client.my_assigned_role = "spymaster"
    client.my_assigned_team = "red"
    client.current_turn = "red"
    
    # Manually set the input boxes to simulate user input
    client.clue_word_input.text = "TESTWORD"
    client.clue_number_input.text = "2"
    
    client._send_clue()

    assert len(client.client.send_buffer) == 1
    sent_msg_body = json.loads(client.client.send_buffer[0][10:].decode('utf-8'))
    assert sent_msg_body["type"] == "clue"
    assert sent_msg_body["clue_word"] == "TESTWORD"
    assert sent_msg_body["clue_number"] == 2

# Test sending a guess when it's the client's turn as an operative
def test_send_guess_sends_correct_message_when_valid():
    """Ensures the client sends a guess message with the correct word."""
    client = CodenamesClient()
    client.client = DummySocket()
    client.connected = True
    client.current_room_id = "room_1"
    client.game_active = True
    client.my_assigned_role = "operative"
    client.my_assigned_team = "red"
    client.current_turn = "red"
    client.clue_word = "CLUE" # A clue must be active to guess
    
    word_to_guess = "WORD_TO_GUESS"
    client._send_guess(word_to_guess)
    
    assert len(client.client.send_buffer) == 1
    sent_msg_body = json.loads(client.client.send_buffer[0][10:].decode('utf-8'))
    assert sent_msg_body["type"] == "guess"
    assert sent_msg_body["word"] == word_to_guess

# Test sending a chat message to the room
def test_send_room_chat_message():
    """Checks that a chat message for a room is sent with the correct content."""
    client = CodenamesClient()
    client.client = DummySocket()
    client.connected = True
    client.current_room_id = "room_1"
    client.chat_input.text = "Hello team!"
    
    client._send_chat_message()

    assert len(client.client.send_buffer) == 1
    sent_msg_body = json.loads(client.client.send_buffer[0][10:].decode('utf-8'))
    assert sent_msg_body["type"] == "chat_message"
    assert sent_msg_body["room_id"] == "room_1"
    assert sent_msg_body["text"] == "Hello team!"

# Test handling a 'game_over' state
def test_handle_game_over():
    """Tests that the game state is correctly updated to game over."""
    client = CodenamesClient()
    # Set an initial active game state to ensure the message changes it
    client.game_active = True
    game_over_msg = {
        "type": "game_state_update",
        "board": [],
        "red_score": 0,
        "blue_score": 0,
        "turn": None,
        "clue_word": None,
        "clue_number": 0,
        "guesses_made": 0,
        "game_over": True,
        "winner": "red",
        "is_spymaster": False,
        "my_team": "red",
        "my_role": "operative",
        "spymaster_red": None,
        "spymaster_blue": None,
        "operative_red": [],
        "operative_blue": [],
    }
    client._handle_message(game_over_msg)

    assert client.game_active is False
    assert client.game_over is True
    assert client.winner == "red"
    assert client.clue_word is None
