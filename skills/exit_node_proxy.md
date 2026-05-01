# exit_node_proxy
Use this when the user asks for Tailscale exit node, proxy, VPN routing, SOCKS, or using the iPad as a network gateway.

## Key conclusion
- Real Tailscale exit node on this iPad is NOT possible with the current iOS jailbreak setup.
- Reason: iOS Network Extension sandbox and missing kernel-level packet forwarding/tun support; no usable `/dev/tun`; cannot set IP forwarding.
- Do not waste time trying to enable `AdvertiseExitNode`; Tailscale iOS may contain code strings but runtime prefs are in-memory and iOS blocks exit-node routing.

## Working alternatives
1. SSH dynamic SOCKS proxy from another device:
```sh
ssh -D 1080 -N mobile@100.115.59.76
```
2. Python SOCKS5 server on iPad:
- Script: `/var/mobile/socks5_server.py`
- Port: `1081`
- Process was seen running as mobile.
- Test from another Tailscale device:
```sh
curl --socks5 100.115.59.76:1081 https://httpbin.org/ip
```
3. Per-port forwarding with `socat` or `ncat` for specific services.

## Steps
1. If asked for exit node, explain briefly that kernel-level exit node is blocked on iOS.
2. Offer or configure app-level SOCKS/HTTP proxy instead.
3. Check port 1081 and process `/var/mobile/socks5_server.py`.
4. Use `socat`/`ncat` only for targeted port forwards.

## Pitfalls
- No `ifconfig`, `netstat`, `pfctl`, normal Linux routing stack, or TUN device.
- Port 1080 may already be in use; use 1081 for custom SOCKS server.
