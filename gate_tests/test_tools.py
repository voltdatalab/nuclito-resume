"""Offline tests of gate tooling; never invoke Docker or a database."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('count,child,ok', [
    (15, '', True), (0, '', False), (14, '', False),
    (15, '<skipped/>', False), (15, '<failure/>', False), (15, '<error/>', False),
])
def test_mysql_receipt_rejects_missing_or_non_green_cases(tmp_path, count, child, ok):
    receipt = tmp_path / 'synthetic.xml'
    receipt.write_text('<testsuites><testsuite>' +
                       ''.join(f'<testcase name="fixture{i}">{child if i == 0 else ""}</testcase>'
                               for i in range(count)) + '</testsuite></testsuites>')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_mysql_receipt.py'), str(receipt)],
                            capture_output=True, text=True, timeout=5)
    assert (result.returncode == 0) is ok


def test_smoke_refuses_execution_outside_hosted_ci(monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/container_smoke.py'),
                             '--image', 'synthetic', '--mysql-container', 'synthetic'],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert 'Only disposable GitHub-hosted CI runners' in result.stderr
