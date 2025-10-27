"""
Star Resonance API routes integrated with existing Discord bot.
Uses the existing database connection and bot structure.
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from flask import Blueprint, request, jsonify, current_app

from src.database.star_resonance_models import (
    StarResonanceUser, Battle, BattleParticipant, 
    BattleMonster, GuildConfig, generate_battle_id, generate_auth_token
)

# Create blueprint
sr_api = Blueprint('sr_api', __name__, url_prefix='/api/sr')

def get_database():
    """Get database instance from bot context."""
    # This will be set by the bot when initializing the API
    return current_app.config.get('DATABASE')

def validate_auth_token(token: str) -> Optional[StarResonanceUser]:
    """Validate auth token and return user if valid."""
    db = get_database()
    if not db:
        return None
    
    # This will be implemented as a method in the Database class
    return db.get_sr_user_by_token(token)

@sr_api.route('/ping', methods=['GET'])
def ping():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'star-resonance-api'
    })

@sr_api.route('/battle-report', methods=['POST'])
def battle_report():
    """Receive battle data from damage counter clients."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Validate required fields
        auth_token = data.get('authToken')
        battle_data = data.get('battleData')
        
        if not auth_token or not battle_data:
            return jsonify({'error': 'Missing authToken or battleData'}), 400
        
        # Validate auth token
        user = validate_auth_token(auth_token)
        if not user:
            return jsonify({'error': 'Invalid or expired auth token'}), 401
        
        # Extract battle data
        timestamp = battle_data.get('timestamp', int(datetime.utcnow().timestamp() * 1000))
        duration = battle_data.get('duration', 0)
        player_data = battle_data.get('player', {})
        enemies_data = battle_data.get('enemies', [])
        
        if not player_data:
            return jsonify({'error': 'No player data provided'}), 400
        
        db = get_database()
        if not db:
            return jsonify({'error': 'Database not available'}), 500
        
        # Process battle data using existing database methods
        battle_id = await db.process_sr_battle_report(
            user_id=user.id,
            timestamp=timestamp,
            duration=duration,
            player_data=player_data,
            enemies_data=enemies_data
        )
        
        return jsonify({
            'success': True,
            'battle_id': battle_id,
            'message': 'Battle data recorded successfully'
        })
        
    except Exception as e:
        current_app.logger.error(f"Battle report error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@sr_api.route('/register', methods=['POST'])
def register_user():
    """Register a new user for Star Resonance integration."""
    try:
        data = request.get_json()
        discord_id = data.get('discord_id')
        discord_username = data.get('discord_username')
        
        if not discord_id or not discord_username:
            return jsonify({'error': 'Missing discord_id or discord_username'}), 400
        
        db = get_database()
        if not db:
            return jsonify({'error': 'Database not available'}), 500
        
        # Use existing database method
        auth_token = await db.register_sr_user(discord_id, discord_username)
        
        return jsonify({
            'success': True,
            'auth_token': auth_token,
            'message': 'User registered successfully'
        })
        
    except Exception as e:
        current_app.logger.error(f"User registration error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@sr_api.route('/user/<int:discord_id>/stats', methods=['GET'])
def get_user_stats(discord_id: int):
    """Get user statistics."""
    try:
        db = get_database()
        if not db:
            return jsonify({'error': 'Database not available'}), 500
        
        # Use existing database method
        stats = await db.get_sr_user_stats(discord_id)
        
        if not stats:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'success': True,
            'user': stats
        })
        
    except Exception as e:
        current_app.logger.error(f"Get user stats error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500