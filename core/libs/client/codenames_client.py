import pygame
import socket
import threading
import json
import time
import random
import sys
import traceback # For better error debugging
import select # Import the select module for non-blocking I/O

from codenamesClient_class import CodenamesClient
from inputBox import InputBox
from button import Button

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
FontName = 'Comic Sans'
FONT_SMALL = pygame.font.SysFont(FontName, 16)
FONT = pygame.font.SysFont(FontName, 20)
FONT_MEDIUM = pygame.font.SysFont(FontName, 22, bold=True)
FONT_LARGE = pygame.font.SysFont(FontName, 32, bold=True)
GAME_OVER_FONT = pygame.font.SysFont(FontName, 48, bold=True)

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5555


if __name__ == "__main__":
    client = CodenamesClient()
    client.run()
