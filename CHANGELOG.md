# Changelog

All notable changes to GameSphere Import Tool are documented here.

## [0.3.0] — 2026-09-03

### Added
- **Automagic path detection** on Linux, macOS, and Windows (`platform_paths.py`) — Steam VDF, Sunshine/Apollo `apps.json`, covers folder, Flatpak vs native, systemd vs exe restart
- **`--auto-config`** and **`--print-config`** CLI flags
- **`scripts/install-linux.sh`** one-liner for Bazzite, Steam Deck, and generic Linux
- **`gamesphere-import`** wrapper command after Linux install
- **DeckyLoader plugin scaffold** (`decky/`) for Game Mode import from Steam Deck / Bazzite
- **`docs/HOST_INTEGRATION.md`** — how Sunshine and Apollo can integrate this tool

### Fixed
- **Linux Steam launches** — games now use Sunshine’s required `detached` commands (not `cmd`); existing entries are repaired on re-import
- **Re-import duplicates** — Linux `steam steam://rungameid/…` commands are recognized correctly
- **Bazzite stream prep** — auto-adds `sunshine-stream-prep.sh` hooks to imported games when that script exists

### Changed
- Linux/macOS: start Steam and restart Sunshine/Apollo automatically (systemd, Flatpak, or exe)
- README rewritten around zero-config / automagic usage

## [0.2.0]

- Windows GUI, Apollo support, Epic (beta), Xbox/Game Pass discovery, custom games JSON, Remove all games

## [1.0.0] — upstream fork baseline

- Fork of [Sunshine-App-Automation](https://github.com/CommonMugger/Sunshine-App-Automation)
