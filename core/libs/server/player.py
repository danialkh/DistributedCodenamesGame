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

# --- Constants ---
HOST = '127.0.0.1'
PORT = 5555
HEADER_LENGTH = 10


class Player:
    """Represents a player connected to the server."""
    def __init__(self, fileno, name):
        self.fileno = fileno
        self.name = name
        self.room_id = None
        self.team = None
        self.role = None
        self.chosen_team = None

    def to_dict(self):
        return {"fileno": self.fileno, "name": self.name, "team": self.team, "role": self.role, "chosen_team": self.chosen_team}
