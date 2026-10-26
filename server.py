"""Local-only stdio MCP adapter for the official EasyEDA bridge."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

SKILL = Path(os.environ.get('EASYEDA_SKILL_DIR', str(Path.home() / '.codex/skills/easyeda-api'))).expanduser()
INSTRUCTIONS = (
    f'Before EasyEDA design operations read {SKILL / "SKILL.md"} and the exact '
    'references/classes signatures, enums and interfaces for EVERY EDA API used. '
    'Check current project/document before editing; PCB and schematic units differ. '
    'Use easyeda_windows to obtain a connected window ID. If multiple windows exist, '
    'resolve the intended window with the user. Execute requires that explicit ID. '
    'Code is JavaScript in an async function(eda); await promises and return results. '
    'Execution can modify designs. After timeout or transport failure, effects may '
    'already have occurred: inspect state before any further action; never blindly retry.'
)


class BridgeError(Exception):
    def __init__(self, message, uncertain=False, details=None):
        super().__init__(message)
        self.uncertain = uncertain
        self.details = details


class Bridge:
    def __init__(self, ports=range(49620, 49630), execute_timeout=35):
        self.ports = ports
        self.execute_timeout = execute_timeout
        # Ignore proxy settings and never follow redirects outside loopback.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, port, path, payload=None, timeout=1):
        req = urllib.request.Request(
            f'http://127.0.0.1:{port}{path}',
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with self.http.open(req, timeout=timeout) as response:
                data = json.load(response)
            if not isinstance(data, dict):
                raise ValueError('Bridge response must be a JSON object')
            if data.get('success') is False or data.get('error'):
                raise BridgeError(str(data.get('error', 'Bridge operation failed')), payload is not None, data)
            return data
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            raise BridgeError(f'Bridge HTTP {exc.code}: {body}', payload is not None) from exc
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise BridgeError(f'Bridge transport/response failure: {exc}', payload is not None) from exc

    def discover(self):
        found = []
        for port in self.ports:
            try:
                health = self.request(port, '/health', timeout=0.3)
                if health.get('service') == 'easyeda-bridge':
                    found.append((port, health))
            except BridgeError:
                pass
        if len(found) > 1:
            raise BridgeError('Multiple bridge servers found; stop stale bridge instances first.', details={'ports': [p for p, _ in found]})
        return found[0] if found else None

    def require(self):
        found = self.discover()
        if not found:
            raise BridgeError('Official EasyEDA bridge not found on 127.0.0.1:49620-49629. Call easyeda_status(start_bridge=true).')
        return found

    def status(self, start_bridge=False):
        found = self.discover()
        started = False
        if found is None and start_bridge:
            node_path = os.environ.get('EASYEDA_NODE') or shutil.which('node')
            node = Path(node_path) if node_path else None
            script = SKILL / 'scripts/bridge-server.mjs'
            if node is None or not node.is_file() or not script.is_file():
                raise BridgeError('Node runtime or official bridge script missing; install the official skill first.')
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
            with (Path(__file__).parent / 'bridge.log').open('ab') as log:
                subprocess.Popen([str(node), str(script)], cwd=str(SKILL), stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, creationflags=flags, close_fds=True)
            started = True
            for _ in range(10):
                time.sleep(0.3)
                found = self.discover()
                if found:
                    break
        if found is None:
            return {'bridgeConnected': False, 'edaConnected': False, 'started': started,
                    'message': 'Bridge unavailable. Use start_bridge=true; inspect bridge.log if startup failed.',
                    'skill': str(SKILL / 'SKILL.md')}
        port, health = found
        return {'bridgeConnected': True, 'port': port, 'started': started, 'health': health,
                'skill': str(SKILL / 'SKILL.md'),
                'next': 'Call easyeda_windows. No connected windows means the run-api-gateway extension must be loaded in EasyEDA.'}

    def windows(self):
        port, _ = self.require()
        return {'port': port, **self.request(port, '/eda-windows')}

    def execute(self, code, window_id):
        if not isinstance(code, str) or not code.strip():
            raise BridgeError('code must be a nonempty JavaScript string.')
        if not isinstance(window_id, str) or not window_id.strip():
            raise BridgeError('An explicit nonempty window_id from easyeda_windows is required.')
        port, _ = self.require()
        windows = self.request(port, '/eda-windows').get('windows', [])
        if not any(w.get('windowId') == window_id and w.get('connected') is True for w in windows):
            raise BridgeError(f'Target window {window_id!r} is not connected. Refresh easyeda_windows; no execution sent.')
        # Single attempt: no fallback to activeWindowId and no retry on ambiguous outcomes.
        return self.request(port, '/execute', {'code': code, 'windowId': window_id}, self.execute_timeout)


bridge = Bridge()
TOOLS = [
    types.Tool(name='easyeda_status', description='Discover the official local EasyEDA bridge and connection status. Optionally start its existing official Node script in a hidden background process.',
               inputSchema={'type': 'object', 'properties': {'start_bridge': {'type': 'boolean', 'default': False}}, 'additionalProperties': False}),
    types.Tool(name='easyeda_windows', description='List connected EasyEDA window IDs. Resolve the intended window before executing code.',
               inputSchema={'type': 'object', 'properties': {}, 'additionalProperties': False}),
    types.Tool(name='easyeda_execute', description=INSTRUCTIONS,
               inputSchema={'type': 'object', 'properties': {'code': {'type': 'string', 'minLength': 1}, 'window_id': {'type': 'string', 'minLength': 1}}, 'required': ['code', 'window_id'], 'additionalProperties': False}),
]


async def list_tools(context, params):
    return types.ListToolsResult(tools=TOOLS)


async def call_tool(context, params):
    try:
        args = params.arguments or {}
        if params.name == 'easyeda_status':
            if set(args) - {'start_bridge'} or not isinstance(args.get('start_bridge', False), bool):
                raise BridgeError('start_bridge must be boolean; no additional arguments allowed.')
            result = await asyncio.to_thread(bridge.status, **args)
        elif params.name == 'easyeda_windows':
            if args:
                raise BridgeError('easyeda_windows accepts no arguments.')
            result = await asyncio.to_thread(bridge.windows)
        elif params.name == 'easyeda_execute':
            if set(args) != {'code', 'window_id'}:
                raise BridgeError('Exactly code and explicit window_id are required.')
            result = await asyncio.to_thread(bridge.execute, **args)
        else:
            raise BridgeError(f'Unknown tool: {params.name}')
        return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(result, ensure_ascii=False))])
    except Exception as exc:
        uncertain = isinstance(exc, BridgeError) and exc.uncertain
        result = {'error': str(exc), 'executionOutcomeUncertain': uncertain,
                  'retryAutomatically': False}
        if uncertain:
            result['next'] = 'Code may already have changed the design. Inspect state before deciding whether to repeat anything.'
        if isinstance(exc, BridgeError) and exc.details is not None:
            result['details'] = exc.details
        return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text=json.dumps(result, ensure_ascii=False))])


async def main():
    server = Server('easyeda-local', version='1.0.0', instructions=INSTRUCTIONS,
                    on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
