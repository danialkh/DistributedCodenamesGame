import pytest
from unittest.mock import patch, MagicMock, call
import json

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
        if self.recv_index < len(self.recv_messages):
            chunk = self.recv_messages[self.recv_index]
            self.recv_index += 1
            return chunk
        return b''  # simulate closed connection

    def close(self):
        self.closed = True

    def setblocking(self, flag):
        pass  # ignore for dummy

# Test initial client state and UI elements
def test_initial_state():
    client = CodenamesClient()
    # Check initial values
    assert client.connected is False
    assert client.logged_in is False
    assert client.current_room_id is None
    assert client.game_active is False
    assert isinstance(client.name_input, InputBox)
    assert client.name_input.get_text() == ''
    assert client.my_assigned_team is None
    assert client.my_assigned_role is None

# Test _send_message serializes and sends correctly
def test_send_message_formats_json_correctly():
    client = CodenamesClient()
    dummy_socket = DummySocket()
    client.client = dummy_socket
    client.connected = True

    message = {"type": "join", "name": "Alice"}
    client._send_message(message)

    # One message should be sent
    assert len(dummy_socket.send_buffer) == 1
    data = dummy_socket.send_buffer[0]
    # The message includes a HEADER_LENGTH header with length, padded
    header_bytes = data[:client.HEADER_LENGTH]
    body_bytes = data[client.HEADER_LENGTH:]
    length_from_header = int(header_bytes.decode("utf-8").strip())

    assert length_from_header == len(body_bytes)
    # Body should decode to our JSON message
    body_json = json.loads(body_bytes.decode("utf-8"))
    assert body_json == message

# Test _receive_message can decode a full message correctly
def test_receive_message_receives_valid_json(monkeypatch):
    # Prepare message header and body
    test_msg = {"type": "lobby_update", "players": ["Alice"], "rooms": [], "chat": []}
    encoded = json.dumps(test_msg).encode('utf-8')
    header = f"{len(encoded):<10}".encode('utf-8')

    dummy_socket = DummySocket(recv_messages=[header, encoded])
    client = CodenamesClient()
    client.client = dummy_socket

    msg = client._receive_message()
    assert isinstance(msg, dict)
    assert msg["type"] == "lobby_update"

# Test _receive_message returns None if server disconnects
def test_receive_message_disconnect():
    dummy_socket = DummySocket(recv_messages=[])
    client = CodenamesClient()
    client.client = dummy_socket

    msg = client._receive_message()
    assert msg is None

# Test handling lobby_update message updates client state properly
def test_handle_lobby_update_message():
    client = CodenamesClient()
    lobby_msg = {
        "type": "lobby_update",
        "players": ["Alice", "Bob"],
        "rooms": [{"id": "room_1", "name": "Test Room", "players": 2, "game_in_progress": False, "owner": "Alice", "owner_fileno": 1}],
        "chat": ["Welcome to lobby"]
    }
    client._handle_message(lobby_msg)

    assert client.lobby_players == ["Alice", "Bob"]
    assert len(client.lobby_rooms) == 1
    assert client.lobby_chat == ["Welcome to lobby"]

# Test resetting connection state clears important fields and closes socket
def test_reset_connection_state_closes_socket():
    client = CodenamesClient()
    dummy_socket = MagicMock()
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
    dummy_socket.close.assert_called_once()

# Test InputBox basic text updating works as expected
def test_input_box_text_update():
    input_box = InputBox(0, 0, 100, 30, placeholder="Enter name")
    # Initially text is empty
    assert input_box.get_text() == ''
    input_box.text = "Hello"
    input_box._update_surface()
    assert input_box.get_text() == "Hello"
    input_box.clear_text()
    assert input_box.get_text() == ''

# Test _try_connect attempts to connect and sends join message
@patch("socket.socket")
def test_try_connect_sends_join(mock_socket_class):
    mock_sock = MagicMock()
    mock_socket_class.return_value = mock_sock

    client = CodenamesClient()
    client.name_input.text = "Tester"

    # Intercept _send_message to confirm it gets called with join message
    sent_messages = []
    def fake_send_message(msg):
        sent_messages.append(msg)

    client._send_message = fake_send_message

    client._try_connect()

    assert client.connected
    # There should be one join message sent
    assert any(m.get("type") == "join" and m.get("name") == "Tester" for m in sent_messages)

# Test _send_set_team does not send if game is active or no room
def test_send_set_team_restricted():
    client = CodenamesClient()
    client.current_room_id = None
    client.game_active = False
    client._send_message = MagicMock()

    client._send_set_team("red")
    # Should not send because no room id
    client._send_message.assert_not_called()

    client.current_room_id = "room_1"
    client.game_active = True
    client._send_message = MagicMock()

    client._send_set_team("blue")
    # Should not send because game is active
    client._send_message.assert_not_called()

    client.game_active = False
    client._send_message = MagicMock()
    client._send_set_team("red")
    client._send_message.assert_called_once()

# Additional tests can be added following the same pattern for guesses, clues, etc,
# but UI rendering and pygame actions are not included here for simplicity.
