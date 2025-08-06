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

