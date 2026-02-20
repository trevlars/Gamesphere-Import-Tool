import os
import json
import vdf
import requests
import glob
from PIL import Image
import io
import subprocess
import time
import psutil
import logging
import argparse
import sys
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin
from dotenv import load_dotenv

# Configuration and logging setup
def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('sunshine_automation.log')
        ]
    )

def normalize_path(path: str) -> str:
    """Normalize path and handle escape sequences properly."""
    if not path:
        return path
    
    # Handle raw string paths (common in Windows)
    # Replace double backslashes with single backslashes
    path = path.replace('\\\\', '\\')
    
    # Normalize the path
    path = os.path.normpath(path)
    
    # Expand environment variables and user home
    path = os.path.expandvars(path)
    path = os.path.expanduser(path)
    
    return path

def validate_config() -> Dict[str, str]:
    """Load and validate configuration from environment variables."""
    load_dotenv()
    
    required_vars = {
        'steam_library_vdf_path': 'Steam library VDF file path',
        'sunshine_apps_json_path': 'Sunshine apps.json file path',
        'sunshine_grids_folder': 'Sunshine thumbnails folder path',
    }
    # Optional: SteamGridDB API key; if missing, thumbnails use Steam CDN (no signup)
    optional_vars = {'steamgriddb_api_key': 'SteamGridDB API key'}

    config = {}
    missing_vars = []

    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        else:
            if 'PATH' in var or 'FOLDER' in var:
                value = normalize_path(value)
                logging.debug(f"Normalized {var}: {value}")
        config[var] = value or ''
        config[var.upper()] = value or ''

    for var, description in optional_vars.items():
        value = os.getenv(var) or ''
        config[var] = value
        config[var.upper()] = value
    
    # Optional variables with defaults
    steam_exe = os.getenv('STEAM_EXE_PATH', '')
    sunshine_exe = os.getenv('SUNSHINE_EXE_PATH', '')
    
    config['STEAM_EXE_PATH'] = normalize_path(steam_exe) if steam_exe else ''
    config['SUNSHINE_EXE_PATH'] = normalize_path(sunshine_exe) if sunshine_exe else ''
    
    if missing_vars:
        logging.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)
    
    # Validate paths exist
    if not os.path.exists(config['STEAM_LIBRARY_VDF_PATH']):
        logging.error(f"Steam library VDF file not found: {config['STEAM_LIBRARY_VDF_PATH']}")
        sys.exit(1)
    
    # Validate parent directories exist for output paths
    apps_dir = os.path.dirname(config['SUNSHINE_APPS_JSON_PATH'])
    if not os.path.exists(apps_dir):
        logging.error(f"Sunshine config directory not found: {apps_dir}")
        logging.info(f"Please ensure Sunshine is installed and has created its config directory")
        sys.exit(1)
    
    return config


def _is_steam_running() -> bool:
    """Return True if steam.exe is already running (Windows)."""
    if os.name != 'nt':
        return False
    try:
        for proc in psutil.process_iter(['name']):
            if proc.info.get('name') and proc.info['name'].lower() == 'steam.exe':
                return True
    except Exception:
        pass
    return False


