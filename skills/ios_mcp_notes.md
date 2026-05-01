# ios_mcp_notes
Use this when the user asks about ios-mcp, MCP integration, root helper commands, IPA install, or SpringBoard/iOS control beyond XXTouch.

## Key facts
- Package installed: `com.witchan.ios-mcp`.
- HTTP health endpoint has responded on port `8090`: `http://127.0.0.1:8090/health` → status ok.
- It is not a standard stdio MCP server for iAgent config.
- Helper binaries exist under `/var/jb/usr/bin`: `mcp-root`, `mcp-roothelper`, `mcp-appinst`, `mcp-ldid`.
- `ios-mcp` CLI command may not exist in PATH; do not assume it does.

## Steps
1. First check health: `curl -s --max-time 3 http://127.0.0.1:8090/health`.
2. Search helpers with `ls /var/jb/usr/bin/*mcp*`.
3. For root commands, prefer existing sudo flow or `mcp-root` if suitable.
4. Do not put ios-mcp into `mcp_servers` as a stdio command unless an actual MCP server binary is verified.
5. If integrating later, create an HTTP bridge tool that calls the real 8090 endpoints after endpoint discovery.

## Pitfalls
- The root helper tools and the HTTP service are not the same thing as a normal MCP stdio server.
- Avoid hallucinating endpoints; probe and inspect before calling.
