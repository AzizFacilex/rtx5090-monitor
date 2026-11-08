#!/usr/bin/env bash
# Install the RTX 5090 top-bar indicator + terminal dashboard for the current user.
set -euo pipefail
cd "$(dirname "$0")"
if ! python3 -c 'import gi; gi.require_version("AyatanaAppIndicator3","0.1")' 2>/dev/null; then
  echo "Installing the AppIndicator GObject bindings (needs sudo)…"
  sudo apt install -y gir1.2-ayatanaappindicator3-0.1 libnotify-bin
fi
command -v astral-guard >/dev/null || echo "WARNING: astral-guard not found - install https://github.com/ksokolowski/astral-hwmon first (per-pin data will show as unavailable)."
install -Dm755 bin/gpu-indicator "$HOME/.local/bin/gpu-indicator"
install -Dm755 bin/gpu-monitor   "$HOME/.local/bin/gpu-monitor"
for f in gpu-indicator gpu-monitor; do
  sed "s|@HOME@|$HOME|g" "desktop/$f.desktop" > "$HOME/.local/share/applications/$f.desktop"
done
mkdir -p "$HOME/.config/autostart"
cp "$HOME/.local/share/applications/gpu-indicator.desktop" "$HOME/.config/autostart/"
pkill -f "$HOME/.local/bin/gpu-indicator" 2>/dev/null || true
nohup "$HOME/.local/bin/gpu-indicator" >/dev/null 2>&1 &
echo "Installed. The indicator is in the top bar and starts automatically at login."
