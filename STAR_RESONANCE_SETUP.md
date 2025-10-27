# Star Resonance Discord Integration Setup

This integration allows Star Resonance Damage Counter clients to automatically upload battle data to your Discord server for tracking and leaderboards.

## Setup Instructions

### 1. Environment Variables

The Star Resonance integration uses your existing PostgreSQL database configuration. Add these variables to your `.env` file:

```env
# Star Resonance API Configuration
STAR_RESONANCE_API_URL=https://your-railway-app.railway.app
STAR_RESONANCE_REPORT_CHANNEL_ID=your_report_channel_id_here

# Flask API Server Configuration (uses existing database)
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
FLASK_DEBUG=false

# Your existing PostgreSQL configuration (already configured)
POSTGRES_HOST=your_postgres_host
POSTGRES_PORT=5432
POSTGRES_DB=your_database_name
POSTGRES_USER=your_username
POSTGRES_PASSWORD=your_password
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the Services

**Option A: Run both services together**
```bash
python start.py
```

**Option B: Run separately**
```bash
# Terminal 1: API Server
python api_server.py

# Terminal 2: Discord Bot
python bot.py
```

### 4. Configure Discord Bot

1. Set the report channel: `/sr_setreport` (admin only)
2. Configure settings: `/sr_config` (admin only)

### 5. User Registration

Users need to register to get auth tokens:

1. Run `/sr_register` in Discord
2. Copy the auth token
3. Configure Star Resonance Damage Counter:
   - Open Discord Integration settings
   - Paste auth token
   - Set server URL to your Railway app URL
   - Enable auto-upload

## API Endpoints

- `GET /health` - Health check
- `GET /api/sr/ping` - API ping
- `POST /api/sr/register` - User registration
- `POST /api/sr/battle-report` - Battle data upload
- `GET /api/sr/user/<discord_id>/stats` - User statistics
- `GET /api/sr/battles/<battle_id>` - Battle details

## Discord Commands

- `/sr_register` - Register for battle tracking
- `/sr_stats [user]` - View battle statistics
- `/sr_leaderboard [timeframe] [category]` - View leaderboards
- `/sr_lastbattle` - View most recent battle
- `/sr_setreport` - Set report channel (admin)
- `/sr_config` - View configuration (admin)

## Deployment on Railway

1. Connect your GitHub repository to Railway
2. Set environment variables in Railway dashboard
3. Railway will automatically deploy both services

## Database Schema

The integration uses SQLAlchemy models for:
- User registration and auth tokens
- Battle metadata and participants
- Monster information
- Aggregated statistics
- Guild configuration

## Troubleshooting

### Common Issues

1. **API server not starting**: Check FLASK_PORT is available
2. **Database errors**: Ensure DATABASE_URL is correct
3. **Discord commands not syncing**: Run `/sync_commands` (admin)
4. **Upload failures**: Check auth token and server URL

### Logs

- Discord bot logs: Console output
- API server logs: Flask debug output
- Database logs: SQLAlchemy echo (set FLASK_DEBUG=true)

## Security Notes

- Auth tokens are unique per user
- API endpoints validate tokens
- Admin commands require proper permissions
- Database uses parameterized queries
