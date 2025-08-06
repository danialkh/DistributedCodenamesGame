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
FontName = 'Comic Sans'
FONT_SMALL = pygame.font.SysFont(FontName, 16)
FONT = pygame.font.SysFont(FontName, 20)
FONT_MEDIUM = pygame.font.SysFont(FontName, 22, bold=True)
FONT_LARGE = pygame.font.SysFont(FontName, 32, bold=True)
GAME_OVER_FONT = pygame.font.SysFont(FontName, 48, bold=True)

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

