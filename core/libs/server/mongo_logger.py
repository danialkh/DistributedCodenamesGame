import socket
import threading
import json
import time
import random
import traceback
import select
import pymongo
from datetime import datetime

# --- MongoDB Logger Class (Updated for localhost connection) ---
class MongoLogger:
    """Handles logging server events to a MongoDB database."""
    def __init__(self, db_host='localhost', db_port=27017, db_name='codenames_monitor', collection_name='server_events'):
        try:
            self.client = pymongo.MongoClient(f"mongodb://{db_host}:{db_port}/", serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            print("Successfully connected to MongoDB.")
        except pymongo.errors.ConnectionFailure as e:
            print(f"Could not connect to MongoDB: {e}")
            self.client = None
        except Exception as e:
            print(f"An unexpected error occurred during MongoDB connection: {e}")
            self.client = None

    def log_event(self, event_type, details):
        """Logs an event to the database if the connection is active."""


        print("event to the database")
        if self.client:
            log_entry = {
                "tz":time.strftime("%I:%M%p on %B %d, %Y"),
                "event_type": event_type,
                "details": details
            }
            try:
                self.collection.insert_one(log_entry)
            except Exception as e:
                print(f"Error logging event to MongoDB: {e}")
