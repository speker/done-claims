import math
import unittest

from doneclaims.stats import Table, mantel_haenszel, wilson


class WilsonTest(unittest.TestCase):
    def test_known_intervals(self):
        low, high = wilson(5, 10)
        self.assertAlmostEqual(low, 0.23659, places=4)
        self.assertAlmostEqual(high, 0.76341, places=4)
        self.assertEqual(wilson(0, 10)[0], 0.0)
        self.assertAlmostEqual(wilson(0, 10)[1], 0.27754, places=4)
        self.assertAlmostEqual(wilson(10, 10)[0], 0.72246, places=4)
        self.assertEqual(wilson(10, 10)[1], 1.0)

    def test_rejects_impossible_counts(self):
        for successes, n in ((1, 0), (-1, 5), (6, 5)):
            with self.assertRaises(ValueError):
                wilson(successes, n)


class MantelHaenszelTest(unittest.TestCase):
    def test_single_stratum_matches_woolf(self):
        result = mantel_haenszel([Table(10, 20, 30, 40)])
        self.assertAlmostEqual(result.estimate, 400 / 600)
        se = math.sqrt(1 / 10 + 1 / 20 + 1 / 30 + 1 / 40)
        self.assertAlmostEqual(result.low, math.exp(math.log(400 / 600) - 1.959963984540054 * se))
        self.assertAlmostEqual(result.high, math.exp(math.log(400 / 600) + 1.959963984540054 * se))

    def test_hand_computed_pooled_estimate(self):
        result = mantel_haenszel([Table(2, 3, 1, 4), Table(5, 5, 2, 8)])
        self.assertAlmostEqual(result.estimate, 3.5)
        self.assertEqual(result.informative_strata, 2)

    def test_stratification_removes_confounding_by_stratum(self):
        strata = [Table(90, 10, 9, 1), Table(1, 9, 10, 90)]
        crude = Table(91, 19, 19, 91)
        self.assertGreater(crude.a * crude.d / (crude.b * crude.c), 20)
        self.assertAlmostEqual(mantel_haenszel(strata).estimate, 1.0)

    def test_repeating_strata_keeps_estimate_and_narrows_interval(self):
        one = mantel_haenszel([Table(10, 20, 30, 40)])
        many = mantel_haenszel([Table(10, 20, 30, 40)] * 4)
        self.assertAlmostEqual(one.estimate, many.estimate)
        self.assertLess(many.high - many.low, one.high - one.low)

    def test_strata_without_contrast_are_skipped(self):
        result = mantel_haenszel([Table(10, 20, 30, 40), Table(3, 4, 0, 0), Table(0, 0, 0, 0)])
        self.assertEqual(result.informative_strata, 1)
        self.assertAlmostEqual(result.estimate, 400 / 600)

    def test_undefined_without_information(self):
        with self.assertRaises(ValueError):
            mantel_haenszel([Table(3, 4, 0, 0)])


if __name__ == "__main__":
    unittest.main()
