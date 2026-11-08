#!/usr/bin/env bash
pkill -f "$HOME/.local/bin/gpu-indicator" 2>/dev/null || true
rm -f "$HOME/.local/bin/gpu-indicator" "$HOME/.local/bin/gpu-monitor" \
      "$HOME/.local/share/applications/gpu-indicator.desktop" "$HOME/.local/share/applications/gpu-monitor.desktop" \
      "$HOME/.config/autostart/gpu-indicator.desktop"
echo "Removed."
