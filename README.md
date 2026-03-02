# TG Leecher Bot 🤖

An advanced Telegram bot for downloading files from URLs and uploading them to Telegram with rich metadata, thumbnails, and automatic file splitting.

## ✨ Features

- **⚡ Fast Downloads**: 4MB chunks with optimized connection pooling
- **✂️ Auto Split**: Automatically splits files > 1.9GB into parts
- **🎬 Video Support**: Upload as document or streamable video
- **📊 Rich Metadata**: Extracts resolution, codec, bitrate, duration
- **🖼 Smart Thumbnails**: Fetches movie posters from iTunes API
- **🌐 Web UI**: Beautiful modern interface with real-time progress
- **🔗 URL Resolution**: Handles redirects and complex URLs

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- Telegram API credentials ([my.telegram.org](https://my.telegram.org))
- Bot token from [@BotFather](https://t.me/botfather)

### Installation

1. Clone the repository:
```bash
git clone <repo-url>
cd tg-leecher-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create `.env` file:
```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
DOWNLOAD_DIR=./downloads
PORT=8080
OWNER_ID=your_telegram_id  # Optional
```

4. Run the bot:
```bash
python bot.py
```

Or run the web server:
```bash
python server.py
```

## 📝 Usage

### Telegram Bot

1. Start a chat with your bot
2. Send any direct download URL
3. Choose upload format (Document or Video)
4. Wait for upload to complete

### Web Interface

1. Open `http://localhost:8080` in your browser
2. Paste the download URL
3. Monitor real-time progress
4. Downloaded files are saved to the configured directory

## 🛠 Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `API_ID` | Telegram API ID | Required |
| `API_HASH` | Telegram API Hash | Required |
| `BOT_TOKEN` | Bot token from @BotFather | Required |
| `DOWNLOAD_DIR` | Download directory | `./downloads` |
| `SPLIT_SIZE` | Max file size before splitting | `1.9 GB` |
| `PORT` | Web server port | `8080` |
| `OWNER_ID` | Admin Telegram ID | `0` |

## 🐳 Docker

Build and run with Docker:

```bash
docker build -t tg-leecher .
docker run -p 8080:8080 --env-file .env tg-leecher
```

## 📁 Project Structure

```
.
├── bot.py           # Main Telegram bot
├── server.py        # FastAPI web server
├── downloader.py    # Download logic
├── uploader.py      # File cleanup utilities
├── utils.py         # Helper functions
├── config.py        # Configuration management
├── static/          # Web UI assets
│   └── index.html   # Modern web interface
├── requirements.txt # Python dependencies
├── Dockerfile       # Docker configuration
└── README.md        # This file
```

## 🔧 Advanced Features

### File Splitting
Files larger than 1.9GB are automatically split into numbered parts to comply with Telegram's file size limits.

### Video Metadata
For video files, the bot extracts:
- Duration
- Resolution (width × height)
- Video codec
- Audio codec
- Bitrate

### Thumbnail Priority
1. iTunes API (movie/show posters)
2. FFmpeg frame extraction
3. Open Graph image from source page

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is open source and available under the MIT License.

## ⚠️ Disclaimer

This bot is for educational purposes only. Users are responsible for complying with copyright laws and terms of service of downloaded content.
