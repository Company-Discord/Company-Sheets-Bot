"""
Flask API server for Star Resonance Discord bot integration.
Handles battle data collection from damage counter clients.
Integrated with existing unified database.
"""

import os
import asyncio
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def create_app():
    """Create and configure Flask application."""
    app = Flask(__name__)
    
    # Enable CORS for all routes
    CORS(app)
    
    # Health check endpoint
    @app.route('/health')
    def health():
        return jsonify({
            'status': 'healthy',
            'service': 'star-resonance-api',
            'database': 'integrated'
        })
    
    # Root endpoint
    @app.route('/')
    def root():
        return jsonify({
            'service': 'Star Resonance API',
            'version': '1.0.0',
            'endpoints': {
                'health': '/health',
                'ping': '/api/sr/ping',
                'register': '/api/sr/register',
                'battle_report': '/api/sr/battle-report',
                'user_stats': '/api/sr/user/<discord_id>/stats'
            }
        })
    
    # Simple battle report endpoint for testing
    @app.route('/api/sr/battle-report', methods=['POST'])
    def battle_report():
        """Receive battle data from damage counter clients."""
        try:
            data = request.get_json()
            if not data:
                app.logger.error("No JSON data provided")
                return jsonify({'error': 'No JSON data provided'}), 400
            
            # Validate required fields
            if 'authToken' not in data:
                app.logger.error("Missing authToken in request")
                return jsonify({'error': 'Missing authToken'}), 400
                
            if 'battleData' not in data:
                app.logger.error("Missing battleData in request")
                return jsonify({'error': 'Missing battleData'}), 400
            
            battle_data = data['battleData']
            if 'player' not in battle_data:
                app.logger.error("Missing player data in battleData")
                return jsonify({'error': 'Missing player data'}), 400
            
            # Log the received data (truncated for readability)
            app.logger.info(f"Received battle report from token: {data['authToken'][:10]}...")
            app.logger.info(f"Player: {battle_data['player'].get('name', 'Unknown')}")
            app.logger.info(f"Duration: {battle_data.get('duration', 0)}ms")
            
            # For now, just acknowledge receipt
            # In a full implementation, this would process the data
            return jsonify({
                'success': True,
                'message': 'Battle data received (test mode)',
                'timestamp': battle_data.get('timestamp', 'unknown'),
                'player': battle_data['player'].get('name', 'Unknown')
            })
            
        except Exception as e:
            app.logger.error(f"Battle report error: {str(e)}")
            return jsonify({'error': f'Internal server error: {str(e)}'}), 500
    
    # Simple ping endpoint
    @app.route('/api/sr/ping', methods=['GET'])
    def ping():
        """Health check endpoint."""
        return jsonify({
            'status': 'ok',
            'timestamp': '2024-01-01T00:00:00Z',
            'service': 'star-resonance-api'
        })
    
    return app

if __name__ == '__main__':
    app = create_app()
    
    # Get configuration from environment
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting Star Resonance API server on {host}:{port}")
    print(f"Debug mode: {debug}")
    
    app.run(host=host, port=port, debug=debug)