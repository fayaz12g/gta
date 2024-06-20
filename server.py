import asyncio
import websockets
import json
import random

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
                sessions[session_id]['host'] = websocket
                await websocket.send(json.dumps({'type': 'host_joined'}))
            elif role == 'player':
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
            total_rounds = data['total_rounds']
            sessions[session_id]['total_rounds'] = total_rounds
            sessions[session_id]['game_started'] = True
            await start_round(session_id)

        elif data['type'] == 'submit_guess':
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

async def start_round(session_id):
    session = sessions[session_id]
    session['current_round'] += 1
    if session['current_round'] > session['total_rounds']:
        await end_game(session_id)
        return

    players = session['players']
    random.shuffle(players)
    roles = ['Person 1', 'Person 2', 'Person 3', 'Guesser']
    for player, role in zip(players, roles):
        player['role'] = role

    script = random.choice(session['scripts'])

    for player in players:
        if player['role'] == 'Guesser':
            await player['websocket'].send(json.dumps({
                'type': 'start_round',
                'role': 'guesser',
                'team': player['role'],
                'name': player['name'],
                'round': f"{session['current_round']}/{session['total_rounds']}"
            }))
        else:
            await player['websocket'].send(json.dumps({
                'type': 'start_round',
                'role': 'speaker',
                'script': script,
                'team': player['role'],
                'name': player['name'],
                'round': f"{session['current_round']}/{session['total_rounds']}"
            }))

async def notify_players(session_id):
    players = sessions[session_id]['players']
    player_names = [player['name'] for player in players]
    for player in players:
        await player['websocket'].send(json.dumps({
            'type': 'update_players',
            'players': player_names
        }))

async def notify_host(session_id):
    host = sessions[session_id]['host']
    player_names = [player['name'] for player in sessions[session_id]['players']]
    await host.send(json.dumps({
        'type': 'update_players',
        'players': player_names
    }))

async def update_leaderboard(session_id):
    session = sessions[session_id]
    host = session['host']
    leaderboard = session['leaderboard']
    await host.send(json.dumps({
        'type': 'update_leaderboard',
        'leaderboard': leaderboard
    }))

async def end_game(session_id):
    session = sessions[session_id]
    host = session['host']
    await host.send(json.dumps({'type': 'end_game', 'leaderboard': session['leaderboard']}))
    for player in session['players']:
        await player['websocket'].send(json.dumps({'type': 'end_game'}))

async def load_scripts():
    with open('scripts.json') as f:
        return json.load(f)

start_server = websockets.serve(handler, "0.0.0.0", 8765)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()