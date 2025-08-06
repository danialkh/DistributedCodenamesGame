# DistributedCodenamesGame


# 🎲 Codenames Game

Welcome to the **Codenames** game implementation! Below you'll find steps to quickly get up and running.

---

## 🚀 Getting Started

Clone this repository and navigate to your project directory.

---

## 🖥️ Usage

# 🖥️ Run Docker
For using the docker container:
	*docker-compose up --build*
or simply use this comment to set the mongo to port 27017 which is the game port:
	*docker run -d --name my-mongodb -p 27017:27017 mongo:4.4*

# 🖥️ Run Server and client
**After running docker and mongodb**
 
**1. Start the Server**

Obtain these two files:
∗ 1. For the server use the main.py in the main folder:
python main.py
∗ 2. for the client use the codenames client.py:
python ../core/libs/client/codenames_client.py
 
 Open a terminal and run:
 
 **python codenames_server.py**
 
 Then, in a separate terminal window, start the client:
 or simply run 1.sh (which is for oppening the server usign bash)
 
 **2. Start the Client**

 Open a terminal and run:
 
 **python codenames_client.py**
 
 Make sure to run the server before the client.
 Run this for more clients to play.
 or simply run 2.sh (which is for oppening the client usign bash)

## 🖥️ Codenames Lobby 

**Codenames Lobby**
    This Python-based multiplayer game lobby allows players to:

    
    •	View a list of online players currently not in a room
    •	See all available game rooms and their names  
    •	Create a new room by entering a name and clicking "Create Room"
    •	Participate in a lobby-wide chat with live messaging
    •	Refresh the lobby to update player and room lists    
    The lobby serves as a central hub to organize game sessions, chat, and manage rooms, system messages before gameplay begins.

<img width="1000" height="650" alt="Python 3 13 8_6_2025 9_53_20 AM" src="https://github.com/user-attachments/assets/b42202d3-291b-4e35-b9b8-524149a77d1e" />


  **It is Red's Turn to guess**

<img width="1000" height="700" alt="Python 3 13 7_28_2025 2_14_54 PM" src="https://github.com/user-attachments/assets/1d154acf-0460-4348-ae11-7dccb20a7bfc" />

  **Blue Waits for the opponent to guess**

<img width="1000" height="700" alt="Python 3 13 7_28_2025 2_14_20 PM" src="https://github.com/user-attachments/assets/49fad4b8-9fef-4a9b-90be-1db919bc1366" />
