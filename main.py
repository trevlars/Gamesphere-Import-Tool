import os
import json
import xml.etree.ElementTree as ET
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
    
    # Optional: Epic Games Store manifests path (Windows); empty = skip Epic
    epic_manifests = os.getenv('EPIC_MANIFESTS_PATH', '')
    if not epic_manifests and os.name == 'nt':
        epic_manifests = os.path.join(os.getenv('ProgramData', 'C:\\ProgramData'), 'Epic', 'EpicGamesLauncher', 'Data', 'Manifests')
    config['EPIC_MANIFESTS_PATH'] = normalize_path(epic_manifests) if epic_manifests else ''
    # Optional: custom games JSON path (name + cmd + optional image per game)
    custom_games_path = os.getenv('CUSTOM_GAMES_JSON_PATH', '')
    config['CUSTOM_GAMES_JSON_PATH'] = normalize_path(custom_games_path) if custom_games_path else ''
    # Optional: Xbox/Windows games root folder(s), comma-separated (e.g. C:\XboxGames,D:\XboxGames)
    xbox_folders = os.getenv('XBOX_GAMES_FOLDERS', '')
    if not xbox_folders and os.name == 'nt':
        xbox_folders = 'C:\\XboxGames'
    config['XBOX_GAMES_FOLDERS'] = xbox_folders.strip()
    # Optional: folder for auto-generated .lnk shortcuts (Windows); if set, Epic/Xbox/custom use shortcuts and Sunshine runs those
    shortcuts_folder = os.getenv('SUNSHINE_SHORTCUTS_FOLDER', '')
    config['SUNSHINE_SHORTCUTS_FOLDER'] = normalize_path(shortcuts_folder) if shortcuts_folder else ''

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


def _steamgriddb_search_steam_id(game_name: str, api_key: str) -> Optional[str]:
    """Search SteamGridDB by game name; return first result's Steam app ID if any."""
    if not api_key or not api_key.strip():
        return None
    url = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{requests.utils.quote(game_name)}"
    headers = {"Authorization": f"Bearer {api_key.strip()}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("success") and data.get("data"):
            first = data["data"][0]
            # API returns objects with "id" (SteamGridDB id) or "steam_app_id"
            steam_id = first.get("steam_app_id") or first.get("id")
            if steam_id is not None:
                return str(steam_id)
    except Exception as e:
        logging.debug(f"SteamGridDB search for '{game_name}': {e}")
    return None


def fetch_grid_by_name(game_name: str, api_key: str, grids_folder: str, file_safe_id: str) -> Optional[str]:
    """Fetch grid for a non-Steam game by name (SteamGridDB search then Steam grid). Returns path or None."""
    steam_id = _steamgriddb_search_steam_id(game_name, api_key)
    if steam_id:
        path = fetch_grid_from_steamgriddb(steam_id, api_key.strip(), grids_folder)
        if path:
            # Save under file_safe_id so we don't overwrite Steam grids
            dest = os.path.join(grids_folder, f"{file_safe_id}.png")
            if dest != path and os.path.exists(path):
                try:
                    import shutil
                    shutil.move(path, dest)
                    return dest
                except Exception:
                    return path
            return path
        path = fetch_grid_from_steam_cdn(steam_id, grids_folder)
        if path:
            dest = os.path.join(grids_folder, f"{file_safe_id}.png")
            if dest != path and os.path.exists(path):
                try:
                    import shutil
                    shutil.move(path, dest)
                    return dest
                except Exception:
                    return path
            return path
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


def _create_shortcut_win(shortcut_path: str, target: str, work_dir: Optional[str] = None) -> bool:
    """Create a Windows .lnk shortcut. target can be an exe path or a protocol URL. Returns True on success."""
    if os.name != 'nt':
        return False
    try:
        shortcut_path = os.path.normpath(shortcut_path)
        if not shortcut_path.lower().endswith('.lnk'):
            shortcut_path += '.lnk'
        if not work_dir and target and os.path.sep in target and not target.startswith('com.'):
            work_dir = os.path.dirname(target)
        work_dir = work_dir or ''
        env = os.environ.copy()
        env['SHORTCUT_PATH'] = shortcut_path
        env['TARGET_PATH'] = target
        env['WORK_DIR'] = work_dir
        script = (
            '$s = New-Object -ComObject WScript.Shell; '
            '$l = $s.CreateShortcut($env:SHORTCUT_PATH); '
            '$l.TargetPath = $env:TARGET_PATH; '
            'if ($env:WORK_DIR) { $l.WorkingDirectory = $env:WORK_DIR }; '
            '$l.Save(); [System.Runtime.Interopservices.Marshal]::ReleaseComObject($s) | Out-Null'
        )
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            env=env, capture_output=True, timeout=10, check=True
        )
        logging.debug(f"Created shortcut: {shortcut_path}")
        return True
    except Exception as e:
        logging.warning(f"Failed to create shortcut {shortcut_path}: {e}")
        return False


