"""Atualiza o módulo recompilado no pacote e refaz assinatura/zipalign pelo Gradle."""
from argparse import ArgumentParser
import base64
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preparar_compilacao import run, SOURCE
from qa.inspect_apk import inspect, elf_load_alignments
from qa.rebuild_shiboken_16kb import build
from qa.check_android_extraction import check_extraction
from qa.fix_android_activity import prepare_activity
from qa.update_android_app import update_application


def replace_module(bundle, module):
    """Preserva os demais arquivos e atualiza também a integridade no RECORD."""
    raw = module.read_bytes()
    if min(elf_load_alignments(raw)) < 16384:
        raise ValueError('Módulo de substituição sem alinhamento de 16 KB.')
    digest = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
    replacement = bundle.with_suffix('.16kb.tmp')
    count = 0
    with tarfile.open(bundle, mode='r|gz') as old:
        with replacement.open('wb') as output, gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as compressed:
            # O jtar do bootstrap Android suporta USTAR, mas não os cabeçalhos
            # estendidos PAX que tarfile usa por padrão para nomes longos.
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as new:
                for member in old:
                    member.pax_headers = {}
                    member.mtime = int(member.mtime)
                    file = old.extractfile(member) if member.isfile() else None
                    if member.isfile() and member.name.endswith('/shiboken6/Shiboken.abi3.so'):
                        member.size = len(raw)
                        member.mtime = int(time.time())
                        new.addfile(member, io.BytesIO(raw))
                        count += 1
                    elif member.isfile() and 'shiboken6-' in member.name and member.name.endswith('.dist-info/RECORD'):
                        rows = list(csv.reader(io.StringIO(file.read().decode('utf-8'))))
                        for row in rows:
                            if row and row[0].endswith('shiboken6/Shiboken.abi3.so'):
                                row[1:] = [digest, str(len(raw))]
                        text = io.StringIO()
                        csv.writer(text, lineterminator='\n').writerows(rows)
                        data = text.getvalue().encode('utf-8')
                        member.size = len(data)
                        new.addfile(member, io.BytesIO(data))
                    else:
                        new.addfile(member, file)
    if count != 1:
        raise ValueError(f'Esperado um módulo Shiboken; encontrados: {count}. O pacote original não foi substituído.')
    replacement.replace(bundle)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=Path.home() / 'novaview-android-prototype-build')
    args = parser.parse_args()
    work = args.work_dir.resolve()
    module = work / 'shiboken-16kb' / 'Shiboken.abi3.so'
    if not module.is_file():
        module = build(work)
    project = work / 'app' / '.buildozer' / 'android' / 'platform' / 'build-arm64-v8a' / 'dists' / 'NovaViewAndroidPrototype'
    application = update_application(work, project, SOURCE)
    activity_dispatch = prepare_activity(work, project)
    print(activity_dispatch, flush=True)
    bundle = project / 'libs' / 'arm64-v8a' / 'libpybundle.so'
    if not bundle.is_file() or not bundle.resolve().is_relative_to(work):
        raise ValueError('Pacote nativo não encontrado na pasta isolada de compilação.')
    backup = work / 'shiboken-16kb' / 'libpybundle-original.so'
    if not backup.is_file():
        shutil.copy2(bundle, backup)
    replace_module(bundle, module)
    extraction = check_extraction(work, project)
    print(json.dumps(extraction), flush=True)
    env = os.environ.copy()
    env['GRADLE_USER_HOME'] = str(work / 'cache' / 'gradle')
    env['ANDROID_HOME'] = str(work / 'android-sdk')
    env['ANDROID_SDK_ROOT'] = env['ANDROID_HOME']
    env['JAVA_HOME'] = str(Path(shutil.which('javac')).resolve().parents[1])
    run([project / 'gradlew', '--console=plain', 'assembleDebug'], cwd=project, env=env)
    apks = list((project / 'build' / 'outputs' / 'apk' / 'debug').glob('*.apk'))
    if not apks:
        raise RuntimeError('O Gradle não produziu o APK final.')
    apk = max(apks, key=lambda path: path.stat().st_mtime)
    tools = work / 'android-sdk' / 'build-tools' / '35.0.0'
    report = inspect(apk, tools)
    if report['demonstrations_included']:
        raise ValueError('O APK ainda contém arquivos de demonstração.')
    destination = SOURCE / 'dist' / 'NovaView-Android-ARM64.apk'
    destination.parent.mkdir(exist_ok=True)
    shutil.copy2(apk, destination)
    report['apk'] = str(destination)
    report['android_java_extraction'] = extraction
    report['android_activity_result_dispatch'] = activity_dispatch
    report['application'] = application
    report['rebuilt_module'] = json.loads((work / 'shiboken-16kb' / 'build-report.json').read_text(encoding='utf-8'))
    (SOURCE / 'qa' / 'apk_verificacao_final.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    legacy = SOURCE / 'dist' / 'NovaView-Android-Prototipo-ARM64.apk'
    if legacy.is_file():
        backup_apk = work / 'previous-apks' / 'NovaView-Android-Prototipo-ARM64.apk'
        backup_apk.parent.mkdir(exist_ok=True)
        if not backup_apk.exists():
            shutil.copy2(legacy, backup_apk)
        legacy.unlink()
    print(json.dumps({key: report[key] for key in ('apk', 'bytes', 'sha256', 'architectures', 'native_libraries',
          'elf_16kb_alignment', 'demonstrations_included', 'physical_tablet_test')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
