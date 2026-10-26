"""Valida os pacotes de compilação sem instalar ferramentas Android."""
from pathlib import Path
import sys
import tempfile
import unittest
import struct
import io
import gzip
import tarfile
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gerar_apk import validate_wheel
from qa.inspect_apk import elf_load_alignments, elf_relro_conflicts, inspect
from qa.finalize_android_package import replace_module
from qa.fix_android_activity import patch_activity, OLD, NEW
from qa.update_android_app import repack_application
from preparar_compilacao import unzip, configure_buildozer


class BuildTests(unittest.TestCase):
    def test_application_update_replaces_sources_removes_stale_bytecode_and_preserves_bootstrap(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            root = Path(folder)
            archive = root / 'private.tar'
            source = root / 'main.py'
            source.write_bytes(b'new code')
            with tarfile.open(archive, 'w:gz', format=tarfile.USTAR_FORMAT) as tar:
                for name, raw in {'main.py': b'old code', 'main.pyc': b'old bytecode', 'sitecustomize.py': b'bootstrap',
                                  'samples/freezer.txt': b'old sample', 'samples/camara_fria.txt': b'old sample'}.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(raw)
                    tar.addfile(member, io.BytesIO(raw))
            repack_application(archive, {'main.py': source})
            with tarfile.open(archive, 'r:gz') as tar:
                self.assertEqual(set(tar.getnames()), {'main.py', 'sitecustomize.py'})
                self.assertEqual(tar.extractfile('main.py').read(), b'new code')
                self.assertEqual(tar.extractfile('sitecustomize.py').read(), b'bootstrap')

    def test_qt_receives_activity_result_before_optional_listeners(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            path = Path(folder) / 'PythonActivity.java'
            path.write_text('class PythonActivity extends QtActivity {\n' + OLD + '    }\n}', encoding='utf-8')
            self.assertTrue(patch_activity(path))
            self.assertIn(NEW, path.read_text(encoding='utf-8'))
            self.assertFalse(patch_activity(path))
            path.write_text('class UnknownActivity {}', encoding='utf-8')
            with self.assertRaises(ValueError):
                patch_activity(path)

    def wheel(self, folder, package='PySide6', version='6.12.0', platform='android_35_arm64_v8a'):
        path = Path(folder) / f'{package}-{version}-{platform}.whl'
        with ZipFile(path, 'w') as archive:
            archive.writestr(f'{package}.dist-info/METADATA', f'Name: {package}\nVersion: {version}\n')
            archive.writestr(f'{package}.dist-info/WHEEL', f'Wheel-Version: 1.0\nTag: cp314-cp314-{platform}\n')
        return path

    def test_arm64_packages_match_tablet_target(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            for package in ('PySide6', 'shiboken6'):
                self.assertEqual(validate_wheel(self.wheel(folder, package), package, 'aarch64'), '6.12.0')

    def test_wrong_platform_version_or_package_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            for platform in ('win_amd64', 'manylinux_2_34_aarch64', 'android_35_x86_64'):
                with self.subTest(platform=platform), self.assertRaises(ValueError):
                    validate_wheel(self.wheel(folder, platform=platform), 'PySide6', 'aarch64')
            with self.assertRaises(ValueError):
                validate_wheel(self.wheel(folder, version='6.11.0'), 'PySide6', 'aarch64')
            with self.assertRaises(ValueError):
                validate_wheel(self.wheel(folder, package='shiboken6'), 'PySide6', 'aarch64')

    def test_x86_emulator_requires_explicit_target(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            self.assertEqual(validate_wheel(self.wheel(folder, platform='android_35_x86_64'), 'PySide6', 'x86_64'), '6.12.0')

    def test_native_16kb_alignment_and_rejection_of_old_4kb_library(self):
        raw = bytearray(120)
        raw[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', raw, 18, 183)
        struct.pack_into('<Q', raw, 32, 64)
        struct.pack_into('<HH', raw, 54, 56, 1)
        struct.pack_into('<I', raw, 64, 1)
        struct.pack_into('<Q', raw, 112, 16384)
        self.assertEqual(elf_load_alignments(raw), [16384])
        struct.pack_into('<Q', raw, 112, 4096)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            path = Path(folder) / 'old_alignment.apk'
            with ZipFile(path, 'w') as apk:
                apk.writestr('lib/arm64-v8a/libexample.so', raw)
            with self.assertRaisesRegex(ValueError, '16 KB'):
                inspect(path, Path(folder))

    def test_download_archive_cannot_escape_its_directory(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            path = Path(folder) / 'bad.zip'
            with ZipFile(path, 'w') as archive:
                archive.writestr('../outside.txt', 'invalid')
            with self.assertRaises(ValueError):
                unzip(path, Path(folder) / 'output')
            self.assertFalse((Path(folder) / 'outside.txt').exists())

    def test_build_configuration_preserves_internal_name_and_adds_demo_files(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            path = Path(folder) / 'buildozer.spec'
            path.write_text('[app]\npackage.name = NovaViewAndroidPrototype\ntitle = Old\nsource.include_exts = py,png,qml\norientation = portrait\n', encoding='utf-8')
            self.assertTrue(configure_buildozer(path))
            text = path.read_text(encoding='utf-8')
            self.assertIn('package.name = NovaViewAndroidPrototype', text)
            self.assertIn('source.include_exts = py,png,qml,txt', text)
            self.assertIn('landscape,portrait,landscape-reverse,portrait-reverse', text)
            self.assertFalse(configure_buildozer(path))

    def test_relro_does_not_protect_a_separate_writable_segment(self):
        raw = bytearray(64 + 56 * 3)
        raw[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<Q', raw, 32, 64)
        struct.pack_into('<HH', raw, 54, 56, 3)
        struct.pack_into('<IIQQQQQQ', raw, 64, 1, 6, 0, 0x8000, 0x8000, 0x1000, 0x1000, 16384)
        struct.pack_into('<IIQQQQQQ', raw, 120, 1, 6, 0, 0xa000, 0xa000, 0x1000, 0x1000, 16384)
        struct.pack_into('<IIQQQQQQ', raw, 176, 0x6474e552, 4, 0, 0x8000, 0x8000, 0x1000, 0x1000, 1)
        self.assertTrue(elf_relro_conflicts(raw))
        struct.pack_into('<Q', raw, 120 + 16, 0xc000)
        self.assertFalse(elf_relro_conflicts(raw))

    def test_repack_preserves_other_files_and_updates_integrity(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'qa') as folder:
            root = Path(folder)
            bundle = root / 'libpybundle.so'
            content = {'_python_bundle/site-packages/shiboken6/Shiboken.abi3.so': b'old',
                       '_python_bundle/site-packages/shiboken6-6.12.0.dist-info/RECORD': b'shiboken6/Shiboken.abi3.so,sha256=old,3\n',
                       'main.py': b'print(123)',
                       '_python_bundle/site-packages/PySide6/' + 'nested/' * 15 + 'example.qml': b'long path'}
            with tarfile.open(bundle, 'w:gz') as archive:
                for name, data in content.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            raw = bytearray(120)
            raw[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<Q', raw, 32, 64)
            struct.pack_into('<HH', raw, 54, 56, 1)
            struct.pack_into('<I', raw, 64, 1)
            struct.pack_into('<Q', raw, 112, 16384)
            module = root / 'Shiboken.abi3.so'
            module.write_bytes(raw)
            replace_module(bundle, module)
            # Inspeciona os blocos reais: leitores TAR simples do Android não
            # reconhecem PAX, mesmo quando tarfile consegue ler o resultado.
            with gzip.open(bundle, 'rb') as stream:
                while True:
                    header = stream.read(512)
                    if not header or header == bytes(512):
                        break
                    self.assertIn(header[156:157], (b'0', b'\0', b'5'))
                    size = int(header[124:136].rstrip(b'\0 '), 8)
                    stream.read((size + 511) // 512 * 512)
            with tarfile.open(bundle, 'r:gz') as archive:
                self.assertEqual(set(archive.getnames()), set(content))
                self.assertEqual(archive.extractfile('main.py').read(), content['main.py'])
                self.assertEqual(archive.extractfile('_python_bundle/site-packages/shiboken6/Shiboken.abi3.so').read(), raw)
                record = archive.extractfile('_python_bundle/site-packages/shiboken6-6.12.0.dist-info/RECORD').read()
                self.assertIn(b',120\n', record)
                self.assertNotIn(b'sha256=old', record)


if __name__ == '__main__':
    unittest.main()