def _read_shortcut_target_win(shortcut_path: str) -> Optional[str]:
    """Read the target path/URL of a Windows .lnk file. Returns None on failure."""
    if os.name != 'nt' or not os.path.isfile(shortcut_path):
        return None
    try:
        env = os.environ.copy()
        env['LNK_PATH'] = shortcut_path
        out = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
             '$s = New-Object -ComObject WScript.Shell; $s.CreateShortcut($env:LNK_PATH).TargetPath'],
            env=env, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _shortcut_launch_cmd(shortcut_path: str) -> str:
    """Return the command to run a .lnk so the shell resolves it (Windows). Sunshine may need this."""
    path_norm = os.path.normpath(shortcut_path)
    return f'cmd /c start "" "{path_norm}"'


def _extract_shortcut_path_from_cmd(cmd: str) -> Optional[str]:
    """If cmd is or contains a path to a .lnk file, return that path (normalized). Otherwise None."""
    c = (cmd or '').strip()
    # cmd /c start "" "C:\path\to\file.lnk"
    if 'start "" "' in c and '.lnk' in c:
        try:
            i = c.index('start "" "') + len('start "" "')  # opening " of path
            j = c.index('"', i + 1)
            path = c[i + 1:j]
            if path.lower().endswith('.lnk'):
                return os.path.normpath(path)
        except ValueError:
            pass
    if c.lower().endswith('.lnk') and os.path.sep in c:
        return os.path.normpath(c)
    return None


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


def load_installed_epic_games(manifests_path: str) -> Dict[str, Dict]:
    """
    Load installed Epic Games Store games from .item manifest files.
    Returns dict keyed by AppName: { "name": DisplayName, "exe_path": full path to exe, "app_name": AppName }.
    """
    if not manifests_path or not os.path.isdir(manifests_path):
        logging.debug("Epic manifests path not set or not a directory, skipping Epic")
        return {}
    installed = {}
    for path in glob.glob(os.path.join(manifests_path, "*.item")):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            app_name = data.get("AppName")
            display_name = data.get("DisplayName") or app_name or "Unknown"
            install_location = data.get("InstallLocation", "")
            launch_exe = data.get("LaunchExecutable", "")
            if not app_name:
                continue
            exe_path = ""
            if install_location and launch_exe:
                exe_path = os.path.join(install_location, launch_exe)
                if not os.path.isfile(exe_path):
                    exe_path = ""
            installed[app_name] = {
                "name": display_name,
                "exe_path": exe_path,
                "app_name": app_name,
            }
        except Exception as e:
            logging.debug(f"Skip Epic manifest {path}: {e}")
    logging.info(f"Found {len(installed)} installed Epic games")
    return installed


def load_custom_games(json_path: str) -> List[Dict]:
    """
    Load custom game entries from a JSON file.
    Expected format: { "games": [ { "name": "...", "cmd": "path or command", "image_path": "" } ] }
    image_path optional; cmd required.
    """
    if not json_path or not os.path.isfile(json_path):
        return []
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        games = data.get("games") or data.get("custom_games") or []
        out = []
        for g in games:
            if isinstance(g, dict) and g.get("cmd"):
                out.append({
                    "name": (g.get("name") or "").strip() or "Custom Game",
                    "cmd": g["cmd"].strip(),
                    "image_path": (g.get("image_path") or "").strip(),
                })
        logging.info(f"Loaded {len(out)} custom game(s) from {json_path}")
        return out
    except Exception as e:
        logging.warning(f"Could not load custom games from {json_path}: {e}")
        return []


