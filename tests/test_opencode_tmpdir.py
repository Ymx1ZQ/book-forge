import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import book_forge as bf  # noqa: E402


def test_each_call_has_its_own_tmpdir_removed_afterwards(tmp_path):
    argv = [sys.executable, "-c", "import os,sys;print(os.environ['TMPDIR']);open(os.path.join(os.environ['TMPDIR'],'x'),'w').write('1')"]
    result = bf._run_opencode_process(argv, cwd=tmp_path, env=dict(os.environ), timeout=30, what="t")
    used = result.stdout.strip()
    assert used and used != os.environ.get("TMPDIR")
    assert not Path(used).exists()


def test_tmpdir_removed_after_timeout(tmp_path):
    argv = [sys.executable, "-c", "import os,time;print(os.environ['TMPDIR'],flush=True);time.sleep(30)"]
    try:
        bf._run_opencode_process(argv, cwd=tmp_path, env=dict(os.environ), timeout=1, what="t")
    except bf.OpencodeTimeout as exc:
        used = exc.stdout.strip()
    else:
        raise AssertionError("expected a timeout")
    assert used and not Path(used).exists()
