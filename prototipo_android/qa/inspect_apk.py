"""Confere estrutura ARM64, alinhamento nativo e assinatura do APK de teste."""
from argparse import ArgumentParser
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tarfile
from zipfile import ZipFile


def elf_load_alignments(raw):
    if raw[:4] != b'\x7fELF' or raw[4] != 2 or raw[5] != 1:
        raise ValueError('Biblioteca nativa não é um ELF64 little-endian.')
    offset = struct.unpack_from('<Q', raw, 32)[0]
    entry_size, count = struct.unpack_from('<HH', raw, 54)
    alignments = []
    for index in range(count):
        header = offset + index * entry_size
        if struct.unpack_from('<I', raw, header)[0] == 1:
            alignments.append(struct.unpack_from('<Q', raw, header + 48)[0])
    return alignments


def elf_relro_conflicts(raw):
    """Detecta dados graváveis que cairiam na página final protegida por RELRO."""
    offset = struct.unpack_from('<Q', raw, 32)[0]
    entry_size, count = struct.unpack_from('<HH', raw, 54)
    headers = [struct.unpack_from('<IIQQQQQQ', raw, offset + i * entry_size) for i in range(count)]
    for relro in (header for header in headers if header[0] == 0x6474e552):
        end = relro[3] + relro[6]
        protected_end = ((end + 16383) // 16384) * 16384
        for load in (header for header in headers if header[0] == 1 and header[1] & 2):
            if max(end, load[3]) < min(protected_end, load[3] + load[6]):
                return True
    return False


def inspect(apk, build_tools, allow_4kb=False):
    apk = apk.resolve()
    bad = []
    native_count = 0
    app_files = []
    relro_conflicts = []

    def inspect_library(name, raw):
        nonlocal native_count
        native_count += 1
        if struct.unpack_from('<H', raw, 18)[0] != 183:
            raise ValueError(f'Biblioteca não é ARM64: {name}')
        alignments = elf_load_alignments(raw)
        if not alignments or min(alignments) < 16384:
            bad.append(name)
        if elf_relro_conflicts(raw):
            relro_conflicts.append(name)

    def inspect_bundle(raw, prefix):
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r|*') as bundle:
            for member in bundle:
                if member.isfile():
                    if prefix == 'assets/private.tar':
                        app_files.append(member.name)
                    if member.name.endswith('.so'):
                        file = bundle.extractfile(member)
                        inspect_library(prefix + ':' + member.name, file.read())
    with ZipFile(apk) as archive:
        libraries = [name for name in archive.namelist() if name.startswith('lib/') and name.endswith('.so')]
        if not libraries:
            raise ValueError('APK sem bibliotecas nativas.')
        architectures = sorted({name.split('/')[1] for name in libraries})
        if architectures != ['arm64-v8a']:
            raise ValueError(f'Arquiteturas inesperadas: {architectures}')
        for name in libraries:
            raw = archive.read(name)
            if name.endswith('/libpybundle.so') and raw.startswith(b'\x1f\x8b'):
                inspect_bundle(raw, name)
            else:
                inspect_library(name, raw)
        if 'assets/private.tar' in archive.namelist():
            inspect_bundle(archive.read('assets/private.tar'), 'assets/private.tar')
    if bad and not allow_4kb:
        raise ValueError(f'Bibliotecas sem alinhamento ELF de 16 KB: {bad}')
    if relro_conflicts and not allow_4kb:
        raise ValueError(f'Conflitos RELRO de 16 KB: {relro_conflicts}')
    results = {}
    for name, command in {
        'signature': [build_tools / 'apksigner', 'verify', '--verbose', '--print-certs', apk],
        'zip_alignment': [build_tools / 'zipalign', '-c', '-P', '16', '-v', '4', apk],
        'manifest': [build_tools / 'aapt', 'dump', 'badging', apk],
    }.items():
        completed = subprocess.run(list(map(str, command)), capture_output=True, text=True)
        if completed.returncode:
            raise ValueError(f'Falha na verificação {name}: {completed.stdout[-3000:]} {completed.stderr[-3000:]}')
        results[name] = completed.stdout if name != 'zip_alignment' else 'OK'
    results.update({'apk': str(apk), 'bytes': apk.stat().st_size,
                    'sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
                    'architectures': architectures, 'native_libraries': native_count,
                    'elf_16kb_alignment': 'Pendente' if bad else 'OK',
                    'libraries_without_16kb_alignment': bad,
                    'relro_16kb_writable_overlap': relro_conflicts,
                    'demonstrations_included': any(name.startswith('samples/') for name in app_files),
                    'physical_tablet_test': 'Pendente'})
    return results


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--build-tools', required=True, type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--allow-4kb', action='store_true', help='Gera relatório de protótipo com pendências explícitas de 16 KB, sem considerá-las aprovadas.')
    args = parser.parse_args()
    report = json.dumps(inspect(args.apk, args.build_tools, allow_4kb=args.allow_4kb), ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(report + '\n', encoding='utf-8')
    print(report)


if __name__ == '__main__':
    main()
