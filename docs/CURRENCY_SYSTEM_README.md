# Custom Currency System

A comprehensive Discord bot economy system with work, slut, crime, and rob commands, inspired by UnbelievaBoat mechanics but implemented as a standalone system.

## 🎯 Features

### Core Commands
- **`/economy work`** - Earn money through legitimate work (100% success rate)
- **`/economy slut`** - High-risk earning activity with 30% failure chance
- **`/economy crime`** - Criminal activities with 40% success rate
- **`/economy rob <user>`** - Steal money from other users with 30% success rate

### Balance Management
- **`/economy balance [user]`** - Check balance and statistics
- **`/economy leaderboard [page]`** - View server leaderboard
- **`/economy give <user> <amount>`** - Transfer money to another user
- **`/economy deposit <amount|all>`** - Move cash to bank
- **`/economy withdraw <amount|all>`** - Move money from bank to cash

### Admin Commands
- **`/economy admin add-money <user> <amount> [location]`** - Add money to user
- **`/economy admin remove-money <user> <amount> [location]`** - Remove money from user
- **`/economy admin reset-balance <user>`** - Reset user's balance to zero
- **`/economy admin economy-stats`** - View economy statistics

## 🏗️ Architecture

### Database Schema
The system uses SQLite with three main tables:

1. **`user_balances`** - Stores user balances, statistics, and cooldowns
2. **`transactions`** - Logs all money movements for audit trail
3. **`guild_settings`** - Per-server economy configuration

### Command Mechanics

#### Work Command
- **Cooldown**: 1 hour (configurable)
- **Earnings**: 50-200 (configurable)
- **Success Rate**: 100%
- **Risk**: None

#### Slut Command
- **Cooldown**: 2 hours (configurable)
- **Earnings**: 100-500 (configurable)
- **Success Rate**: 70% (30% failure chance)
- **Failure Penalty**: Lose 25% of potential earnings

#### Crime Command
- **Cooldown**: 30 minutes (configurable)
- **Earnings**: 200-800 (configurable)
- **Success Rate**: 40% (60% failure chance)
- **Failure Penalty**: Lose 50% of potential earnings

#### Rob Command
- **Cooldown**: 15 minutes (configurable)
- **Earnings**: 100-400 (configurable)
- **Success Rate**: 30% (70% failure chance)
- **Failure Penalty**: Lose 25% of potential earnings
- **Target Requirements**: Must have at least 50 cash

## ⚙️ Configuration

### Environment Variables
- `CURRENCY_EMOJI` - Currency symbol/emoji (default: 💰)

### Default Settings (Per Guild)
```python
{
    "currency_symbol": "💰",
    "work_cooldown": 3600,      # 1 hour
    "slut_cooldown": 7200,      # 2 hours
    "crime_cooldown": 1800,     # 30 minutes
    "rob_cooldown": 900,        # 15 minutes
    "work_min_earn": 50,
    "work_max_earn": 200,
    "slut_min_earn": 100,
    "slut_max_earn": 500,
    "slut_fail_chance": 0.3,    # 30%
    "crime_min_earn": 200,
    "crime_max_earn": 800,
    "crime_success_rate": 0.4,  # 40%
    "rob_min_earn": 100,
    "rob_max_earn": 400,
    "rob_success_rate": 0.3,    # 30%
}
```

## 🚀 Installation

1. **Add to bot.py**: The currency system is already integrated into your bot.py file
2. **Database**: The system automatically creates the required SQLite database in `data/currency.db`
3. **Dependencies**: Uses existing dependencies (aiosqlite, discord.py)

## 📊 Statistics Tracking

The system tracks comprehensive statistics for each user:
- Total money earned/spent
- Crime success rate (crimes_succeeded/crimes_committed)
- Rob success rate (robs_succeeded/robs_attempted)
- Individual cooldown timestamps
- Complete transaction history

## 🔒 Security Features

- **Permission Checks**: Admin commands require administrator permissions
- **Input Validation**: All amounts and parameters are validated
- **Cooldown System**: Prevents command spam and abuse
- **Transaction Logging**: Complete audit trail of all money movements
- **Balance Protection**: Users cannot go below 0 balance

## 🎮 User Experience

- **Rich Embeds**: All responses use Discord embeds with colors and formatting
- **Error Handling**: Comprehensive error messages for all failure cases
- **Cooldown Display**: Clear indication of when commands will be available
- **Statistics**: Detailed user statistics and success rates
- **Leaderboards**: Server-wide rankings with pagination

## 🔧 Technical Details

- **Async/Await**: Fully asynchronous implementation
- **Database Locking**: Thread-safe database operations
- **Error Recovery**: Graceful handling of database and API errors
- **Memory Efficient**: Minimal memory footprint with lazy loading
- **Scalable**: Supports multiple guilds with isolated economies

## 📈 Future Enhancements

Potential features for future development:
- Daily/weekly bonuses
- Item shop system
- Gambling games integration
- Achievement system
- Economy events and competitions
- Advanced admin controls for economy management

## 🐛 Troubleshooting

### Common Issues
1. **Database Errors**: Ensure the `data/` directory exists and is writable
2. **Permission Errors**: Admin commands require administrator permissions
3. **Cooldown Issues**: Check system time synchronization
4. **Import Errors**: Ensure all dependencies are installed

### Debug Commands
- Use `/sync_commands` to reload the currency system
- Check bot logs for detailed error messages
- Verify database file permissions

## 📝 License

This currency system is part of your Company Sheets Bot project and follows the same licensing terms.