def _parse_microsoft_game_config(config_path: str, game_root: str) -> Optional[Tuple[str, str]]:
    """Parse MicrosoftGame.config; return (display_name, exe_filename) or None. exe_filename is just the name, not path."""
    try:
        tree = ET.parse(config_path)
        root = tree.getroot()
        ns = {}  # no namespace in these configs usually
        display_name = None
        exe_name = None
        # ShellVisuals DefaultDisplayName or Identity Name
        for tag in ("ShellVisuals", "Identity"):
            el = root.find(tag)
            if el is not None:
                display_name = el.get("DefaultDisplayName") or el.get("Name")
                if display_name:
                    break
        if not display_name:
            display_name = os.path.basename(game_root.rstrip(os.sep))
        # First Executable in ExecutableList (skip IsDevOnly if we can)
        exec_list = root.find("ExecutableList")
        if exec_list is not None:
            for exe_el in exec_list.findall("Executable"):
                if exe_el.get("IsDevOnly", "false").lower() == "true":
                    continue
                exe_name = exe_el.get("Name")
                if exe_name:
                    break
        if display_name and exe_name:
            return (display_name.strip(), exe_name.strip())
    except Exception as e:
        logging.debug(f"Parse MicrosoftGame.config {config_path}: {e}")
    return None


def load_installed_xbox_games(folders_str: str) -> Dict[str, Dict]:
    """
    Discover Xbox/Windows Store (Game Pass) games from usual install folders (e.g. C:\\XboxGames).
    folders_str: comma-separated list of root paths.
    Returns dict keyed by normalized exe path: { "name": display name, "cmd": full exe path }.
    """
    if not folders_str or os.name != 'nt':
        return {}
    roots = [normalize_path(p.strip()) for p in folders_str.split(",") if p.strip()]
    installed = {}
    for root_dir in roots:
        if not os.path.isdir(root_dir):
            logging.debug(f"Xbox games root not found: {root_dir}")
            continue
        for entry in os.listdir(root_dir):
            game_dir = os.path.join(root_dir, entry)
            if not os.path.isdir(game_dir):
                continue
            config_path = os.path.join(game_dir, "MicrosoftGame.config")
            display_name = None
            exe_name = None
            if os.path.isfile(config_path):
                parsed = _parse_microsoft_game_config(config_path, game_dir)
                if parsed:
                    display_name, exe_name = parsed
            if not exe_name:
                # Fallback: find first .exe in the game root (not in subfolders)
                for f in os.listdir(game_dir):
                    if f.lower().endswith(".exe") and not f.lower().startswith("uninstall"):
                        exe_name = f
                        if not display_name:
                            display_name = os.path.splitext(f)[0].replace("_", " ").replace("-", " ")
                        break
            if not display_name:
                display_name = entry
            if not exe_name:
                continue
            exe_path = os.path.join(game_dir, exe_name)
            if not os.path.isfile(exe_path):
                continue
            exe_path_norm = os.path.normpath(exe_path)
            installed[exe_path_norm] = {"name": display_name, "cmd": exe_path_norm}
    logging.info(f"Found {len(installed)} Xbox/Windows games")
    return installed


