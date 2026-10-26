"""Verifica os pacotes com o mesmo leitor jtar usado pelo bootstrap Android."""
import subprocess
import tempfile
from pathlib import Path


JAVA = r'''
import java.io.*;
import java.nio.file.*;
import java.util.zip.GZIPInputStream;
import org.kamranzafar.jtar.*;

public class CheckExtraction {
    public static void main(String[] args) throws Exception {
        Path root = Paths.get(args[1]).toAbsolutePath();
        int count = 0;
        try (TarInputStream tar = new TarInputStream(new BufferedInputStream(
                new GZIPInputStream(new FileInputStream(args[0]))))) {
            byte[] buffer = new byte[1024 * 1024];
            TarEntry entry;
            while ((entry = tar.getNextEntry()) != null) {
                Path output = root.resolve(entry.getName()).normalize();
                if (!output.startsWith(root)) throw new IOException("Unsafe path");
                if (entry.isDirectory()) {
                    Files.createDirectories(output);
                } else {
                    // Assim como AssetExtract, depende das entradas de diretório
                    // do pacote; não cria pastas extras para disfarçar erros.
                    try (OutputStream file = new BufferedOutputStream(Files.newOutputStream(output))) {
                        int length;
                        while ((length = tar.read(buffer)) != -1) file.write(buffer, 0, length);
                    }
                }
                count++;
            }
        }
        System.out.println("Extracted entries: " + count);
    }
}
'''


def check_extraction(work, project):
    source = work / 'app/.buildozer/android/platform/python-for-android/pythonforandroid/bootstraps/common/build/src/main/java/org/kamranzafar/jtar'
    packages = [project / 'libs/arm64-v8a/libpybundle.so', project / 'src/main/assets/private.tar']
    if not packages[1].is_file():
        packages[1] = project / 'assets/private.tar'
    with tempfile.TemporaryDirectory(prefix='extract-check-', dir=work) as temporary:
        root = Path(temporary)
        java = root / 'CheckExtraction.java'
        java.write_text(JAVA, encoding='utf-8')
        subprocess.run(['javac', '-d', str(root), *map(str, source.glob('*.java')), str(java)], check=True)
        results = []
        for index, archive in enumerate(packages):
            target = root / str(index)
            target.mkdir()
            result = subprocess.run(['java', '-cp', str(root), 'CheckExtraction', str(archive), str(target)],
                                    check=True, capture_output=True, text=True)
            results.append({'archive': archive.name, 'result': result.stdout.strip()})
        return results
