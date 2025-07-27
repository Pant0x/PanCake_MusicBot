# Pancake Music Bot
   ```
   https://discord.com/oauth2/authorize?client_id=1379577348927782963
   ```

A professional Discord music bot with high-quality playback, queue, playlists, lyrics, filters, 24/7 mode, and more.

## Features
- YouTube playback (with search and direct links)
- Queue management (add, remove, shuffle, move, export/import)
- Playlists (save, load, share, delete)
- Track history and replay
- Lyrics search (Genius API)
- Audio filters (bassboost, nightcore, vaporwave, 8d, clear)
- 24/7 mode and auto-disconnect
- Smart Autoplay/Auto-DJ
- Slash command support

## Setup
1. Clone the repository.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project directory with your tokens:
   ```
   TOKEN=your_discord_bot_token
   GENIUS_TOKEN=your_genius_api_token
   ```
4. Run the bot:
   ```
   python MyBot.py
   ```

## Usage
Use `!help` or `/help` in Discord to see all commands and features.

## Notes
- Requires Python 3.8+
- Make sure `musicbot.db` is writable by the bot.
- Do **not** commit your `.env` file or tokens to GitHub.

## License
Panto