def process_existing_apps(
    sunshine_config: Dict,
    installed_games: Dict[str, str],
    installed_epic: Optional[Dict[str, Dict]] = None,
    custom_cmds: Optional[Set[str]] = None,
    installed_xbox: Optional[Dict[str, Dict]] = None,
    shortcuts_folder: Optional[str] = None,
) -> Tuple[List[Dict], List[Tuple[str, str]], List[Tuple[str, str]], Set[str], Set[str], Set[str]]:
    """Process existing Sunshine apps and identify changes. Returns (updated_apps, removed_steam, removed_epic, existing_steam_ids, existing_epic_ids, existing_xbox_cmds)."""
    updated_apps = []
    removed_steam = []
    removed_epic: List[Tuple[str, str]] = []
    existing_steam_apps: Set[str] = set()
    existing_epic_apps: Set[str] = set()
    existing_xbox_cmds: Set[str] = set()
    installed_epic = installed_epic or {}
    custom_cmds = custom_cmds or set()
    installed_xbox = installed_xbox or {}
    shortcuts_folder_norm = os.path.normpath(shortcuts_folder) if shortcuts_folder else ""

    def _delete_shortcut_if_in_folder(shortcut_path: Optional[str]) -> None:
        if not shortcut_path or not shortcuts_folder_norm:
            return
        p = os.path.normpath(shortcut_path)
        if p.startswith(shortcuts_folder_norm) and os.path.isfile(p):
            try:
                os.remove(p)
                logging.debug(f"Removed shortcut: {p}")
            except Exception as e:
                logging.warning(f"Failed to remove shortcut {p}: {e}")

    for app in sunshine_config.get('apps', []):
        cmd = (app.get('cmd') or '').strip()
        cmd_norm = os.path.normpath(cmd) if os.path.sep in cmd else cmd
        shortcut_path = _extract_shortcut_path_from_cmd(cmd) if shortcuts_folder_norm else None
        if shortcut_path and shortcuts_folder_norm and shortcut_path.startswith(shortcuts_folder_norm):
            target = _read_shortcut_target_win(shortcut_path)
            if target and 'com.epicgames.launcher://' in target:
                try:
                    prefix = "com.epicgames.launcher://apps/"
                    idx = target.find(prefix)
                    if idx != -1:
                        app_name = target[idx + len(prefix):].split('?')[0].split('/')[0].strip()
                        if app_name in installed_epic:
                            updated_apps.append(app)
                            existing_epic_apps.add(app_name)
                        else:
                            removed_epic.append((app.get('name', 'Unknown'), app_name))
                            _delete_shortcut_if_in_folder(shortcut_path)
                            grid_path = app.get('image-path')
                            if grid_path and os.path.exists(grid_path):
                                try:
                                    os.remove(grid_path)
                                    logging.debug(f"Removed grid image: {grid_path}")
                                except Exception as e:
                                    logging.warning(f"Failed to remove grid image {grid_path}: {e}")
                    else:
                        updated_apps.append(app)
                except Exception:
                    updated_apps.append(app)
            elif target and os.path.sep in target:
                target_norm = os.path.normpath(target)
                if target_norm in installed_xbox or target in installed_xbox:
                    updated_apps.append(app)
                    existing_xbox_cmds.add(target_norm if target_norm in installed_xbox else target)
                elif target in custom_cmds or target_norm in custom_cmds:
                    updated_apps.append(app)
                else:
                    updated_apps.append(app)
            else:
                updated_apps.append(app)
            continue
        if cmd.startswith('steam://rungameid/'):
            app_id = cmd.split('/')[-1].split('?')[0]
            if app_id in installed_games:
                updated_apps.append(app)
                existing_steam_apps.add(app_id)
            else:
                removed_steam.append((app.get('name', 'Unknown'), app_id))
                grid_path = app.get('image-path')
                if grid_path and os.path.exists(grid_path):
                    try:
                        os.remove(grid_path)
                        logging.debug(f"Removed grid image: {grid_path}")
                    except Exception as e:
                        logging.warning(f"Failed to remove grid image {grid_path}: {e}")
        elif 'com.epicgames.launcher://' in cmd:
            # Extract AppName: com.epicgames.launcher://apps/AppName?action=...
            try:
                prefix = "com.epicgames.launcher://apps/"
                idx = cmd.find(prefix)
                if idx != -1:
                    rest = cmd[idx + len(prefix):]
                    app_name = rest.split('?')[0].split('/')[0].strip()
                    if app_name in installed_epic:
                        updated_apps.append(app)
                        existing_epic_apps.add(app_name)
                    else:
                        removed_epic.append((app.get('name', 'Unknown'), app_name))
                        grid_path = app.get('image-path')
                        if grid_path and os.path.exists(grid_path):
                            try:
                                os.remove(grid_path)
                                logging.debug(f"Removed grid image: {grid_path}")
                            except Exception as e:
                                logging.warning(f"Failed to remove grid image {grid_path}: {e}")
                else:
                    updated_apps.append(app)
            except Exception:
                updated_apps.append(app)
        elif cmd_norm in installed_xbox:
            updated_apps.append(app)
            existing_xbox_cmds.add(cmd_norm)
        elif cmd in installed_xbox:
            updated_apps.append(app)
            existing_xbox_cmds.add(cmd)
        elif cmd in custom_cmds:
            updated_apps.append(app)
        else:
            updated_apps.append(app)

    return updated_apps, removed_steam, removed_epic, existing_steam_apps, existing_epic_apps, existing_xbox_cmds

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


