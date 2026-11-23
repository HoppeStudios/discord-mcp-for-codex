"""Verify the installed personal adapter and its reviewed local dependencies."""
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import runpy
import sys

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text('utf-8'))
for item in manifest['files']:
    if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
        raise RuntimeError('A reviewed browser adapter file or runtime changed. Review before reinstalling.')
if version('mcp') != manifest['mcp_version']:
    raise RuntimeError('The pinned MCP SDK version changed. Review before reinstalling.')
os.environ['DISCORD_BROWSER_HELPER'] = manifest['helper']
os.environ['DISCORD_BROWSER_HELPER_SHA256'] = manifest['helper_sha256']
os.environ['DISCORD_BROWSER_DATA_DIR'] = manifest['data_dir']
runpy.run_path(str(root / 'browser_adapter.py'), run_name='__main__')
