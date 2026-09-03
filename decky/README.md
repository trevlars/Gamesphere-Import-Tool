# GameSphere Import — DeckyLoader plugin

Import your Steam library into Sunshine from Game Mode — uses the same **automagic** CLI as the host (`gamesphere-import`).

## Prerequisites

1. Install the CLI (detects paths automatically):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/trevlars/Gamesphere-Import-Tool/main/scripts/install-linux.sh | bash
   ```

2. Sunshine running as a user service (`systemctl --user status sunshine`) or Flatpak.

## Build & install

On a machine with Node 18+ and pnpm:

```bash
cd decky
pnpm install
pnpm run build
```

Copy or symlink the `decky` folder into your Decky plugins directory:

```bash
# Steam Deck / Bazzite with Decky
ln -sfn "$HOME/.local/share/gamesphere-import-tool/decky" \
  "$HOME/homebrew/plugins/gamesphere-import"
```

Then reload Decky (or restart Steam in Game Mode).

## What it does

- **Import Steam games** — runs `gamesphere-import` (dry-run optional) and shows log output in the plugin panel
- **Remove all games** — resets Sunshine to stock apps (Desktop, Steam Big Picture)
- **Auto paths** — uses the same path detection as the CLI; no manual `.env` editing on Deck/Bazzite

## Notes

- On Bazzite, your existing Sunshine `prep-cmd` hooks (e.g. `sunshine-stream-prep.sh`) are preserved during normal import; only `--remove-games` resets stock apps.
- Epic/Xbox/custom game import remains Windows-only in the CLI; the Decky plugin is Steam-focused on Linux.
