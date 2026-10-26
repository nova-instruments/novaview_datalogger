"""Diagnóstico somente leitura do ambiente Linux de compilação."""
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess

tools = ['python3', 'pip3', 'gcc', 'g++', 'make', 'autoconf', 'automake', 'libtoolize',
         'pkg-config', 'git', 'zip', 'unzip', 'java', 'javac', 'cmake', 'ninja', 'patch']
result = {'system': platform.platform(), 'tools': {tool: shutil.which(tool) for tool in tools},
          'venv_available': importlib.util.find_spec('venv') is not None,
          'user_home': str(Path.home()), 'free_gb': round(shutil.disk_usage(Path.home()).free / 1024**3, 1)}
result['sudo_without_password'] = subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode == 0
print(json.dumps(result, indent=2))
