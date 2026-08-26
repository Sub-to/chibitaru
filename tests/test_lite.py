#!/usr/bin/env python3
"""
軽量モード（MYLN-FRAME 純Pythonコア）のテスト
================================================
外部依存なし。llama-server もモデルファイルも不要。

実行:
    python3 -m unittest discover -s tests -v
    python3 tests/test_lite.py
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

AOKO = Path(__file__).resolve().parent.parent / "aoko"
sys.path.insert(0, str(AOKO))

# 軽量モードを強制（native があるマシンでも純Pythonを検証する）
os.environ["CHIBITARU_ENGINE"] = "python"

from feature_extractor import extract           # noqa: E402
from myln_py import PyMylnFrame, risk_score     # noqa: E402


class TestRiskScore(unittest.TestCase):
    """危険度スコアの基本性質。"""

    def test_zero_is_zero(self):
        self.assertEqual(risk_score([0.0] * 5), 0.0)

    def test_bounded_0_to_1(self):
        for feats in ([1.0] * 5, [0.5] * 5, [0.0] * 5, [2.0] * 5, [-1.0] * 5):
            s = risk_score(feats)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_monotonic_in_each_feature(self):
        """どの特徴量を上げてもスコアは下がらない。"""
        base = [0.1] * 5
        for i in range(5):
            hi = list(base)
            hi[i] = 0.9
            self.assertGreaterEqual(risk_score(hi), risk_score(base))

    def test_breadth_bonus(self):
        """同じ合計でも、複数指標が同時に立つ方が危険と判定される。"""
        concentrated = risk_score([1.0, 0.0, 0.0, 0.0, 0.0])
        spread = risk_score([0.6, 0.6, 0.6, 0.6, 0.6])
        self.assertGreater(spread, concentrated)

    def test_short_vector_does_not_crash(self):
        self.assertGreaterEqual(risk_score([0.5]), 0.0)
        self.assertEqual(risk_score([]), 0.0)


class TestPyMylnFrame(unittest.TestCase):
    """純Python推論コアの API 互換性。"""

    def setUp(self):
        self.frame = PyMylnFrame(size="T", n_classes=5).tune_security(in_dim=5)

    def test_probs_form_distribution(self):
        probs = self.frame.infer([0.5] * 5)
        self.assertEqual(len(probs), 5)
        self.assertAlmostEqual(sum(probs), 1.0, places=6)
        for p in probs:
            self.assertGreaterEqual(p, 0.0)

    def test_predict_matches_argmax(self):
        feats = [0.8, 0.5, 0.0, 0.0, 0.0]
        probs = self.frame.infer(feats)
        expected = PyMylnFrame.SECURITY_CLASSES[probs.index(max(probs))]
        self.assertEqual(self.frame.predict(feats), expected)

    def test_predict_with_score(self):
        level, p = self.frame.predict_with_score([0.9, 0.9, 0.7, 0.95, 0.75])
        self.assertEqual(level, "CRITICAL")
        self.assertGreater(p, 0.5)

    def test_metadata(self):
        self.assertEqual(self.frame.dim, 5)
        self.assertEqual(self.frame.n_classes, 5)
        self.assertIn("MYLN", self.frame.tag)
        self.assertTrue(self.frame.version)

    def test_deterministic(self):
        feats = [0.3, 0.7, 0.2, 0.4, 0.1]
        self.assertEqual(self.frame.infer(feats), self.frame.infer(feats))


class TestEventLevels(unittest.TestCase):
    """monitor.py が出すイベントが妥当なレベルに落ちるか。"""

    def setUp(self):
        self.frame = PyMylnFrame().tune_security(in_dim=5)

    def _level(self, event):
        return self.frame.predict(extract(event))

    def test_quiet_system_is_safe(self):
        self.assertEqual(self.frame.predict([0.0] * 5), "SAFE")

    def test_ransomware_is_critical(self):
        self.assertEqual(self._level({
            "type": "ransomware_pattern",
            "detail": "大量ファイル暗号化試行を検出",
        }), "CRITICAL")

    def test_vault_mass_change_is_high(self):
        self.assertEqual(self._level({
            "type": "vault_mass_change",
            "detail": "Vault内ファイルが急増変化: 38件（ランサムウェア疑い）",
            "count": 38,
        }), "HIGH")

    def test_backdoor_port_is_at_least_medium(self):
        level = self._level({
            "type": "suspicious_network",
            "detail": "バックドアポート接続疑い: 10.0.0.1:4444 ESTABLISHED",
            "port": 4444,
        })
        self.assertIn(level, ("MEDIUM", "HIGH", "CRITICAL"))

    def test_severity_ordering(self):
        """深刻なイベントほど高いスコアになる。"""
        order = ["ai_injection", "vault_mass_change", "ransomware_pattern"]
        scores = [risk_score(extract({"type": t, "detail": "", "count": 38})) for t in order]
        self.assertEqual(scores, sorted(scores))


class TestConductorContract(unittest.TestCase):
    """myln_conductor.judge() が conductor.judge() と同じ形を返すか。"""

    def test_judge_shape(self):
        import myln_conductor
        self.assertEqual(myln_conductor.backend(), "python")

        result = myln_conductor.judge({
            "type": "ransomware_pattern",
            "detail": "大量ファイル暗号化試行を検出",
        })
        for key in ("level", "action", "event", "verdicts"):
            self.assertIn(key, result)
        self.assertIn(result["level"], ["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"])
        self.assertTrue(result["action"])
        self.assertEqual(len(result["verdicts"]), 4)
        for v in result["verdicts"]:
            self.assertIn("agent", v)
            self.assertIn("level", v)
            self.assertIn("reason", v)

    def test_no_llm_required(self):
        """軽量モードでは llama-server に一切アクセスしない。"""
        import urllib.request
        import myln_conductor

        def _boom(*a, **kw):
            raise AssertionError("軽量モードなのにネットワークへアクセスした")

        original = urllib.request.urlopen
        urllib.request.urlopen = _boom
        try:
            myln_conductor.judge({"type": "suspicious_process", "detail": "test"})
        finally:
            urllib.request.urlopen = original


class TestVaultProtection(unittest.TestCase):
    """Vault 保護が「保護したまま元に戻せる」ことを確認する。"""

    def test_protect_and_restore_keeps_tree_traversable(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            (vault / "sub").mkdir(parents=True)
            note = vault / "sub" / "note.md"
            note.write_text("hello", encoding="utf-8")

            os.environ["CHIBITARU_VAULT"] = str(vault)
            for mod in ("response",):
                sys.modules.pop(mod, None)
            import response

            self.assertTrue(response.make_vault_readonly())
            # ディレクトリは辿れたまま（x ビットが残っている）
            self.assertTrue(os.stat(vault / "sub").st_mode & stat.S_IXUSR)
            # ファイルは書き込み不可
            self.assertFalse(os.stat(note).st_mode & stat.S_IWUSR)
            # 読み出しはできる
            self.assertEqual(note.read_text(encoding="utf-8"), "hello")

            self.assertTrue(response.restore_vault_writable())
            self.assertTrue(os.stat(note).st_mode & stat.S_IWUSR)
            self.assertTrue(os.stat(vault / "sub").st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
