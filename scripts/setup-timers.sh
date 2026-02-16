#!/usr/bin/env bash
# Setup systemd user timers for job search automation.
# Run: bash scripts/setup-timers.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SYSTEMD_DIR="$PROJECT_DIR/systemd"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
CONFIG_DIR="$HOME/.config/job-search"

echo "=== Job Search Automation — Systemd Timer Setup ==="
echo "Project: $PROJECT_DIR"
echo ""

# Create directories
mkdir -p "$USER_SYSTEMD_DIR"
mkdir -p "$CONFIG_DIR"

# Generate env file template if it doesn't exist
ENV_FILE="$CONFIG_DIR/env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'ENVEOF'
# Environment variables for job search automation.
# Fill in values and uncomment the lines you need.
# SMTP_USER=your_email@gmail.com
# SMTP_PASSWORD=your_app_password
# HUNTER_API_KEY=your_key
ENVEOF
    echo "Created env template at $ENV_FILE"
    echo "  -> Edit this file with your API keys and SMTP credentials"
else
    echo "Env file already exists: $ENV_FILE"
fi

# Symlink all unit files
echo ""
echo "Installing systemd units..."
for unit in "$SYSTEMD_DIR"/*.service "$SYSTEMD_DIR"/*.timer; do
    name="$(basename "$unit")"
    ln -sf "$unit" "$USER_SYSTEMD_DIR/$name"
    echo "  Linked $name"
done

# Reload systemd
systemctl --user daemon-reload
echo ""
echo "Reloaded systemd user daemon"

# Enable and start all timers (2 timers: monitor + outreach)
TIMERS=(
    job-search-monitor.timer
    job-search-outreach.timer
)

echo ""
echo "Enabling and starting timers..."
for timer in "${TIMERS[@]}"; do
    systemctl --user enable "$timer"
    systemctl --user start "$timer"
    echo "  Started $timer"
done

# Enable lingering so timers run even when logged out
loginctl enable-linger "$USER"
echo ""
echo "Enabled lingering for user $USER"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Useful commands:"
echo "  systemctl --user list-timers              # See all timer schedules"
echo "  systemctl --user status job-search-monitor # Check a service"
echo "  journalctl --user -u job-search-monitor    # View logs"
echo "  systemctl --user start job-search-monitor  # Run manually"
