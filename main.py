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
        'sunshine_grids_folder': 'Sunshine grids folder path',
        'steamgriddb_api_key': 'SteamGridDB API key'
    }
    
    config = {}
    missing_vars = []
    
    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        else:
            # Normalize paths for file/folder variables
            if 'PATH' in var or 'FOLDER' in var:
                value = normalize_path(value)
                logging.debug(f"Normalized {var}: {value}")
        config[var] = value
    
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


def restart_steam(steam_exe_path: str) -> None:
    """Restart Steam application safely."""
    if os.name != 'nt':
        logging.warning("Steam restarting is only supported on Windows. Please restart Steam manually if any game is missing.")
        return
    
    if not steam_exe_path or not os.path.exists(steam_exe_path):
        logging.warning("Steam executable path not configured or doesn't exist. Skipping Steam restart.")
        return
    
    logging.info("Restarting Steam...")
    try:
        # Terminate Steam processes
        terminated = False
        for proc in psutil.process_iter(['name', 'pid']):
            if proc.info['name'] and proc.info['name'].lower() == 'steam.exe':
                logging.debug(f"Terminating Steam process (PID: {proc.info['pid']})")
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                    terminated = True
                except psutil.TimeoutExpired:
                    logging.warning(f"Steam process (PID: {proc.info['pid']}) didn't terminate gracefully")
                    proc.kill()
        
        if terminated:
            time.sleep(3)  # Brief pause before restart
        
        # Start Steam
        logging.info(f"Starting Steam from: {steam_exe_path}")
        subprocess.Popen([steam_exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(10)  # Wait for Steam to start up
        logging.info("Steam restart completed")
        
    except Exception as e:
        logging.error(f"Error restarting Steam: {e}")

def restart_sunshine(sunshine_exe_path: str) -> None:
    """Restart Sunshine application safely."""
    if os.name != 'nt':
        logging.warning("Sunshine restarting is only supported on Windows. Please restart Sunshine manually.")
        return
    
    if not sunshine_exe_path or not os.path.exists(sunshine_exe_path):
        logging.warning("Sunshine executable path not configured or doesn't exist. Skipping Sunshine restart.")
        return
    
    logging.info("Restarting Sunshine...")
    try:
        # Terminate Sunshine processes
        terminated = False
        for proc in psutil.process_iter(['name', 'pid']):
            if proc.info['name'] and proc.info['name'].lower() == 'sunshine.exe':
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
        
        # Start Sunshine
        logging.info(f"Starting Sunshine from: {sunshine_exe_path}")
        subprocess.Popen([sunshine_exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info("Sunshine restart completed")
        
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
    try:
        # Create backup if file exists
        if os.path.exists(path):
            backup_path = f"{path}.backup"
            import shutil
            shutil.copy2(path, backup_path)
            logging.debug(f"Created backup: {backup_path}")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        # Write config
        with open(path, 'w', encoding='utf-8') as file:
            json.dump(config, file, indent=4, ensure_ascii=False)
        
        logging.info(f"Saved Sunshine config with {len(config.get('apps', []))} apps")
        
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
            future = executor.submit(fetch_grid_from_steamgriddb, app_id, api_key, grids_folder)
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

def main() -> None:
    """Main application function."""
    parser = argparse.ArgumentParser(description='Sunshine Steam Game Automation')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--no-restart', action='store_true', help='Skip restarting Steam and Sunshine')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)
    logging.info("Starting Sunshine Steam Game Automation")
    
    try:
        # Load and validate configuration
        config = validate_config()
        
        # Restart Steam before processing (unless disabled)
        if not args.no_restart:
            restart_steam(config['STEAM_EXE_PATH'])
        
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
