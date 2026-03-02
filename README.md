# Telegram Leech Bot

A powerful Python-based Telegram bot that downloads files from direct URLs, magnet links, and torrents, then uploads them to Telegram. Features a modern Web UI with real-time progress tracking.

## Features

- 📥 **Multiple Download Sources**: Direct HTTP/HTTPS links, magnet links, and torrent files
- ⚡ **High-Speed Downloads**: Powered by Aria2 with 16 connections per server
- ✂️ **Auto File Splitting**: Automatically splits files >1.9GB to comply with Telegram's 2GB limit
- 📊 **Real-time Progress**: Live progress bars with speed, ETA, and file size
- 🌐 **Modern Web UI**: Glassmorphism design with WebSocket-based updates
- 🖼️ **Custom Thumbnails**: Set custom thumbnails for video uploads
- 📝 **Custom Captions**: Add custom captions to uploaded files
- 📤 **Dump Channel Support**: Auto-upload to specific channels
- 🎬 **Video Support**: Automatic thumbnail generation for videos

## Tech Stack

- **Python 3.11** with asyncio
- **Pyrogram** - Telegram MTProto client
- **Aria2** - High-speed download engine
- **aiohttp** - Async HTTP client and web server
- **FastAPI-style WebSocket** - Real-time communication
- **Tailwind CSS** - Modern UI styling

## Installation

### Prerequisites

- Python 3.11+
- Aria2 installed (`apt-get install aria2` on Ubuntu/Debian)
- FFmpeg installed (optional, for video thumbnails)

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd telegram-leech-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

4. Edit `.env` with your values:
```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
OWNER_ID=your_user_id
```

Get `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org/apps).
Get `BOT_TOKEN` from [@BotFather](https://t.me/BotFather).

## Usage

### Running the Bot

```bash
python bot.py
```

The bot will:
1. Start the Aria2 daemon
2. Start the web server on the configured port
3. Connect to Telegram
4. Begin listening for messages

### Telegram Commands

- `/start` - Show welcome message and help
- `/help` - Show detailed help
- `/setdump <channel_id>` - Set auto-upload dump channel
- `/setcaption <text>` - Set custom caption for uploads
- `/setthumb` (reply to image) - Set custom thumbnail
- `/status` - Show your current settings

### Web UI

Access the web interface at `http://localhost:8080` (or your configured port).

Features:
- Paste URLs directly
- Real-time download/upload progress
- Speed and ETA display
- Activity log
- Connection status indicator

### Downloading Files

Simply send the bot any of the following:
- Direct download URLs (`https://example.com/file.zip`)
- Magnet links (`magnet:?xt=urn:btih:...`)
- Torrent files (upload the `.torrent` file)

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Telegram  │────▶│   Bot.py    │────▶│   Aria2     │
│   Client    │◄────│  (Pyrogram) │◄────│  Daemon     │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │   Web UI    │
                    │  (aiohttp)  │
                    └─────────────┘
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `API_ID` | Telegram API ID | - |
| `API_HASH` | Telegram API Hash | - |
| `BOT_TOKEN` | Bot token from @BotFather | - |
| `OWNER_ID` | Your Telegram user ID | 0 |
| `PORT` | Web server port | 8080 |
| `DOWNLOAD_DIR` | Download directory | ./downloads |
| `SPLIT_SIZE` | Max file size before splitting | 1900MB |

## Project Structure

```
.
├── bot.py              # Main bot entry point
├── server.py           # Standalone web server
├── config.py           # Configuration settings
├── downloader.py       # Direct download handler
├── uploader.py         # Telegram upload handler
├── utils.py            # Shared utilities
├── static/
│   └── index.html      # Web UI
├── lastperson07/
│   ├── aria2_client.py # Aria2 RPC client
│   ├── settings_db.py  # User settings storage
│   └── split_utils.py  # File splitting utilities
└── requirements.txt
```

## Troubleshooting

### Bot not responding
- Check that all environment variables are set correctly
- Verify the bot token is valid
- Check the logs for connection errors

### Downloads not starting
- Ensure Aria2 is installed: `aria2c --version`
- Check that port 6800 is not in use
- Verify the URL is accessible

### Uploads failing
- Check that the OWNER_ID is set correctly
- Verify the bot has permission to send files in the target chat
- Check file sizes don't exceed Telegram limits

### Web UI not loading
- Verify the PORT is not in use by another service
- Check firewall settings
- Ensure static files are in the correct directory

## License

MIT License - Feel free to use and modify!

## Credits

Built with:
- [Pyrogram](https://docs.pyrogram.org/)
- [Aria2](https://aria2.github.io/)
- [aiohttp](https://docs.aiohttp.org/)
- [Tailwind CSS](https://tailwindcss.com/)
