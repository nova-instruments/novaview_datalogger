"""Lança a ferramenta oficial sem instalar ou alterar o projeto principal."""
from argparse import ArgumentParser
from pathlib import Path
import os
import shutil
import subprocess
import sys
from email.parser import Parser
from zipfile import ZipFile, BadZipFile


def validate_wheel(path: Path, package: str, arch: str) -> str:
    """Confere plataforma e versão sem instalar ou extrair o pacote."""
    if not path.is_file() or path.suffix != '.whl':
        raise ValueError(f'Pacote Android não encontrado: {path}')
    try:
        with ZipFile(path) as wheel:
            metadata_names = [name for name in wheel.namelist() if name.endswith('.dist-info/METADATA')]
            tag_names = [name for name in wheel.namelist() if name.endswith('.dist-info/WHEEL')]
            if len(metadata_names) != 1 or len(tag_names) != 1:
                raise ValueError(f'Pacote sem identificação válida: {path.name}')
            metadata = Parser().parsestr(wheel.read(metadata_names[0]).decode('utf-8'))
            tags = Parser().parsestr(wheel.read(tag_names[0]).decode('utf-8')).get_all('Tag', [])
    except (BadZipFile, UnicodeError) as error:
        raise ValueError(f'Pacote inválido: {path.name}') from error
    if metadata.get('Name', '').casefold() != package.casefold():
        raise ValueError(f'O arquivo {path.name} não é um pacote {package}.')
    endings = ('_arm64_v8a', '_aarch64') if arch == 'aarch64' else ('_x86_64',)
    if not any('android_' in tag and tag.endswith(endings) for tag in tags):
        raise ValueError(f'{path.name}: selecione um pacote Android para {arch}; pacotes Windows e de outra arquitetura não servem.')
    version = metadata.get('Version', '')
    if version != '6.12.0':
        raise ValueError(f'{path.name}: este protótipo usa Qt/PySide6 6.12.0; selecione a mesma versão para Android.')
    return version


def main():
    parser = ArgumentParser(description='Gerar APK de teste do protótipo NovaView.')
    parser.add_argument('--wheel-pyside', required=True, type=Path)
    parser.add_argument('--wheel-shiboken', required=True, type=Path)
    parser.add_argument('--sdk-path', required=True, type=Path)
    parser.add_argument('--ndk-path', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--non-interactive', action='store_true', help='Executa sem perguntas dentro do ambiente de compilação isolado.')
    parser.add_argument('--keep-deployment-files', action='store_true', help='Preserva o cache de compilação para retomar o trabalho.')
    parser.add_argument('--arch', choices=('aarch64', 'x86_64'), default='aarch64',
                        help='Padrão: aarch64/ARM64 para o Galaxy Tab A11. x86_64 é destinado ao emulador.')
    args = parser.parse_args()
    if sys.platform not in ('linux', 'darwin'):
        parser.error('O empacotamento Android requer Linux ou macOS. A prévia pode ser executada no Windows.')
    tool = shutil.which('pyside6-android-deploy')
    if not tool or not shutil.which('java'):
        parser.error('Ative o ambiente isolado com PySide6 e disponibilize o Java 17 ou mais recente.')
    try:
        validate_wheel(args.wheel_pyside, 'PySide6', args.arch)
        validate_wheel(args.wheel_shiboken, 'shiboken6', args.arch)
    except ValueError as error:
        parser.error(str(error))
    for path in (args.sdk_path, args.ndk_path):
        if not path.is_dir():
            parser.error(f'Pasta Android não encontrada: {path}')
    # O nome interno também entra em caminhos de compilação do python-for-android.
    command = [tool, '--name', 'NovaViewAndroidPrototype',
               '--wheel-pyside', str(args.wheel_pyside.resolve()),
               '--wheel-shiboken', str(args.wheel_shiboken.resolve()),
               '--sdk-path', str(args.sdk_path.resolve()), '--ndk-path', str(args.ndk_path.resolve())]
    if args.dry_run:
        command.append('--dry-run')
    if args.non_interactive:
        command.append('--force')
    if args.keep_deployment_files:
        command.append('--keep-deployment-files')
    # Ambiente de compilação e suas alterações ficam fora do aplicativo validado.
    os.chdir(Path(__file__).resolve().parent)
    return subprocess.call(command)


if __name__ == '__main__':
    sys.exit(main())
