# Sunshine Steam Game Importer

This Python script automatically imports your INSTALLED Steam games into Sunshine, a game streaming server, complete with grid images for each game. 

Example: 
![IMG_0759](https://github.com/user-attachments/assets/365301a4-57d8-4b5e-a9d6-5ba4573af638)

## Features

- **Automatically detects installed Steam games** with concurrent processing for speed
- **Fetches game names and grid images** from SteamGridDB with retry logic
- **Updates Sunshine's apps.json** with Steam games and their grid images
- **Cross-platform support** for Windows, Linux, and macOS
- **Robust error handling** with comprehensive logging
- **Command-line options** for verbose output, dry runs, and more
- **Environment-based configuration** using .env files
- **Automatic backup** of configuration files before changes

## Prerequisites

Before you begin, ensure you have met the following requirements:

- **Python 3.12 or higher** installed
- **uv package manager** (recommended) or pip
- **Sunshine** installed and configured
- **A SteamGridDB API key** (get one from [SteamGridDB](https://www.steamgriddb.com/profile/preferences/api))

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
   git clone <repository-url>
   cd Sunshine-App-Automation
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

## Configuration

The script now uses environment variables for configuration. Create a `.env` file in the project directory:

```env
# Required variables
STEAM_LIBRARY_VDF_PATH=C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf
SUNSHINE_APPS_JSON_PATH=C:/Program Files/Sunshine/config/apps.json
SUNSHINE_GRIDS_FOLDER=C:/Sunshine_Grids
STEAMGRIDDB_API_KEY=your_api_key_here

# Optional variables (for Windows process restart)
STEAM_EXE_PATH=C:/Program Files (x86)/Steam/steam.exe
SUNSHINE_EXE_PATH=C:/Program Files/Sunshine/sunshine.exe
```

### Path Examples by Platform:

**Windows:**
- Steam Library: `C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf`
- Sunshine Apps: `C:/Program Files/Sunshine/config/apps.json`
- Grids Folder: `C:/Sunshine_Grids`

**Linux:**
- Steam Library: `/home/username/.local/share/Steam/steamapps/libraryfolders.vdf`
- Sunshine Apps: `/home/username/.config/sunshine/apps.json`
- Grids Folder: `/home/username/.config/sunshine/grids`

**macOS:**
- Steam Library: `/Users/username/Library/Application Support/Steam/steamapps/libraryfolders.vdf`
- Sunshine Apps: `/Users/username/.config/sunshine/apps.json`
- Grids Folder: `/Users/username/.config/sunshine/grids`

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

# Skip restarting Steam and Sunshine
uv run main.py --no-restart

# Combine options
uv run main.py --verbose --dry-run
```

### What the script does:

1. **Validates configuration** and checks all required paths
2. **Loads Steam library** and discovers installed games (concurrent processing)
3. **Downloads grid images** from SteamGridDB (with retry logic)
4. **Updates Sunshine configuration** with new games and removes uninstalled ones
5. **Creates backups** of your configuration before making changes
6. **Provides detailed logging** of all operations

## Troubleshooting

### Common Issues

- **"Invalid argument" errors**: Check your `.env` file paths use forward slashes `/` or double backslashes `\\`
- **"Access Denied" errors**: Run with administrator privileges on Windows
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

## Contributing

Contributions to improve the script are welcome. Please feel free to submit a Pull Request.

## Changelog

### v2.0 (Latest)
- Complete rewrite with improved architecture
- Environment variable configuration
- Concurrent processing for 10x speed improvement
- Robust error handling and retry logic
- Cross-platform support improvements
- Command-line interface with options
- Automatic backup creation
- Comprehensive logging

### v1.0 (Original)
- Basic Steam game detection
- Simple SteamGridDB integration
- Windows-focused implementation

## Acknowledgements

- [Sunshine](https://github.com/LizardByte/Sunshine) for the game streaming server
- [SteamGridDB](https://www.steamgriddb.com/) for providing the grid images
- [uv](https://github.com/astral-sh/uv) for fast Python package management