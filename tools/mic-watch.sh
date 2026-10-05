#!/bin/sh
# Runs every minute from the board's crontab (docs/tutorial.md, Step 5).
# After a USB mic or camera is replugged, WirePlumber can lose the input, and the app then sees no
# microphone. This re-runs the fix that worked by hand: stop the app, restart WirePlumber, start the app.
export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Bluetooth speaker: after a power cut the board comes back with "Paired: no", so reconnect, and re-pair if
# needed (works while the speaker is in pairing mode, which most enter when they find nothing to join).
SPK=41:42:D4:D6:80:FE
if ! bluetoothctl info $SPK | grep -q 'Connected: yes'; then
  bluetoothctl power on >/dev/null; bluetoothctl pairable on >/dev/null  # off = paired but not bonded: key never saved
  if ! bluetoothctl info $SPK | grep -q 'Bonded: yes'; then
    bluetoothctl --timeout 10 scan on >/dev/null
    bluetoothctl pair $SPK >/dev/null && bluetoothctl trust $SPK >/dev/null
  fi
  if bluetoothctl connect $SPK | grep -q successful; then
    echo "$(date '+%F %T') speaker reconnected" >> "$HOME/mic-watch.log"
    sleep 3
    wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0
  fi
fi

grep -q USB-Audio /proc/asound/cards || exit 0               # no USB mic plugged in: nothing to fix
pw-dump | grep -q '"node.name": "alsa_input' && exit 0       # PipeWire sees it: all good
echo "$(date '+%F %T') mic missing from PipeWire, restarting" >> "$HOME/mic-watch.log"
running=$(arduino-app-cli app list | grep -c '^user:jarvis .*running')
[ "$running" = 1 ] && arduino-app-cli app stop user:jarvis
systemctl --user restart wireplumber
sleep 5
[ "$running" = 1 ] && arduino-app-cli app start user:jarvis
