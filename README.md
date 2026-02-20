# GameSphere Import Tool

**GameSphere Import Tool** imports your installed Steam games into [Sunshine](https://github.com/LizardByte/Sunshine) or [Apollo](https://github.com/ClassicOldSong/Apollo) (game streaming hosts), with thumbnail artwork. **No signup for thumbnails:** art is fetched from Steam’s CDN by default (same approach as the [GameSphere](https://github.com/trevlars/GameSphere) client). An optional SteamGridDB API key can be used for community picks.

> **Credit — Original Python project**  
> This project is a fork of **[Sunshine-App-Automation](https://github.com/CommonMugger/Sunshine-App-Automation)** by [CommonMugger](https://github.com/CommonMugger). The original Python automation (Steam detection, config handling, thumbnails, and CLI) was the foundation for this tool. We added a Windows GUI, Apollo support, GameSphere branding, and other improvements. Thank you to CommonMugger for the original work. 

Example: 
![IMG_0759](https://github.com/user-attachments/assets/365301a4-57d8-4b5e-a9d6-5ba4573af638)

## Features

- **Automatically detects installed Steam games** with concurrent processing for speed
- **Fetches game names and thumbnail images** — Steam CDN by default (no API key); optional SteamGridDB for community art
- **Updates Sunshine/Apollo apps.json** with Steam games and their thumbnail images
- **Cross-platform support** for Windows, Linux, and macOS
- **Robust error handling** with comprehensive logging
- **Command-line options** for verbose output, dry runs, and more
- **Environment-based configuration** using .env files
- **Automatic backup** of configuration files before changes
- **Standalone Windows .exe** — build once, share with users who don’t have Python

## Prerequisites

Before you begin, ensure you have met the following requirements:

- **Python 3.12 or higher** installed
- **uv package manager** (recommended) or pip
- **Sunshine** or **Apollo** installed and configured
- **(Optional)** A [SteamGridDB](https://www.steamgriddb.com/profile/preferences/api) API key for community thumbnail art; if omitted, thumbnails use Steam’s CDN with no signup

## Installation

### Recommended: Using uv (Fast and Modern)

1. **Install uv** if you haven't already:
   ```bash
   # Windows
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   
   # macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone this repository**:
   ```bash
   git clone https://github.com/trevlars/Gamesphere-Import-Tool.git
   cd Gamesphere-Import-Tool
   ```

3. **Install dependencies using uv**:
   ```bash
   uv sync
   ```

### Alternative: Using pip

1. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Windows GUI

On Windows you can use the **Gamesphere Import Tool** GUI instead of the command line:

1. Install dependencies (including `customtkinter`):  
   `pip install -r requirements.txt` or `uv sync`
2. Run the GUI:  
   `python gui.py` or `uv run gui.py`
3. Choose **Sunshine** or **Apollo** as the streaming host (default paths update automatically).
4. Fill in the paths (SteamGridDB API key is optional — leave blank to use Steam CDN thumbnails); use **Browse** to pick files/folders.
5. Use **Save config** to write a `.env` file, then **Run importer** to run the automation. **Remove all games** wipes all apps from the host (fresh `apps.json`), including manually added ones. Log output appears in the window.

The GUI uses the same `.env` as the CLI, so you can switch between GUI and command line.

### Standalone Windows .exe

You can build a single **.exe** so others can run the tool without installing Python:

1. **On a Windows machine**, install the build optional dependency:
   ```bash
   uv sync --optional build
   # or: pip install pyinstaller
   ```
2. Build the executable:
   ```bash
   uv run build_exe.py
   # or: pyinstaller GamesphereImportTool.spec
   ```
3. The executable is created at `dist/GamesphereImportTool.exe`. Copy it (and optionally a `.env` or `.env.example`) to share.
4. **End users:** Put the `.exe` in a folder, run it, set paths in the GUI (API key optional), save config, then click **Run importer**. No Python installation required.

## Configuration

The script now uses environment variables for configuration. Create a `.env` file in the project directory:

```env
# Required variables
STEAM_LIBRARY_VDF_PATH=C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf
SUNSHINE_APPS_JSON_PATH=C:/Program Files/Sunshine/config/apps.json
SUNSHINE_GRIDS_FOLDER=C:/Sunshine_Thumbnails

# Optional: SteamGridDB API key for community thumbnail art; leave empty to use Steam CDN (no signup)
STEAMGRIDDB_API_KEY=

# Optional variables (for Windows process restart)
STEAM_EXE_PATH=C:/Program Files (x86)/Steam/steam.exe
SUNSHINE_EXE_PATH=C:/Program Files/Sunshine/sunshine.exe
```

### Path Examples by Platform:

**Windows:**
- Steam Library: `C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf`
- Sunshine Apps: `C:/Program Files/Sunshine/config/apps.json`
- Thumbnails folder: `C:/Sunshine_Thumbnails`

**Linux:**
- Steam Library: `/home/username/.local/share/Steam/steamapps/libraryfolders.vdf`
- Sunshine Apps: `/home/username/.config/sunshine/apps.json`
- Thumbnails folder: `/home/username/.config/sunshine/grids`

**macOS:**
- Steam Library: `/Users/username/Library/Application Support/Steam/steamapps/libraryfolders.vdf`
- Sunshine Apps: `/Users/username/.config/sunshine/apps.json`
- Thumbnails folder: `/Users/username/.config/sunshine/grids`

## Usage

### Basic Usage

```bash
# Using uv (recommended)
uv run main.py

# Using python directly
python main.py
```

### Command-line Options

```bash
# Verbose logging for debugging
uv run main.py --verbose

# Preview changes without making them
uv run main.py --dry-run

# Remove ALL apps from host config (fresh apps.json, including manually added apps)
uv run main.py --remove-games

# Skip starting Steam (if not running) and skip restarting the streaming host
uv run main.py --no-restart

# Combine options
uv run main.py --verbose --dry-run
```

### What the script does:

1. **Validates configuration** and checks all required paths
2. **Loads Steam library** and discovers installed games (concurrent processing)
3. **Downloads thumbnail images** from Steam CDN (or SteamGridDB if API key is set)
4. **Updates Sunshine/Apollo configuration** with new games and removes uninstalled ones
5. **Creates backups** of your configuration before making changes
6. **Provides detailed logging** of all operations

## Troubleshooting

### Common Issues

- **"Invalid argument" errors**: Check your `.env` file paths use forward slashes `/` or double backslashes `\\`
- **"Access Denied" / "Permission denied" when saving config**: If Apollo or Sunshine is installed under `C:\Program Files`, the tool must write to that folder. Right-click the app (or shortcut) and choose **Run as administrator**, then run the importer again. Backups are saved to your user folder if the config directory is not writable.
- **API rate limiting**: The script includes automatic retry logic with backoff
- **Missing games**: Some games may not have data available in Steam's API

### Log Files

The script creates detailed logs in `sunshine_automation.log`. Use `--verbose` for more detailed output.

### Environment Variable Issues

If you're having path issues, the script will now:
- Automatically normalize Windows paths
- Validate that required directories exist
- Give clear error messages about what's wrong

### Platform-Specific Notes

**Linux with Flatpak Steam:**
The script automatically detects Flatpak Steam installations and uses the correct command format.

**macOS:**
Steam paths may vary depending on installation method (Steam app vs manual install).

## Repository

**[github.com/trevlars/Gamesphere-Import-Tool](https://github.com/trevlars/Gamesphere-Import-Tool)**

## Contributing

Contributions to improve the script are welcome. Please feel free to submit a Pull Request.

## Changelog

### GameSphere Import Tool (this fork)
- Windows GUI (CustomTkinter) with config form and log output; GameSphere branding and red theme
- **Sunshine** and **Apollo** support with host selector and default paths
- **Remove all games** resets `apps.json` fully (all apps removed, including manually added)
- Host restart works for both Sunshine and Apollo
- Credit to [CommonMugger/Sunshine-App-Automation](https://github.com/CommonMugger/Sunshine-App-Automation) for the original Python automation

### v2.0 (upstream)
- Complete rewrite with improved architecture
- Environment variable configuration
- Concurrent processing, retry logic, cross-platform CLI

### v1.0 (original)
- Basic Steam game detection and SteamGridDB integration

## Acknowledgements

- **[CommonMugger/Sunshine-App-Automation](https://github.com/CommonMugger/Sunshine-App-Automation)** — original Python project this fork is based on. The core automation (Steam library parsing, Sunshine/Apollo config updates, thumbnail handling, and CLI) comes from that repo. Thank you to [CommonMugger](https://github.com/CommonMugger) for the original work.
- [Sunshine](https://github.com/LizardByte/Sunshine) and [Apollo](https://github.com/ClassicOldSong/Apollo) — game streaming hosts
- [Steam CDN](https://partner.steamgames.com/doc/store/assets/libraryassets) and optional [SteamGridDB](https://www.steamgriddb.com/) for thumbnail images
- [GameSphere](https://github.com/trevlars/GameSphere) — TV client that pairs with this importer; GUI styling and branding are inspired by it
- [uv](https://github.com/astral-sh/uv) for fast Python package management

---

## Legal disclaimer

<sub>*Fine print. This project is provided for convenience only. You are responsible for your own setup and any effects of using this software.*</sub>

**Use at your own risk.** This software is provided **“as is”** without warranty of any kind. The authors and contributors are not liable for any damage to your computer, operating system, games, game saves, Steam or Sunshine/Apollo configuration, or any other software or data arising from the use or misuse of this tool. Back up your configuration and important data before use. This project is not affiliated with, endorsed by, or supported by Valve (Steam), LizardByte (Sunshine), Apollo, SteamGridDB, or any other third-party product or service mentioned here. All trademarks are property of their respective owners.