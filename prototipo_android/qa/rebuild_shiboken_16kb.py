"""Recompila o módulo oficial Shiboken 6.12.0 com alinhamento Android de 16 KB."""
from argparse import ArgumentParser
from pathlib import Path
import json
import os
import subprocess
import sys
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preparar_compilacao import download, fetch, unzip, run
from qa.inspect_apk import elf_load_alignments


def build(work):
    stage = work / 'shiboken-16kb'
    source = stage / 'source'
    generated = stage / 'generated'
    source.mkdir(parents=True, exist_ok=True)
    python = work / 'venv' / 'bin' / 'python'
    wheel_name = 'shiboken6_generator-6.12.0-cp310-abi3-manylinux_2_34_x86_64.whl'
    wheel = download('https://download.qt.io/official_releases/QtForPython/shiboken6-generator/' + wheel_name,
                     work / 'downloads' / wheel_name)
    run([python, '-m', 'pip', 'install', wheel])
    base = 'https://raw.githubusercontent.com/pyside/pyside-setup/v6.12.0/sources/shiboken6/shibokenmodule/'
    for name in ('nothing.h', 'typesystem_shiboken.xml', 'shibokenmodule.cpp'):
        (source / name).write_bytes(fetch(base + name))
    # Este cabeçalho privado é usado pelo módulo oficial, mas não vai no wheel.
    (source / 'sbkconverter_p.h').write_bytes(fetch(
        'https://raw.githubusercontent.com/pyside/pyside-setup/v6.12.0/sources/shiboken6/libshiboken/sbkconverter_p.h'))
    generator = work / 'venv' / 'bin' / 'shiboken6'
    if not generator.is_file():
        generator = next((work / 'venv').glob('lib/python*/site-packages/shiboken6_generator/shiboken6'))
    run([generator, '--generator-set=shiboken', '--avoid-protected-hack',
         f'--output-directory={generated}', f'--typesystem-paths={source}',
         source / 'nothing.h', source / 'typesystem_shiboken.xml'], cwd=source)
    android_wheel = next((work / 'wheels').glob('shiboken6-6.12.0-*-android_aarch64.whl'))
    extracted = stage / 'android-wheel'
    unzip(android_wheel, extracted)
    package = extracted / 'shiboken6'
    headers = package / 'include' / 'shiboken6'
    python_source = work / 'app' / '.buildozer' / 'android' / 'platform' / 'build-arm64-v8a' / 'build' / 'other_builds' / 'python3' / 'arm64-v8a__ndk_target_28' / 'python3'
    python_include = python_source / 'Include'
    python_config = python_source / 'android-build'
    if not (python_include / 'Python.h').is_file() or not (python_config / 'pyconfig.h').is_file():
        raise RuntimeError('Cabeçalhos do Python Android ainda não estão prontos.')
    tools = work / 'android-sdk' / 'ndk' / '28.2.13676358' / 'toolchains' / 'llvm' / 'prebuilt' / 'linux-x86_64' / 'bin'
    target = stage / 'Shiboken.abi3.so'
    command = [tools / 'aarch64-linux-android28-clang++', '-shared', '-fPIC', '-std=c++20', '-O2',
               '-DPy_LIMITED_API=0x030A0000', '-fvisibility=hidden',
               '-I' + str(headers), '-I' + str(python_include), '-I' + str(python_config),
               '-I' + str(source),
               '-I' + str(generated / 'Shiboken'),
               generated / 'Shiboken' / 'shiboken_module_wrapper.cpp',
               '-L' + str(package), '-l:libshiboken6.abi3.so',
               '-Wl,-rpath,$ORIGIN', '-Wl,-z,max-page-size=16384', '-Wl,-z,common-page-size=16384',
               '-o', target]
    run(command)
    run([tools / 'llvm-strip', '--strip-unneeded', target])
    alignments = elf_load_alignments(target.read_bytes())
    if min(alignments) < 16384:
        raise RuntimeError('O módulo recompilado ainda não tem alinhamento de 16 KB.')
    report = {'source': base, 'version': '6.12.0', 'module': str(target),
              'alignment': alignments, 'compiler': str(command[0]),
              'note': 'Código oficial sem alteração funcional; módulo recompilado com max/common page size de 16 KB.'}
    (stage / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    return target


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=Path.home() / 'novaview-android-prototype-build')
    arguments = parser.parse_args()
    build(arguments.work_dir.resolve())