def ensure_steam_running(steam_exe_path: str) -> None:
    """Start Steam only if it is not already running. Does not restart or close Steam."""
    if os.name != 'nt':
        logging.warning("Steam start is only supported on Windows. Ensure Steam is running if needed.")
        return

    if not steam_exe_path or not os.path.exists(steam_exe_path):
        logging.warning("Steam executable path not configured or doesn't exist. Skipping Steam start.")
        return

    if _is_steam_running():
        logging.info("Steam is already running. Skipping start.")
        return

    logging.info("Steam is not running. Starting Steam...")
    try:
        subprocess.Popen([steam_exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(5)  # Brief pause for Steam to begin starting
        logging.info("Steam start requested")
    except Exception as e:
        logging.error(f"Error starting Steam: {e}")

def restart_sunshine(sunshine_exe_path: str) -> None:
    """Restart Sunshine/Apollo (or other Sunshine-compatible host) safely."""
    if os.name != 'nt':
        logging.warning("Host restarting is only supported on Windows. Please restart manually.")
        return
    
    if not sunshine_exe_path or not os.path.exists(sunshine_exe_path):
        logging.warning("Host executable path not configured or doesn't exist. Skipping restart.")
        return
    
    # Derive process name from exe path so both Sunshine and Apollo work
    process_name = os.path.basename(sunshine_exe_path).lower()
    logging.info(f"Restarting host ({process_name})...")
    try:
        terminated = False
        for proc in psutil.process_iter(['name', 'pid']):
            if proc.info['name'] and proc.info['name'].lower() == process_name:
                logging.debug(f"Terminating Sunshine process (PID: {proc.info['pid']})")
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                    terminated = True
                except psutil.TimeoutExpired:
                    logging.warning(f"Sunshine process (PID: {proc.info['pid']}) didn't terminate gracefully")
                    proc.kill()
        
        if terminated:
            time.sleep(3)  # Brief pause before restart
        
        logging.info(f"Starting host from: {sunshine_exe_path}")
        subprocess.Popen([sunshine_exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info("Host restart completed")
        
    except Exception as e:
        logging.error(f"Error restarting Sunshine: {e}")

@lru_cache(maxsize=1000)
def get_game_name(app_id: str) -> Optional[str]:
    """Fetch game name from Steam API with caching and retry logic."""
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
    
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if str(app_id) in data and data[str(app_id)].get('success'):
                game_data = data[str(app_id)].get('data', {})
                name = game_data.get('name')
                if name:
                    logging.debug(f"Retrieved name for AppID {app_id}: {name}")
                    return name
            
            logging.warning(f"No valid data found for AppID {app_id}")
            return None
            
        except requests.exceptions.Timeout:
            logging.warning(f"Timeout fetching name for AppID {app_id} (attempt {attempt + 1}/3)")
        except requests.exceptions.RequestException as e:
            logging.warning(f"Request error for AppID {app_id} (attempt {attempt + 1}/3): {e}")
        except Exception as e:
            logging.error(f"Unexpected error fetching name for AppID {app_id}: {e}")
            return None
        
        if attempt < 2:  # Don't sleep on last attempt
            time.sleep(2 ** attempt)  # Exponential backoff
    
    logging.error(f"Failed to fetch name for AppID {app_id} after 3 attempts")
    return None

def fetch_grid_from_steamgriddb(app_id: str, api_key: str, grids_folder: str) -> Optional[str]:
    """Fetch game grid image from SteamGridDB with retry logic."""
    url = f"https://www.steamgriddb.com/api/v2/grids/steam/{app_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if "data" in data and len(data["data"]) > 0:
                grid_url = data["data"][0]["url"]
                grid_response = requests.get(grid_url, timeout=30)
                grid_response.raise_for_status()
                
                # Validate image data
                try:
                    image = Image.open(io.BytesIO(grid_response.content))
                    image.verify()  # Verify it's a valid image
                    
                    # Reopen for saving (verify() closes the image)
                    image = Image.open(io.BytesIO(grid_response.content))
                    grid_path = os.path.join(grids_folder, f"{app_id}.png")
                    
                    # Ensure directory exists
                    os.makedirs(grids_folder, exist_ok=True)
                    
                    image.save(grid_path, "PNG")
                    logging.debug(f"Downloaded grid for AppID {app_id}: {grid_path}")
                    return grid_path
                    
                except Exception as img_error:
                    logging.warning(f"Invalid image data for AppID {app_id}: {img_error}")
                    return None
            else:
                logging.warning(f"No grid data found for AppID {app_id}")
                return None
                
        except requests.exceptions.Timeout:
            logging.warning(f"Timeout fetching grid for AppID {app_id} (attempt {attempt + 1}/3)")
        except requests.exceptions.RequestException as e:
            logging.warning(f"Request error for AppID {app_id} (attempt {attempt + 1}/3): {e}")
        except Exception as e:
            logging.error(f"Unexpected error fetching grid for AppID {app_id}: {e}")
            return None
        
        if attempt < 2:  # Don't sleep on last attempt
            time.sleep(2 ** attempt)  # Exponential backoff
    
    logging.error(f"Failed to fetch grid for AppID {app_id} after 3 attempts")
    return None


# Steam CDN URLs (no API key, no signup) — box art (library cover) first, then header fallback
STEAM_CDN_LIBRARY_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900_2x.jpg"  # box art 1200x1800
STEAM_CDN_LIBRARY_FALLBACK_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg"  # 600x900
STEAM_CDN_HEADER_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"  # wide tile fallback


def _download_steam_cdn_image(url: str, app_id: str, grids_folder: str) -> Optional[str]:
    """Download image from URL to grids_folder; return path or None."""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        if len(response.content) < 500:
            return None
        image = Image.open(io.BytesIO(response.content))
        image.verify()
        image = Image.open(io.BytesIO(response.content))
        grid_path = os.path.join(grids_folder, f"{app_id}.png")
        os.makedirs(grids_folder, exist_ok=True)
        image.save(grid_path, "PNG")
        logging.debug(f"Downloaded image from Steam CDN for AppID {app_id}: {grid_path}")
        return grid_path
    except Exception:
        return None


def fetch_grid_from_steam_cdn(app_id: str, grids_folder: str) -> Optional[str]:
    """Fetch box-art (library cover) image from Steam's public CDN. No API key or signup required."""
    for url_template in (STEAM_CDN_LIBRARY_URL, STEAM_CDN_LIBRARY_FALLBACK_URL, STEAM_CDN_HEADER_URL):
        url = url_template.format(app_id=app_id)
        path = _download_steam_cdn_image(url, app_id, grids_folder)
        if path:
            return path
    logging.warning(f"No Steam CDN image found for AppID {app_id}")
    return None


def fetch_grid(app_id: str, api_key: str, grids_folder: str) -> Optional[str]:
    """Fetch grid image: SteamGridDB if API key set (with Steam CDN fallback), else Steam CDN only."""
    if api_key and api_key.strip():
        path = fetch_grid_from_steamgriddb(app_id, api_key.strip(), grids_folder)
        if path:
            return path
        logging.debug(f"SteamGridDB failed for {app_id}, trying Steam CDN")
    return fetch_grid_from_steam_cdn(app_id, grids_folder)


def get_sunshine_config(path: str) -> Dict:
    """Load Sunshine configuration with error handling."""
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as file:
                config = json.load(file)
            
            # Validate config structure
            if not isinstance(config, dict):
                raise ValueError("Config must be a dictionary")
            
            if 'apps' not in config:
                config['apps'] = []
            
            if 'env' not in config:
                config['env'] = ""
            
            logging.info(f"Loaded Sunshine config with {len(config['apps'])} apps")
            return config
        else:
            config = {"env": "", "apps": []}
            logging.info("Sunshine config not found, initializing empty config")
            return config
            
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in Sunshine config file: {e}")
        raise
    except Exception as e:
        logging.error(f"Error loading Sunshine config: {e}")
        raise

def save_sunshine_config(path: str, config: Dict) -> None:
    """Save Sunshine configuration with backup and error handling."""
    import shutil
    backup_path = f"{path}.backup"
    config_dir = os.path.dirname(path)

    try:
        # Create backup if file exists (use fallback dir if Program Files is read-only)
        if os.path.exists(path):
            try:
                shutil.copy2(path, backup_path)
                logging.debug(f"Created backup: {backup_path}")
            except OSError as e:
                if e.errno == 13:  # Permission denied
                    fallback = os.path.join(os.path.expanduser("~"), "GamesphereImportTool_backups")
                    os.makedirs(fallback, exist_ok=True)
                    backup_name = os.path.basename(path) + ".backup"
                    backup_path = os.path.join(fallback, backup_name)
                    shutil.copy2(path, backup_path)
                    logging.info(f"Backup saved to user folder (no write access to config dir): {backup_path}")
                else:
                    raise

        # Ensure directory exists
        try:
            os.makedirs(config_dir, exist_ok=True)
        except OSError as e:
            if e.errno == 13:
                raise PermissionError(
                    "Cannot write to the config directory (e.g. Program Files). "
                    "Run this tool as Administrator: right-click the app and choose 'Run as administrator'."
                ) from e
            raise

        # Write config
        try:
            with open(path, 'w', encoding='utf-8') as file:
                json.dump(config, file, indent=4, ensure_ascii=False)
        except OSError as e:
            if e.errno == 13:
                raise PermissionError(
                    "Cannot write to the config directory (e.g. Program Files). "
                    "Run this tool as Administrator: right-click the app and choose 'Run as administrator'."
                ) from e
            raise

        logging.info(f"Saved Sunshine config with {len(config.get('apps', []))} apps")

    except PermissionError:
        raise
    except Exception as e:
        logging.error(f"Error saving Sunshine config: {e}")
        raise

def load_installed_games(library_vdf_path: str) -> Dict[str, str]:
    """Load installed games from Steam library VDF file."""
    logging.info(f"Loading Steam library from {library_vdf_path}")
    
    try:
        with open(library_vdf_path, 'r', encoding='utf-8') as file:
            steam_data = vdf.load(file)
    except Exception as e:
        logging.error(f"Error loading Steam library VDF: {e}")
        raise
    
    logging.debug("Raw Steam library data loaded successfully")
    
    installed_games = {}
    total_apps = 0
    
    # Count total apps for progress tracking
    for folder_data in steam_data.get('libraryfolders', {}).values():
        if "apps" in folder_data:
            total_apps += len(folder_data["apps"])
    
    logging.info(f"Processing {total_apps} Steam apps...")
    
    # Use thread pool for concurrent API calls
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_app_id = {}
        
        for folder_data in steam_data.get('libraryfolders', {}).values():
            if "apps" in folder_data:
                for app_id in folder_data["apps"].keys():
                    future = executor.submit(get_game_name, app_id)
                    future_to_app_id[future] = app_id
        
        processed = 0
        for future in as_completed(future_to_app_id):
            app_id = future_to_app_id[future]
            processed += 1
            
            try:
                game_name = future.result()
                if game_name:
                    installed_games[app_id] = game_name
                    logging.debug(f"Found game: {game_name} (ID: {app_id})")
            except Exception as e:
                logging.warning(f"Error processing AppID {app_id}: {e}")
            
            if processed % 50 == 0 or processed == total_apps:
                logging.info(f"Processed {processed}/{total_apps} apps...")
    
    logging.info(f"Found {len(installed_games)} installed games")
    return installed_games

def process_existing_apps(sunshine_config: Dict, installed_games: Dict[str, str]) -> Tuple[List[Dict], List[Tuple[str, str]], Set[str]]:
    """Process existing Sunshine apps and identify changes."""
    updated_apps = []
    removed_games = []
    existing_steam_apps = set()
    
    for app in sunshine_config.get('apps', []):
        if 'cmd' in app and app['cmd'].startswith('steam://rungameid/'):
            app_id = app['cmd'].split('/')[-1]
            if app_id in installed_games:
                updated_apps.append(app)
                existing_steam_apps.add(app_id)
            else:
                removed_games.append((app.get('name', 'Unknown'), app_id))
                # Clean up grid image
                grid_path = app.get('image-path')
                if grid_path and os.path.exists(grid_path):
                    try:
                        os.remove(grid_path)
                        logging.debug(f"Removed grid image: {grid_path}")
                    except Exception as e:
                        logging.warning(f"Failed to remove grid image {grid_path}: {e}")
        else:
            # Keep non-Steam apps
            updated_apps.append(app)
    
    return updated_apps, removed_games, existing_steam_apps

def add_new_games(new_games: Set[str], installed_games: Dict[str, str], api_key: str, grids_folder: str) -> List[Dict]:
    """Add new games with grid images using concurrent downloads."""
    new_apps = []
    
    if not new_games:
        return new_apps
    
    logging.info(f"Adding {len(new_games)} new games...")
    
    # Download grids concurrently
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_app_id = {}
        
        for app_id in new_games:
            future = executor.submit(fetch_grid, app_id, api_key or '', grids_folder)
            future_to_app_id[future] = app_id
        
        processed = 0
        for future in as_completed(future_to_app_id):
            app_id = future_to_app_id[future]
            processed += 1
            
            try:
                grid_path = future.result()
                game_name = installed_games[app_id]
                
                # Determine command based on platform
                if os.name == 'nt':
                    cmd = f"steam://rungameid/{app_id}"
                else:
                    # Check for Flatpak Steam
                    flatpak_steam = subprocess.run(
                        ['flatpak', 'list', '--app', '--columns=application'], 
                        capture_output=True, text=True
                    ).stdout
                    
                    if 'com.valvesoftware.Steam' in flatpak_steam:
                        cmd = f"flatpak run com.valvesoftware.Steam steam://rungameid/{app_id}"
                    else:
                        cmd = f"steam steam://rungameid/{app_id}"
                
                new_app = {
                    "name": game_name,
                    "cmd": cmd,
                    "output": "",
                    "detached": "",
                    "elevated": "false",
                    "hidden": "true",
                    "wait-all": "true",
                    "exit-timeout": "5",
                    "image-path": grid_path or ""
                }
                new_apps.append(new_app)
                logging.info(f"Added: {game_name}")
                
            except Exception as e:
                logging.error(f"Error processing new game {app_id}: {e}")
            
            if processed % 10 == 0 or processed == len(new_games):
                logging.info(f"Processed {processed}/{len(new_games)} new games...")
    
    return new_apps


def remove_all_apps_from_config(apps_json_path: str, grids_folder: str) -> int:
    """
    Remove ALL apps from Sunshine/Apollo config (including manually added ones).
    Writes a fresh apps.json with empty apps array and removes thumbnail files in the grids folder.
    Returns the number of apps that were removed.
    """
    config = get_sunshine_config(apps_json_path)
    apps = config.get('apps', [])
    removed_count = len(apps)

    # Delete thumbnail images referenced by any app
    for app in apps:
        grid_path = app.get('image-path')
        if grid_path and os.path.exists(grid_path):
            try:
                os.remove(grid_path)
                logging.debug(f"Removed thumbnail: {grid_path}")
            except Exception as e:
                logging.warning(f"Failed to remove thumbnail {grid_path}: {e}")

    # Remove any other PNGs in the grids folder (e.g. orphaned or from manual adds)
    if os.path.isdir(grids_folder):
        try:
            for name in os.listdir(grids_folder):
                if name.lower().endswith('.png'):
                    path = os.path.join(grids_folder, name)
                    try:
                        os.remove(path)
                        logging.debug(f"Removed grid image: {path}")
                    except Exception as e:
                        logging.warning(f"Failed to remove {path}: {e}")
        except OSError as e:
            logging.warning(f"Could not list grids folder {grids_folder}: {e}")

    # Fresh config: keep top-level keys like 'env', empty apps
    config['apps'] = []
    save_sunshine_config(apps_json_path, config)
    logging.info(f"Removed all {removed_count} app(s). apps.json is now fresh (empty apps).")
    return removed_count


def main() -> None:
    """Main application function."""
    parser = argparse.ArgumentParser(description='Sunshine Steam Game Automation')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--no-restart', action='store_true', help='Skip starting Steam (if not running) and skip restarting Sunshine/Apollo')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--remove-games', action='store_true', help='Remove ALL apps from host config (fresh apps.json), including manually added ones')
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)
    logging.info("Starting Sunshine Steam Game Automation")
    
    try:
        # Load and validate configuration
        config = validate_config()
        
        if args.remove_games:
            host_name = os.getenv("HOST", "sunshine").strip()
            if host_name.lower() not in ("sunshine", "apollo"):
                host_name = "sunshine"
            host_name = host_name.capitalize()
            logging.info(f"Removing all Steam games from {host_name}")
            removed = remove_all_apps_from_config(
                config['SUNSHINE_APPS_JSON_PATH'],
                config['SUNSHINE_GRIDS_FOLDER'],
            )
            if not args.no_restart:
                restart_sunshine(config['SUNSHINE_EXE_PATH'])
            logging.info("Remove-games completed successfully")
            return
        # ----- normal import flow below -----
        
        # Start Steam only if not already running (unless disabled)
        if not args.no_restart:
            ensure_steam_running(config['STEAM_EXE_PATH'])
        
        # Load installed games
        installed_games = load_installed_games(config['STEAM_LIBRARY_VDF_PATH'])
        
        # Load Sunshine configuration
        sunshine_config = get_sunshine_config(config['SUNSHINE_APPS_JSON_PATH'])
        
        # Ensure grids folder exists
        os.makedirs(config['SUNSHINE_GRIDS_FOLDER'], exist_ok=True)
        
        # Process existing apps
        updated_apps, removed_games, existing_steam_apps = process_existing_apps(sunshine_config, installed_games)
        
        # Find new games to add
        new_games = set(installed_games.keys()) - existing_steam_apps
        
        # Log changes
        if removed_games:
            logging.info(f"Games to remove: {[name for name, _ in removed_games]}")
        if new_games:
            logging.info(f"New games to add: {[installed_games[app_id] for app_id in new_games]}")
        
        if not removed_games and not new_games:
            logging.info("No changes needed - all games are up to date")
            return
        
        if args.dry_run:
            logging.info("Dry run mode - no changes will be made")
            return
        
        # Add new games
        new_apps = add_new_games(new_games, installed_games, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'])
        updated_apps.extend(new_apps)
        
        # Update and save configuration
        sunshine_config['apps'] = updated_apps
        save_sunshine_config(config['SUNSHINE_APPS_JSON_PATH'], sunshine_config)
        
        # Restart Sunshine after processing (unless disabled)
        if not args.no_restart:
            restart_sunshine(config['SUNSHINE_EXE_PATH'])
        
        logging.info("Sunshine apps.json update process completed successfully")
        
    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