def _epic_launch_cmd(app_name: str) -> str:
    """Build launch command for an Epic game (protocol; Epic Launcher must be installed)."""
    url = f"com.epicgames.launcher://apps/{app_name}?action=launch&silent=true"
    if os.name == 'nt':
        return f'start "" "{url}"'
    return url


def add_epic_games(
    new_epic_ids: Set[str],
    installed_epic: Dict[str, Dict],
    api_key: str,
    grids_folder: str,
    shortcuts_folder: Optional[str] = None,
) -> List[Dict]:
    """Add new Epic Games Store games with grid images (by name search). If shortcuts_folder set (Windows), create .lnk and use that as cmd."""
    new_apps = []
    if not new_epic_ids:
        return new_apps
    logging.info(f"Adding {len(new_epic_ids)} Epic game(s)...")
    for app_name in new_epic_ids:
        try:
            info = installed_epic.get(app_name)
            if not info:
                continue
            game_name = info["name"]
            safe_id = "epic_" + "".join(c if c.isalnum() or c in "._-" else "_" for c in app_name)
            grid_path = fetch_grid_by_name(game_name, api_key or '', grids_folder, safe_id)
            epic_url = f"com.epicgames.launcher://apps/{app_name}?action=launch&silent=true"
            if shortcuts_folder and os.name == 'nt':
                os.makedirs(shortcuts_folder, exist_ok=True)
                shortcut_path = os.path.join(shortcuts_folder, safe_id + ".lnk")
                if _create_shortcut_win(shortcut_path, epic_url):
                    cmd = _shortcut_launch_cmd(shortcut_path)
                else:
                    cmd = _epic_launch_cmd(app_name)
            else:
                cmd = _epic_launch_cmd(app_name)
            new_apps.append({
                "name": game_name,
                "cmd": cmd,
                "output": "",
                "detached": "",
                "elevated": "false",
                "hidden": "true",
                "wait-all": "true",
                "exit-timeout": "5",
                "image-path": grid_path or "",
            })
            logging.info(f"Added Epic: {game_name}")
        except Exception as e:
            logging.error(f"Error adding Epic game {app_name}: {e}")
    return new_apps


def add_custom_games(
    custom_list: List[Dict],
    existing_cmds: Set[str],
    api_key: str,
    grids_folder: str,
    shortcuts_folder: Optional[str] = None,
) -> List[Dict]:
    """Add custom games (from JSON) that are not already in config. If shortcuts_folder set (Windows), create .lnk and use that as cmd."""
    new_apps = []
    for g in custom_list:
        exe_cmd = g.get("cmd", "").strip()
        if not exe_cmd or exe_cmd in existing_cmds:
            continue
        name = (g.get("name") or "").strip() or "Custom Game"
        image_path = (g.get("image_path") or "").strip()
        if not image_path:
            safe_id = "custom_" + str(abs(hash(exe_cmd)))[:12]
            image_path = fetch_grid_by_name(name, api_key or '', grids_folder, safe_id) or ""
        if shortcuts_folder and os.name == 'nt' and os.path.sep in exe_cmd and os.path.isfile(exe_cmd):
            os.makedirs(shortcuts_folder, exist_ok=True)
            safe_id = "custom_" + str(abs(hash(exe_cmd)))[:12]
            shortcut_path = os.path.join(shortcuts_folder, safe_id + ".lnk")
            work_dir = os.path.dirname(exe_cmd)
            if _create_shortcut_win(shortcut_path, exe_cmd, work_dir):
                cmd = _shortcut_launch_cmd(shortcut_path)
            else:
                cmd = exe_cmd
        else:
            cmd = exe_cmd
        new_apps.append({
            "name": name,
            "cmd": cmd,
            "output": "",
            "detached": "",
            "elevated": "false",
            "hidden": "true",
            "wait-all": "true",
            "exit-timeout": "5",
            "image-path": image_path,
        })
        logging.info(f"Added custom: {name}")
    return new_apps


