#!/bin/sh
# Runs every minute from the board's crontab (docs/tutorial.md, Step 5).
# After a USB mic or camera is replugged, WirePlumber can lose the input, and the app then sees no
# microphone. This re-runs the fix that worked by hand: stop the app, restart WirePlumber, start the app.
export XDG_RUNTIME_DIR=/run/user/$(id -u)
grep -q USB-Audio /proc/asound/cards || exit 0               # no USB mic plugged in: nothing to fix
pw-dump | grep -q '"node.name": "alsa_input' && exit 0       # PipeWire sees it: all good
echo "$(date '+%F %T') mic missing from PipeWire, restarting" >> "$HOME/mic-watch.log"
running=$(arduino-app-cli app list | grep -c '^user:jarvis .*running')
[ "$running" = 1 ] && arduino-app-cli app stop user:jarvis
systemctl --user restart wireplumber
sleep 5
[ "$running" = 1 ] && arduino-app-cli app start user:jarvis
