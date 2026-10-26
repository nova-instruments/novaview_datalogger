"""Corrige o encaminhamento de resultados do bootstrap python-for-android ao Qt."""
from pathlib import Path
import subprocess
import tempfile


OLD = '''    protected void onActivityResult(int requestCode, int resultCode, Intent intent) {
        if (this.activityResultListeners == null) return;
        this.onResume();
'''
NEW = '''    protected void onActivityResult(int requestCode, int resultCode, Intent intent) {
        // Qt encerra o seletor nativo e entrega a URL ao FileDialog.
        super.onActivityResult(requestCode, resultCode, intent);
        if (this.activityResultListeners == null) return;
'''


def patch_activity(path):
    source = path.read_text(encoding='utf-8')
    if NEW in source:
        return False
    if 'extends QtActivity' not in source or source.count(OLD) != 1:
        raise ValueError(f'Bootstrap Qt diferente do esperado: {path}')
    path.write_text(source.replace(OLD, NEW), encoding='utf-8')
    return True


def check_dispatch(path, work):
    """Executa o método real com um receptor Qt simulado, sem aparelho conectado."""
    source = path.read_text(encoding='utf-8')
    begin = source.index('    protected void onActivityResult(')
    end = source.index('\n    public static void start_service(', begin)
    method = source[begin:end]
    harness = '''
import java.util.*;
class Intent {}
class QtActivity {
    int calls = 0;
    protected void onActivityResult(int request, int result, Intent intent) { calls++; }
}
public class CheckActivity extends QtActivity {
    interface ActivityResultListener { void onActivityResult(int request, int result, Intent intent); }
    List<ActivityResultListener> activityResultListeners;
    void onResume() { throw new AssertionError("Manual lifecycle call"); }
''' + method + '''
    public static void main(String[] args) {
        CheckActivity activity = new CheckActivity();
        activity.onActivityResult(1, -1, new Intent());
        activity.onActivityResult(2, 0, null);
        if (activity.calls != 2) throw new AssertionError("Qt did not receive selection/cancellation");
        int[] received = {0};
        activity.activityResultListeners = new ArrayList<>();
        activity.activityResultListeners.add((request, result, data) -> {
            if (request != 3 || result != -1 || data == null) throw new AssertionError("Invalid result");
            received[0]++;
        });
        activity.onActivityResult(3, -1, new Intent());
        if (activity.calls != 3 || received[0] != 1) throw new AssertionError("Listener result lost");
        System.out.println("OK: selection, cancellation, repeated requests and existing listeners");
    }
}
'''
    with tempfile.TemporaryDirectory(prefix='activity-check-', dir=work) as temporary:
        root = Path(temporary)
        java = root / 'CheckActivity.java'
        java.write_text(harness, encoding='utf-8')
        subprocess.run(['javac', str(java)], check=True)
        result = subprocess.run(['java', '-cp', str(root), 'CheckActivity'], check=True, capture_output=True, text=True)
        return result.stdout.strip()


def prepare_activity(work, project):
    activity = project / 'src/main/java/org/kivy/android/PythonActivity.java'
    template = work / 'app/.buildozer/android/platform/python-for-android/pythonforandroid/bootstraps/qt/build/src/main/java/org/kivy/android/PythonActivity.java'
    patch_activity(activity)
    patch_activity(template)
    return check_dispatch(activity, work)