def add_xbox_games(
    new_xbox_cmds: Set[str],
    installed_xbox: Dict[str, Dict],
    api_key: str,
    grids_folder: str,
    shortcuts_folder: Optional[str] = None,
) -> List[Dict]:
    """Add discovered Xbox/Windows games with grid images (by name search). If shortcuts_folder set (Windows), create .lnk and use that as cmd."""
    new_apps = []
    if not new_xbox_cmds:
        return new_apps
    logging.info(f"Adding {len(new_xbox_cmds)} Xbox/Windows game(s)...")
    for exe_path in new_xbox_cmds:
        info = installed_xbox.get(exe_path)
        if not info:
            continue
        try:
            name = info["name"]
            safe_id = "xbox_" + str(abs(hash(exe_path)))[:12]
            grid_path = fetch_grid_by_name(name, api_key or '', grids_folder, safe_id)
            if shortcuts_folder and os.name == 'nt' and os.path.isfile(exe_path):
                os.makedirs(shortcuts_folder, exist_ok=True)
                shortcut_path = os.path.join(shortcuts_folder, safe_id + ".lnk")
                work_dir = os.path.dirname(exe_path)
                if _create_shortcut_win(shortcut_path, exe_path, work_dir):
                    cmd = _shortcut_launch_cmd(shortcut_path)
                else:
                    cmd = exe_path
            else:
                cmd = exe_path
            new_apps.append({
                "name": name,
                "cmd": cmd,
                "output": "",
                "detached": "",
                "elevated": "false",
                "hidden": "true",
                "wait-all": "true",
                "exit-timeout": "5",
                "image-path": grid_path or "",
            })
            logging.info(f"Added Xbox/Windows: {name}")
        except Exception as e:
            logging.error(f"Error adding Xbox game {exe_path}: {e}")
    return new_apps


def get_stock_default_apps(host: str) -> List[Dict]:
    """
    Return the stock app list that Sunshine/Apollo ship with (per official docs).
    Used when "Remove all games" resets to host defaults. image-path is left empty
    so the host/client use their own default icons (desktop.png, steam.png, etc.).
    """
    host = (host or "sunshine").strip().lower()
    if host not in ("sunshine", "apollo"):
        host = "sunshine"

    def _app(
        name: str,
        cmd: str = "",
        output: str = "",
        detached: str = "",
        elevated: str = "false",
        hidden: str = "true",
        wait_all: str = "true",
        exit_timeout: str = "5",
        image_path: str = "",
        prep_do: str = "",
        prep_undo: str = "",
    ) -> Dict:
        app: Dict = {
            "name": name,
            "cmd": cmd,
            "output": output,
            "detached": detached,
            "elevated": elevated,
            "hidden": hidden,
            "wait-all": wait_all,
            "exit-timeout": exit_timeout,
            "image-path": image_path,
        }
        if prep_do or prep_undo:
            app["prep-cmd"] = [{"do": prep_do, "undo": prep_undo, "elevated": False}]
        return app

    # Desktop — stream the desktop (Sunshine app examples)
    desktop = _app("Desktop")

    # Steam Big Picture — official name/structure from Sunshine docs (Windows)
    if os.name == "nt":
        steam = _app(
            "Steam Big Picture",
            detached="steam://open/bigpicture",
            prep_do="steam://close/bigpicture",
            prep_undo="steam://open/bigpicture",
        )
    elif sys.platform == "darwin":
        steam = _app(
            "Steam Big Picture",
            detached="open steam://open/bigpicture",
            prep_do="open steam://close/bigpicture",
            prep_undo="open steam://open/bigpicture",
        )
    else:
        steam = _app(
            "Steam Big Picture",
            detached="steam steam://open/bigpicture",
            prep_do="steam steam://close/bigpicture",
            prep_undo="steam steam://open/bigpicture",
        )

    if host == "apollo":
        virtual_display = _app("Virtual Display")
        return [desktop, steam, virtual_display]
    return [desktop, steam]


