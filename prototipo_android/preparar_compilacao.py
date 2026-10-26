"""Prepara e compila uma cópia isolada no Linux/WSL; não altera a versão Windows."""
from argparse import ArgumentParser
from configparser import ConfigParser
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlopen, Request
from urllib.parse import urljoin
import venv
import xml.etree.ElementTree as ET
from zipfile import ZipFile

VERSION = '6.12.0'
NDK = '28.2.13676358'
SOURCE = Path(__file__).resolve().parent


def configure_buildozer(path):
    """Configura recursos e rotação sem alterar o nome interno já compilado."""
    config = ConfigParser(interpolation=None)
    config.read(path, encoding='utf-8')
    if not config.has_section('app'):
        raise ValueError('Configuração Buildozer inválida.')
    if any(character.isspace() for character in config.get('app', 'package.name', fallback='')):
        raise ValueError('O nome interno do aplicativo não pode conter espaços.')
    extensions = [value.strip() for value in config.get('app', 'source.include_exts', fallback='py,png,qml,js').split(',')]
    changed = False
    if 'txt' not in extensions:
        config.set('app', 'source.include_exts', ','.join(extensions + ['txt']))
        changed = True
    for key, value in {'title': 'NovaView Datalogger', 'version': '0.2.1',
                       'icon.filename': 'assets/icon.png',
                       'orientation': 'landscape,portrait,landscape-reverse,portrait-reverse'}.items():
        if config.get('app', key, fallback='') != value:
            config.set('app', key, value)
            changed = True
    if changed:
        with path.open('w', encoding='utf-8') as stream:
            config.write(stream)
    return changed


def run(command, **kwargs):
    print('Executando:', ' '.join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'NovaView-Android-build/0.1'}), timeout=120) as response:
        return response.read()


def download(url, target, sha1=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        partial = target.with_name(target.name + '.partial')
        run(['curl', '--fail', '--location', '--retry', '3', '--continue-at', '-',
             '--output', partial, url])
        partial.replace(target)
    if sha1 and hashlib.sha1(target.read_bytes()).hexdigest().lower() != sha1.lower():
        raise RuntimeError(f'Checksum incorreto: {target.name}')
    return target


def unzip(archive, target):
    target.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as zipped:
        for member in zipped.infolist():
            if not (target / member.filename).resolve().is_relative_to(target.resolve()):
                raise ValueError('Caminho inválido dentro do pacote baixado.')
        zipped.extractall(target)
        for member in zipped.infolist():
            mode = member.external_attr >> 16
            if mode & 0o111:
                (target / member.filename).chmod(0o755)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for name, value in attrs if name == 'href')


