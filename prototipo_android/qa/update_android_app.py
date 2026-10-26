"""Atualiza fontes e recursos no projeto isolado, preservando o bootstrap validado."""
import hashlib
import io
from pathlib import Path
import re
import shutil
import tarfile
import time
import xml.etree.ElementTree as ET

VERSION = '0.2.1'
VERSION_CODE = 10283


def application_files(source):
    files = {name: source / name for name in ('main.py', 'controller.py', 'datalogger.py')}
    for directory in ('ui', 'assets'):
        for path in sorted((source / directory).rglob('*')):
            if path.is_file() and path.suffix in ('.qml', '.png', '.txt'):
                files[path.relative_to(source).as_posix()] = path
    return files


def repack_application(archive, files):
    temporary = archive.with_suffix('.updated.tmp')
    remaining = dict(files)
    with tarfile.open(archive, 'r:gz') as old, tarfile.open(temporary, 'w:gz', format=tarfile.USTAR_FORMAT) as new:
        directories = set()
        for member in old:
            if member.name == 'samples' or member.name.startswith('samples/'):
                continue
            # O bootstrap prefere main.pyc a main.py. Não preserve bytecode
            # antigo quando a atualização entrega fontes novos.
            path = Path(member.name)
            if path.suffix == '.pyc' and (path.stem in ('main', 'controller', 'datalogger') or
                    path.parent.name == '__pycache__' and path.stem.split('.')[0] in ('main', 'controller', 'datalogger')):
                continue
            if member.isdir():
                directories.add(member.name.rstrip('/'))
            member.pax_headers = {}
            member.mtime = int(member.mtime)
            content = remaining.pop(member.name, None)
            if content:
                raw = content.read_bytes()
                member.size = len(raw)
                member.mtime = int(time.time())
                new.addfile(member, io.BytesIO(raw))
            else:
                new.addfile(member, old.extractfile(member) if member.isfile() else None)
        for name, path in remaining.items():
            parent = Path(name).parent.as_posix()
            if parent != '.' and parent not in directories:
                raise ValueError(f'Diretório de aplicação ausente: {parent}')
            member = tarfile.TarInfo(name)
            raw = path.read_bytes()
            member.mode = 0o644
            member.size = len(raw)
            member.mtime = int(time.time())
            new.addfile(member, io.BytesIO(raw))
    temporary.replace(archive)


def update_application(work, project, source):
    files = application_files(source)
    archive = project / 'src/main/assets/private.tar'
    repack_application(archive, files)
    fingerprint = hashlib.sha256()
    for name, path in sorted(files.items()):
        fingerprint.update(name.encode('utf-8') + b'\0' + path.read_bytes())
        target = work / 'app' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    strings = project / 'src/main/res/values/strings.xml'
    document = ET.parse(strings)
    for element in document.getroot().findall('string'):
        if element.get('name') == 'private_version':
            element.text = fingerprint.hexdigest()
        elif element.get('name') == 'app_name':
            element.text = 'NovaView Datalogger'
    document.write(strings, encoding='utf-8', xml_declaration=True)
    shutil.copy2(source / 'assets/icon.png', project / 'src/main/res/mipmap/icon.png')
    gradle = project / 'build.gradle'
    text = gradle.read_text(encoding='utf-8')
    text = re.sub(r'versionCode\s+\d+', f'versionCode {VERSION_CODE}', text)
    text = re.sub(r"versionName\s+'[^']+'", f"versionName '{VERSION}'", text)
    gradle.write_text(text, encoding='utf-8')
    return {'version': VERSION, 'version_code': VERSION_CODE, 'source_sha256': fingerprint.hexdigest(),
            'files': sorted(files), 'reports': False}