def remove_all_apps_from_config(
    apps_json_path: str,
    grids_folder: str,
    host: str = "sunshine",
    shortcuts_folder: Optional[str] = None,
) -> int:
    """
    Remove all games and manually added apps, then restore the stock default apps
    that Sunshine/Apollo ship with (Desktop, Steam Big Picture, and for Apollo Virtual Display).
    Uses official structure with empty image-path so the host uses its own icons.
    If shortcuts_folder is set, deletes all .lnk files in it.
    Returns the number of apps that were removed.
    """
    config = get_sunshine_config(apps_json_path)
    apps = config.get('apps', [])
    removed_count = len(apps)

    # Delete thumbnails for removed apps when they live in our grids folder
    grids_folder_abs = os.path.abspath(grids_folder) if grids_folder else ""
    for app in apps:
        grid_path = app.get('image-path')
        if grid_path and os.path.exists(grid_path):
            if grids_folder_abs and os.path.abspath(os.path.dirname(grid_path)) == grids_folder_abs:
                try:
                    os.remove(grid_path)
                    logging.debug(f"Removed grid image: {grid_path}")
                except Exception as e:
                    logging.warning(f"Failed to remove grid image {grid_path}: {e}")

    # Remove any other PNGs in the grids folder (orphaned thumbnails)
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

    # Remove all generated shortcuts when using a shortcuts folder
    if shortcuts_folder and os.path.isdir(shortcuts_folder):
        try:
            for name in os.listdir(shortcuts_folder):
                if name.lower().endswith('.lnk'):
                    path = os.path.join(shortcuts_folder, name)
                    try:
                        os.remove(path)
                        logging.debug(f"Removed shortcut: {path}")
                    except Exception as e:
                        logging.warning(f"Failed to remove {path}: {e}")
        except OSError as e:
            logging.warning(f"Could not list shortcuts folder {shortcuts_folder}: {e}")

    # Restore stock defaults (Desktop, Steam Big Picture, Virtual Display for Apollo)
    default_apps = get_stock_default_apps(host)
    config['apps'] = default_apps
    save_sunshine_config(apps_json_path, config)
    default_names = [a.get('name', '') for a in default_apps]
    logging.info(f"Removed {removed_count} app(s). Restored stock apps: {default_names}.")
    return removed_count


