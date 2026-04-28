# battery
Check the battery level and charging state of the device.

## Steps
1. Run: `cat /sys/class/power_supply/battery/capacity 2>/dev/null || pmset -g batt 2>/dev/null || echo "unavailable"`
2. Report the percentage and whether plugged in.
