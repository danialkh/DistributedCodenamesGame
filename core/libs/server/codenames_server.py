import pygame
import socket
import threading
import json
import time
import random
import sys
import traceback # For better error debugging
import select # Import the select module for non-blocking I/O

from inputBox import InputBox
from button import Button

# --- Constants ---
WIDTH, HEIGHT = 1000, 650
FPS = 60
HEADER_LENGTH = 10 # Must match server's HEADER_LENGTH