def android_wheel(package, folder):
    base = f'https://download.qt.io/official_releases/QtForPython/{package}/'
    parser = Links()
    parser.feed(fetch(base).decode('utf-8'))
    names = [name for name in parser.links if name.lower().startswith(f'{package}-{VERSION}-')
             and name.endswith('android_aarch64.whl')]
    if len(names) != 1:
        raise RuntimeError(f'Não foi encontrado um único pacote Android ARM64 de {package} {VERSION}.')
    return download(urljoin(base, names[0]), folder / names[0])


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=Path.home() / 'novaview-android-prototype-build')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Retoma o Buildozer existente, sem recriar o cache nativo do Qt.')
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Execute no Ubuntu/WSL. Use abrir_previa.bat para a prévia Windows.')
    work = args.work_dir.expanduser().resolve()
    if work == SOURCE or SOURCE.is_relative_to(work) or work.is_relative_to(SOURCE):
        parser.error('A pasta de compilação precisa ficar separada da pasta de fontes.')
    for tool in ('java', 'javac', 'unzip', 'zip', 'gcc', 'make', 'git', 'curl'):
        if not shutil.which(tool):
            parser.error(f'Pré-requisito ausente: {tool}. Consulte qa/install_linux_dependencies.sh.')
    work.mkdir(parents=True, exist_ok=True)
    print(f'Pasta isolada de compilação: {work}', flush=True)
    environment = work / 'venv'
    if not (environment / 'bin' / 'python').is_file():
        venv.create(environment, with_pip=True)
    python = environment / 'bin' / 'python'
    env = os.environ.copy()
    env['VIRTUAL_ENV'] = str(environment)
    env['PATH'] = str(environment / 'bin') + os.pathsep + env['PATH']
    env['PIP_CACHE_DIR'] = str(work / 'cache' / 'pip')
    env['GRADLE_USER_HOME'] = str(work / 'cache' / 'gradle')
    env['ANDROID_USER_HOME'] = str(work / 'cache' / 'android-user')
    env['JAVA_HOME'] = str(Path(shutil.which('javac')).resolve().parents[1])
    run([python, '-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel'], env=env)
    run([python, '-m', 'pip', 'install', f'PySide6=={VERSION}'], env=env)
    android_requirements = subprocess.check_output(
        [str(python), '-c', "from pathlib import Path; import PySide6; print(Path(PySide6.__file__).parent / 'scripts' / 'requirements-android.txt')"],
        text=True, env=env).strip()
    run([python, '-m', 'pip', 'install', '-r', android_requirements], env=env)

    sdk = work / 'android-sdk'
    manager = sdk / 'cmdline-tools' / 'latest' / 'bin' / 'sdkmanager'
    if not manager.is_file():
        repository = ET.fromstring(fetch('https://dl.google.com/android/repository/repository2-1.xml'))
        packages = {node.attrib['path']: node for node in repository.iter()
                    if node.tag.endswith('remotePackage') and 'path' in node.attrib}
        package = packages.get('cmdline-tools;19.0')
        if package is None:
            package = packages.get('cmdline-tools;latest')
        if package is None:
            raise RuntimeError('Ferramentas Android não encontradas no repositório oficial.')
        archive = next(a for a in package.findall('./archives/archive') if a.findtext('host-os') == 'linux')
        complete = archive.find('complete')
        filename = complete.findtext('url')
        archive_path = download('https://dl.google.com/android/repository/' + filename,
                                work / 'downloads' / filename, complete.findtext('checksum'))
        unpacked = work / 'downloads' / 'commandline-unpacked'
        unzip(archive_path, unpacked)
        manager.parent.parent.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(unpacked / 'cmdline-tools'), str(manager.parent.parent))
    env['ANDROID_HOME'] = str(sdk)
    env['ANDROID_SDK_ROOT'] = str(sdk)
    # Buildozer 1.6 ainda procura o caminho antigo das ferramentas do SDK.
    legacy_tools = sdk / 'tools'
    if not legacy_tools.exists():
        legacy_tools.symlink_to(Path('cmdline-tools') / 'latest', target_is_directory=True)
    run([manager, f'--sdk_root={sdk}', '--licenses'], input=b'y\n' * 100, env=env)
    run([manager, f'--sdk_root={sdk}', 'platform-tools', 'platforms;android-35',
         'build-tools;35.0.0', f'ndk;{NDK}'], env=env)
    wheels = work / 'wheels'
    pyside = android_wheel('pyside6', wheels)
    shiboken = android_wheel('shiboken6', wheels)
    application = work / 'app'
    application.mkdir(exist_ok=True)
    for name in ('main.py', 'controller.py', 'datalogger.py', 'gerar_apk.py', 'pyproject.toml', 'requirements.txt'):
        shutil.copy2(SOURCE / name, application / name)
    for folder in ('ui', 'assets'):
        shutil.copytree(SOURCE / folder, application / folder, dirs_exist_ok=True)
    if args.prepare_only:
        print('Ambiente preparado. Use o mesmo comando sem --prepare-only para compilar.', flush=True)
        return 0
    if args.resume:
        if not (application / 'buildozer.spec').is_file():
            raise RuntimeError('Ainda não existe configuração de compilação para retomar.')
        configure_buildozer(application / 'buildozer.spec')
        run([python, '-m', 'buildozer', 'android', 'debug'], env=env, cwd=application)
    else:
        run([python, application / 'gerar_apk.py', '--wheel-pyside', pyside, '--wheel-shiboken', shiboken,
             '--sdk-path', sdk, '--ndk-path', sdk / 'ndk' / NDK, '--non-interactive',
             '--keep-deployment-files'], env=env, cwd=application)
        if configure_buildozer(application / 'buildozer.spec'):
            run([python, '-m', 'buildozer', 'android', 'debug'], env=env, cwd=application)
    # O bin/ é a saída direta do Buildozer; a cópia no diretório superior pode
    # pertencer à etapa anterior, ainda sem os ajustes de dados e orientação.
    apks = list(application.glob('bin/*.apk')) or list(application.glob('*.apk'))
    if not apks:
        raise RuntimeError('Compilação terminou, mas o APK não foi encontrado na saída esperada.')
    destination = SOURCE / 'dist'
    destination.mkdir(exist_ok=True)
    target = destination / 'NovaView-Android-ARM64.apk'
    # Corrige o módulo do wheel oficial que ainda usa segmentos de 4 KB e
    # só considera a entrega concluída após assinatura e inspeção completas.
    run([python, SOURCE / 'qa' / 'finalize_android_package.py', '--work-dir', work], env=env)
    print(f'APK disponível: {target}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
