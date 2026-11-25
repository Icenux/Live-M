import os
import unittest

from livem import procs


def stat_line(pid, comm, utime, stime, rss_pages):
    # Fields 3..52 of /proc/<pid>/stat after "(comm) "; only utime(14), stime(15),
    # rss(24) matter, the rest is filler.
    rest = ['S'] + ['0'] * 49
    rest[11] = str(utime)
    rest[12] = str(stime)
    rest[21] = str(rss_pages)
    return f"{pid} ({comm}) {' '.join(rest)}\n".encode()


class ParseStatTests(unittest.TestCase):
    def test_plain(self):
        name, ticks, rss = procs.parse_stat(stat_line(1, "bash", 10, 5, 100))
        self.assertEqual((name, ticks, rss), ("bash", 15, 100 * procs.PAGE_SIZE))

    def test_name_with_spaces_and_parentheses(self):
        name, ticks, _ = procs.parse_stat(stat_line(2, "Web Content (x)", 3, 4, 1))
        self.assertEqual((name, ticks), ("Web Content (x)", 7))

    def test_garbage_returns_none(self):
        self.assertIsNone(procs.parse_stat(b"not a stat line"))
        self.assertIsNone(procs.parse_stat(b"1 (x) S 0"))

    def test_reads_own_process(self):
        snap = procs.read_all()
        self.assertIn(os.getpid(), snap)


class ComputeTests(unittest.TestCase):
    def test_cpu_percent_of_one_core(self):
        prev = {1: ("a", 0, 10)}
        cur = {1: ("a", procs.CLK_TCK * 2, 10)}   # 2 s of CPU ...
        rows = procs.compute(prev, cur, dt=4.0)    # ... in 4 s -> 50 %
        self.assertAlmostEqual(rows[0].cpu, 50.0)

    def test_new_process_and_pid_reuse_get_zero(self):
        prev = {1: ("a", 1000, 1)}
        cur = {1: ("b", 5, 1), 2: ("c", 50, 1)}    # pid 1 counter went backwards
        by_pid = {r.pid: r for r in procs.compute(prev, cur, dt=1.0)}
        self.assertEqual(by_pid[1].cpu, 0.0)
        self.assertEqual(by_pid[2].cpu, 0.0)

    def test_top_skips_zero_and_limits(self):
        rows = [procs.ProcInfo(i, f"p{i}", float(i), 0) for i in range(10)]
        best = procs.top(rows, 3, "cpu")
        self.assertEqual([r.pid for r in best], [9, 8, 7])
        self.assertEqual(procs.top(rows, 3, "rss"), [])


class SamplerTests(unittest.TestCase):
    def test_ready_after_second_snapshot_only(self):
        s = procs.ProcSampler(ttl=3.0)
        s.poll(now=100.0)
        self.assertFalse(s.ready)
        s.poll(now=100.2)               # too early (FIRST_DELAY = 1 s)
        self.assertFalse(s.ready)
        s.poll(now=101.1)
        self.assertTrue(s.ready)

    def test_respects_ttl_after_ready(self):
        s = procs.ProcSampler(ttl=3.0)
        s.poll(now=0.0)
        s.poll(now=1.5)
        self.assertTrue(s.ready)
        before = s._prev_t
        s.poll(now=3.0)                 # only 1.5 s since last sample
        self.assertEqual(s._prev_t, before)
        s.poll(now=4.6)
        self.assertEqual(s._prev_t, 4.6)


if __name__ == "__main__":
    unittest.main()
