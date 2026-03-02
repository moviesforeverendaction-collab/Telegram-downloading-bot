# Telegram Leech Bot Design (Render Hosted)

## Goal
Build a simple, robust Telegram Bot that accepts direct download links, downloads the files, and uploads them back to the user's Telegram DM. It must be designed to run on Render's free tier.

## Architecture

*   **Backend:** Python 3 using `Pyrogram` (for all Telegram interactions and MTProto file uploads).
*   **Downloading Engine:** `aiohttp` for fast, asynchronous downloading of the direct links.
*   **Web Server (Render Keep-Alive):** A very minimal `aiohttp.web` server running on the required `$PORT`. Render requires web services to bind to a port, otherwise the deployment fails. This dummy server will respond with "Bot is running" to health checks.
*   **File Handling System:**
    *   **Download Phase:** User sends a link via message -> Bot downloads to local `./downloads/` -> Bot edits its "Downloading..." message with a progress bar.
    *   **Upload Phase:** Pyrogram reads the local file -> Uploads to the same chat -> Bot edits its "Uploading..." message with a progress bar.
    *   **Cleanup Phase:** Deletes local files to prevent Render's ephemeral disk from filling up.

## Components
1.  **Main Bot (`bot.py`)**: Contains Pyrogram setup, message handlers for `/start` and valid URLs.
2.  **Downloader (`utils/download.py`)**: `aiohttp` logic with progress callbacks.
3.  **Dummy Web Server (`server.py`)**: Simple HTTP server to satisfy Render's port binding requirement.
4.  **Progress Helper (`utils/progress.py`)**: Logic to format the progress bar and ETA so it looks nice in Telegram messages without hitting rate limits (editing messages too fast).

## User Flow
1.  User sends `/start` -> Bot replies: "Send me a direct download link."
2.  User sends a link (e.g., `https://example.com/file.zip`).
3.  Bot replies: `Downloading... [▓▓▓▓▓░░░░░] 50%`
4.  Bot edits message: `Uploading... [▓▓▓▓▓▓▓▓░░] 80%`
5.  Bot sends the file buffer to the user.
6.  Bot edits original message to: `Completed!`

## Constraints
*   **Storage:** Render's free tier has limited disk space and memory (512MB RAM). We must download files into the ephemeral container and delete them immediately.
*   **Speed:** Downloading relies on the source link's speed; uploading relies on Telegram's API via Pyrogram. We will use `TgCrypto` to speed up Pyrogram.
*   **Telegram Limits:** Max 2GB per file for standard bots. If the user needs 4GB, they require a Premium User Session.
