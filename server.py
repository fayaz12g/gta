import asyncio
import websockets
import json
import random
import os
import socket  # Import socket module for getting IP address
from aiohttp import web

sessions = {}

async def handler(websocket, path):
    async for message in websocket:
        data = json.loads(message)
        session_id = data['sessionId']

        if session_id not in sessions:
            sessions[session_id] = {
                'players': [],
                'host': None,
                'game_started': False,
                'current_round': 0,
                'total_rounds': 0,
                'scripts': await load_scripts(),
                'leaderboard': {}
            }

        if data['type'] == 'join':
            role = data['role']
            player_name = data['name'] if 'name' in data else None
            if role == 'host':
                print(f"Host connected for session {session_id}")
                sessions[session_id]['host'] = websocket
                await websocket.send(json.dumps({'type': 'host_joined'}))
            elif role == 'player':
                print(f"Player {player_name} attempting to join session {session_id}")
                if sessions[session_id]['host'] is None:
                    await websocket.send(json.dumps({'type': 'error', 'message': 'Host not connected yet'}))
                    print(f"Host not connected yet, player {player_name} cannot join.")
                    continue
                sessions[session_id]['players'].append({
                    'websocket': websocket,
                    'name': player_name,
                    'points': 0,
                    'role': None
                })
                sessions[session_id]['leaderboard'][player_name] = 0
                await notify_players(session_id)
                await notify_host(session_id)

        elif data['type'] == 'start_game':
            print(f"Game starting for session {session_id} with {data['total_rounds']} rounds.")
            total_rounds = data['total_rounds']
            sessions[session_id]['total_rounds'] = total_rounds
            sessions[session_id]['game_started'] = True
            await start_round(session_id)

        elif data['type'] == 'submit_guess':
            print(f"Guess submitted in session {session_id}.")
            session = sessions[session_id]
            guesser_name = data['guesser']
            guessed_player = data['guess']
            adlibber = data['adlibber']
            if guessed_player == adlibber:
                for player in session['players']:
                    if player['name'] == guesser_name:
                        player['points'] += 1
                        session['leaderboard'][guesser_name] += 1
            await update_leaderboard(session_id)
            await start_round(session_id)

        elif data['type'] == 'start_round':
            script_id = data['script_id']
            try:
                script = next(script for script in sessions[session_id]['scripts'] if script['script_id'] == script_id)
                # Get server IP address dynamically
                server_ip = socket.gethostbyname(socket.gethostname())

                # Assign roles and send dialogue sequentially
                players = sessions[session_id]['players']
                random.shuffle(players)
                roles = ['Person 1', 'Person 2', 'Person 3']
                player_roles = {}
                for player, role in zip(players, roles):
                    player['role'] = role
                    player_roles[player['name']] = role

                session['player_roles'] = player_roles
                session['current_script'] = script

                # Send start_round message to each player with their respective role and dialogue
                for player in players:
                    if player['role'] in ['Person 1', 'Person 2', 'Person 3']:
                        await player['websocket'].send(json.dumps({
                            'type': 'start_round',
                            'role': player['role'],
                            'script_id': script['script_id'],
                            'ipAddress': server_ip,
                            'dialogue': script['dialogue'][player['role']],
                            'round': f"{session['current_round']}/{session['total_rounds']}"
                        }))

                await update_leaderboard(session_id)
                await notify_host(session_id)

            except StopIteration:
                print(f"Script with ID {script_id} not found.")
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': f"Script with ID {script_id} not found."
                }))
        elif path.startswith('/api/scripts/'):
            script_id = path.split('/')[-1]  # Extract the script ID from the path
            try:
                script = next(script for script in sessions[session_id]['scripts'] if script['script_id'] == int(script_id))
                await websocket.send(json.dumps({
                    'type': 'script_details',
                    'script': script
                }))
            except StopIteration:
                await websocket.send(json.dumps({
                    'type': 'error',
                    'message': f"Script with ID {script_id} not found."
                }))

async def start_round(session_id):
    session = sessions[session_id]
    session['current_round'] += 1
    total_rounds = int(session['total_rounds'])  # Ensure total_rounds is integer

    if session['current_round'] > total_rounds:
        await end_game(session_id)
        return

    players = session['players']
    random.shuffle(players)
    roles = ['Person 1', 'Person 2', 'Person 3', 'Guesser']
    player_roles = {}
    for player, role in zip(players, roles):
        player['role'] = role
        player_roles[player['name']] = role

    script = random.choice(session['scripts'])
    session['current_script'] = script
    session['player_roles'] = player_roles

    # Print debug information
    print(f"Chosen script ID: {script['script_id']}")  # Assuming 'scripts' is a list of dictionaries

    # Get server IP address dynamically
    server_ip = socket.gethostbyname(socket.gethostname())

    # Send start_round message with script_id and dynamically fetched ipAddress
    for player in players:
        if player['role'] == 'Guesser':
            await player['websocket'].send(json.dumps({
                'type': 'start_round',
                'role': 'guesser',
                'script_id': script['script_id'],
                'ipAddress': server_ip,  # Include dynamically fetched IP address
                'name': player['name'],
                'round': f"{session['current_round']}/{total_rounds}"
            }))
        else:
            await player['websocket'].send(json.dumps({
                'type': 'start_round',
                'role': player['role'],
                'script_id': script['script_id'],
                'ipAddress': server_ip,  # Include dynamically fetched IP address
                'name': player['name'],
                'round': f"{session['current_round']}/{total_rounds}"
            }))

    await update_leaderboard(session_id)
    await notify_host(session_id)


async def notify_players(session_id):
    players = sessions[session_id]['players']
    player_names = [player['name'] for player in players]
    for player in players:
        await player['websocket'].send(json.dumps({
            'type': 'update_players',
            'players': player_names
        }))
    print(f"Notified players in session {session_id} of player list update.")

async def notify_host(session_id):
    host = sessions[session_id]['host']
    if host is None:
        print(f"No host found for session {session_id} when trying to notify host.")
        return
    players = sessions[session_id]['players']
    player_names = [player['name'] for player in players]
    await host.send(json.dumps({
        'type': 'update_players',
        'players': player_names
    }))
    print(f"Notified host in session {session_id} of player list update with players: {player_names}")


async def update_leaderboard(session_id):
    session = sessions[session_id]
    leaderboard = session['leaderboard']

    for player in session['players']:
        await player['websocket'].send(json.dumps({
            'type': 'update_leaderboard',
            'leaderboard': leaderboard
        }))

    host = session['host']
    if host:
        await host.send(json.dumps({
            'type': 'update_leaderboard',
            'leaderboard': leaderboard
        }))

    print(f"Updated leaderboard for session {session_id}.")


async def end_game(session_id):
    session = sessions[session_id]
    leaderboard = session['leaderboard']

    for player in session['players']:
        await player['websocket'].send(json.dumps({
            'type': 'end_game',
            'leaderboard': leaderboard
        }))

    host = session['host']
    if host:
        await host.send(json.dumps({
            'type': 'end_game',
            'leaderboard': leaderboard
        }))

    print(f"Game ended for session {session_id}.")


async def load_scripts():
    script_path = os.path.join(os.path.dirname(__file__), 'scripts.json')
    with open(script_path) as f:
        scripts = json.load(f)
    print("Loaded scripts from scripts.json")
    return scripts

start_server = websockets.serve(handler, '0.0.0.0', 8765)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
