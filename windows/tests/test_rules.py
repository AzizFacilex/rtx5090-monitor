"""The ported rules must agree with astral-guard on its own corpus.

tests/data/guard-cases.jsonl is copied verbatim from
https://github.com/ksokolowski/astral-hwmon (MIT). Run: python -m unittest discover -s tests
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import astral_core as core  # noqa: E402

CORPUS = Path(__file__).parent / "data" / "guard-cases.jsonl"
EXPECT = {"OK": core.OK, "WARN": core.WARN, "CRIT": core.CRIT, "UNKNOWN": core.UNKNOWN}


def spread(flat, n):
    """6 values apply to every sample, 6*n give one block each (corpus.c)."""
    assert len(flat) in (6, 6 * n)
    return [flat] * n if len(flat) == 6 else [flat[i * 6:i * 6 + 6] for i in range(n)]


class Corpus(unittest.TestCase):
    def test_every_case(self):
        cases = [json.loads(l) for l in CORPUS.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreater(len(cases), 10)
        for c in cases:
            with self.subTest(c["note"]):
                n = c["samples"]
                samples = list(zip(spread(c["mv"], n), spread(c["ma"], n)))
                level, findings = core.evaluate(samples)
                self.assertEqual(level, EXPECT[c["expect"]])
                has_note = any(f["level"] == "NOTE" for f in findings)
                self.assertEqual(has_note, bool(c.get("expect_note")))


class Behaviour(unittest.TestCase):
    HEALTHY = [7640, 7840, 8300, 7920, 8560, 8020]

    def test_note_never_raises_level(self):
        level, f = core.evaluate([(None, [6900] * 3 + [8200] * 3)] * 5)
        self.assertEqual(level, core.OK)
        self.assertEqual([x["level"] for x in f], ["NOTE"])

    def test_no_voltage_skips_r4_only(self):
        self.assertEqual(core.evaluate([(None, self.HEALTHY)] * 5)[0], core.OK)
        crit = list(self.HEALTHY)
        crit[4] = 9600
        self.assertEqual(core.evaluate([(None, crit)] * 5)[0], core.CRIT)

    def test_single_sample_spike_does_not_alarm(self):
        spike = list(self.HEALTHY)
        spike[0] = 12000
        runs = [(None, self.HEALTHY)] * 4 + [(None, spike)]
        self.assertEqual(core.evaluate(runs)[0], core.OK)


class Classify(unittest.TestCase):
    CFG = core.DEFAULT_CONFIG

    def entries(self, amps, volts=None, comma=False):
        out, i = [], 0
        for p, a in enumerate(amps, 1):
            raw = f"{a:.3f}".replace(".", "," if comma else ".")
            out.append(dict(index=i, sensor="ASUS ROG ASTRAL RTX 5090", label=f"12V-2x6 Pin{p} Current",
                            value=f"{raw} A", raw=raw)); i += 1
        for p, v in enumerate(volts or [], 1):
            raw = f"{v:.3f}".replace(".", "," if comma else ".")
            out.append(dict(index=i, sensor="ASUS ROG ASTRAL RTX 5090", label=f"Pin #{p} Voltage",
                            value=f"{raw} V", raw=raw)); i += 1
        out.append(dict(index=i, sensor="CPU", label="Core 1 Clock", value="5400.0 MHz", raw="5400.0"))
        return out

    def test_full_read(self):
        ma, mv, err, _ = core.classify(self.entries([8.3] * 6, [12.1] * 6), self.CFG)
        self.assertIsNone(err)
        self.assertEqual(ma, [8300] * 6)
        self.assertEqual(mv, [12100] * 6)

    def test_german_decimal_comma(self):
        ma, mv, err, _ = core.classify(self.entries([8.3] * 6, [12.104] * 6, comma=True), self.CFG)
        self.assertIsNone(err)
        self.assertEqual(mv, [12104] * 6)

    def test_currents_without_voltages(self):
        ma, mv, err, _ = core.classify(self.entries([1.5] * 6), self.CFG)
        self.assertIsNone(err)
        self.assertIsNone(mv)

    def test_partial_read_fails_whole_sample(self):
        ma, mv, err, _ = core.classify(self.entries([8.3] * 5), self.CFG)
        self.assertIsNone(ma)
        self.assertIn("5 of 6", err)

    def test_implausible_rejected(self):
        ma, _, err, _ = core.classify(self.entries([8.3] * 5 + [99.0]), self.CFG)
        self.assertIsNone(ma)
        self.assertIn("implausible", err)

    def test_duplicate_pin_rejected(self):
        e = self.entries([8.3] * 6)
        e.append(dict(e[0], index=99))
        self.assertIn("twice", core.classify(e, self.CFG)[2])


if __name__ == "__main__":
    unittest.main()
