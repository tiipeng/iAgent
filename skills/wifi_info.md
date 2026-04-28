# wifi_info
Show the current Wi-Fi SSID and IP address.

## Steps
1. Run: `networksetup -getairportnetwork en0 2>/dev/null || ipconfig getifaddr en0 2>/dev/null`
2. Run: `ifconfig en0 2>/dev/null | grep "inet "`
3. Report SSID and IP address.
