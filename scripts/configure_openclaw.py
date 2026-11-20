"""Create a separate local OpenClaw configuration for the maritime demo."""
from pathlib import Path
import os
import json
import secrets
import shutil

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get('AMI_OPENCLAW_HOME', str(Path.home() / '.local/share/ami-openclaw'))) / 'state'


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    STATE.chmod(0o700)
    config_path = STATE / 'openclaw.json'
    if config_path.exists():
        print(f'Preserved existing configuration: {config_path}')
        return
    workspace = STATE / 'workspace'
    shutil.copytree(ROOT / 'openclaw/workspace', workspace, dirs_exist_ok=True)
    config = {
        'gateway': {'mode': 'local', 'bind': 'loopback', 'port': 18790,
                    'auth': {'mode': 'token', 'token': secrets.token_urlsafe(32)}},
        'agents': {'defaults': {
            'workspace': str(workspace),
            'model': {'primary': 'ollama/ami-demo3-qwen:latest'},
            'timeoutSeconds': 600,
        }},
        'models': {'providers': {'ollama': {
            'baseUrl': 'http://127.0.0.1:11434', 'api': 'ollama', 'apiKey': 'ollama-local',
            'models': [{'id': 'ami-demo3-qwen:latest', 'name': 'Maritime Qwen 2.5 7B',
                        'reasoning': False, 'input': ['text'],
                        'contextWindow': 32768, 'maxTokens': 4096}],
        }}},
        'tools': {'allow': ['investigate_port_impact']},
        'plugins': {'allow': ['ami-maritime'],
                    'load': {'paths': [str(ROOT / 'openclaw/maritime-plugin')]},
                    'entries': {'ami-maritime': {'enabled': True, 'config': {'repoRoot': str(ROOT)}}}},
    }
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    config_path.chmod(0o600)
    print(f'Configured local maritime OpenClaw on port 18790: {config_path}')
    print('Model: local Ollama. Only the maritime investigation tool is allowed.')

if __name__ == '__main__':
    main()