def main() -> None:
    """Main application function."""
    parser = argparse.ArgumentParser(description='Sunshine Steam Game Automation')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--no-restart', action='store_true', help='Skip starting Steam (if not running) and skip restarting Sunshine/Apollo')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--remove-games', action='store_true', help='Remove all games (Steam + manually added); keep only stock apps Desktop, Steam, Virtual Display')
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
                host=host_name.lower(),
                shortcuts_folder=config.get('SUNSHINE_SHORTCUTS_FOLDER') or '',
            )
            if not args.no_restart:
                restart_sunshine(config['SUNSHINE_EXE_PATH'])
            logging.info("Remove-games completed successfully")
            wasteland_msg = f"Games removed. Your {host_name} is now a barren wasteland where joy and whimsy go to die."
            print()
            print("=" * 70)
            print(f"  {wasteland_msg}")
            print("=" * 70)
            print()
            print(f"BANNER:{wasteland_msg}")
            return
        # ----- normal import flow below -----
        
        # Start Steam only if not already running (unless disabled)
        if not args.no_restart:
            ensure_steam_running(config['STEAM_EXE_PATH'])
        
        # Load installed games (Steam)
        installed_games = load_installed_games(config['STEAM_LIBRARY_VDF_PATH'])
        
        # Load Epic games (Windows only, if path set)
        installed_epic = {}
        if config.get('EPIC_MANIFESTS_PATH') and os.name == 'nt':
            installed_epic = load_installed_epic_games(config['EPIC_MANIFESTS_PATH'])
        
        # Load custom games (from JSON if path set)
        custom_list = load_custom_games(config.get('CUSTOM_GAMES_JSON_PATH', '') or '')
        custom_cmds = {g["cmd"] for g in custom_list}
        
        # Load Xbox/Windows games from usual folders (e.g. C:\XboxGames)
        installed_xbox = {}
        if config.get('XBOX_GAMES_FOLDERS'):
            installed_xbox = load_installed_xbox_games(config['XBOX_GAMES_FOLDERS'])
        
        # Load Sunshine configuration
        sunshine_config = get_sunshine_config(config['SUNSHINE_APPS_JSON_PATH'])
        
        # Ensure grids folder exists
        os.makedirs(config['SUNSHINE_GRIDS_FOLDER'], exist_ok=True)
        
        # Process existing apps (Steam, Epic, custom, Xbox)
        shortcuts_folder = config.get('SUNSHINE_SHORTCUTS_FOLDER') or ''
        updated_apps, removed_steam, removed_epic, existing_steam_apps, existing_epic_apps, existing_xbox_cmds = process_existing_apps(
            sunshine_config, installed_games, installed_epic, custom_cmds, installed_xbox, shortcuts_folder
        )
        
        # Find new games to add
        new_games = set(installed_games.keys()) - existing_steam_apps
        new_epic = set(installed_epic.keys()) - existing_epic_apps
        new_xbox = set(installed_xbox.keys()) - existing_xbox_cmds
        existing_cmds = {app.get('cmd', '').strip() for app in updated_apps}
        existing_cmds_norm = {os.path.normpath(c) for c in existing_cmds if os.path.sep in c}
        existing_cmds |= existing_cmds_norm
        new_custom = [g for g in custom_list if g["cmd"].strip() not in existing_cmds and os.path.normpath(g["cmd"].strip()) not in existing_cmds]
        
        # Log changes
        if removed_steam:
            logging.info(f"Steam games to remove: {[name for name, _ in removed_steam]}")
        if removed_epic:
            logging.info(f"Epic games to remove: {[name for name, _ in removed_epic]}")
        if new_games:
            logging.info(f"New Steam games to add: {[installed_games[app_id] for app_id in new_games]}")
        if new_epic:
            logging.info(f"New Epic games to add: {[installed_epic[aid]['name'] for aid in new_epic]}")
        if new_xbox:
            logging.info(f"New Xbox/Windows games to add: {[installed_xbox[c]['name'] for c in new_xbox]}")
        if new_custom:
            logging.info(f"New custom games to add: {[g['name'] for g in new_custom]}")
        
        if not removed_steam and not removed_epic and not new_games and not new_epic and not new_xbox and not new_custom:
            logging.info("No changes needed - all games are up to date")
            return
        
        if args.dry_run:
            logging.info("Dry run mode - no changes will be made")
            return
        
        # Add new Steam games
        new_steam_apps = add_new_games(new_games, installed_games, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'])
        updated_apps.extend(new_steam_apps)
        # Add new Epic games
        new_epic_apps = add_epic_games(new_epic, installed_epic, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'], shortcuts_folder)
        updated_apps.extend(new_epic_apps)
        # Add new Xbox/Windows games
        new_xbox_apps = add_xbox_games(new_xbox, installed_xbox, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'], shortcuts_folder)
        updated_apps.extend(new_xbox_apps)
        # Add new custom games
        new_custom_apps = add_custom_games(custom_list, existing_cmds, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'], shortcuts_folder)
        updated_apps.extend(new_custom_apps)
        
        # Update and save configuration
        sunshine_config['apps'] = updated_apps
        save_sunshine_config(config['SUNSHINE_APPS_JSON_PATH'], sunshine_config)
        
        # Restart Sunshine after processing (unless disabled)
        if not args.no_restart:
            restart_sunshine(config['SUNSHINE_EXE_PATH'])
        
        logging.info("Sunshine apps.json update process completed successfully")
        host_display = os.getenv("HOST", "sunshine").strip()
        if host_display.lower() not in ("sunshine", "apollo"):
            host_display = "sunshine"
        host_display = host_display.capitalize()
        spherical_msg = f"Your {host_display} is now SPHERICAL!"
        print()
        print("=" * 70)
        print(f"  {spherical_msg}")
        print("=" * 70)
        print()
        print(f"BANNER:{spherical_msg}")
        
    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
