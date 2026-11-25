import os
import tempfile
import unittest

from livem.app import _find_wifi_iface


class FakeSysfs:
    """Minimal /sys/class/net tree in a temp dir."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def add(self, name, wireless=False, phy=False, state="up"):
        base = os.path.join(self.root, name)
        os.makedirs(base)
        if wireless:
            os.makedirs(os.path.join(base, "wireless"))
        if phy:
            open(os.path.join(base, "phy80211"), "w").close()
        if state is not None:
            with open(os.path.join(base, "operstate"), "w") as f:
                f.write(state + "\n")

    def close(self):
        self._tmp.cleanup()


class FindWifiTests(unittest.TestCase):
    def setUp(self):
        self.sys = FakeSysfs()
        self.addCleanup(self.sys.close)

    def find(self, names):
        return _find_wifi_iface({n: None for n in names}, sysfs=self.sys.root)

    def test_detects_by_kernel_marker_not_by_name(self):
        self.sys.add("lo", state="unknown")
        self.sys.add("eth0")
        self.sys.add("netradio7", wireless=True)           # custom name
        self.assertEqual(self.find(["lo", "eth0", "netradio7"]), "netradio7")

    def test_phy80211_marker_is_enough(self):
        self.sys.add("lan0")
        self.sys.add("fastnet", phy=True)
        self.assertEqual(self.find(["lan0", "fastnet"]), "fastnet")

    def test_name_alone_is_not_wifi_when_sysfs_knows_better(self):
        self.sys.add("wlan-bridge")                        # looks wireless, is not
        self.sys.add("radio0", wireless=True)
        self.assertEqual(self.find(["wlan-bridge", "radio0"]), "radio0")

    def test_prefers_interface_that_is_up(self):
        self.sys.add("wlp1s0", wireless=True, state="down")
        self.sys.add("wlp2s0", wireless=True, state="up")
        self.assertEqual(self.find(["wlp1s0", "wlp2s0"]), "wlp2s0")

    def test_all_down_still_returns_first_wireless(self):
        self.sys.add("wlp2s0", wireless=True, state="down")
        self.sys.add("wlp1s0", wireless=True, state="down")
        self.assertEqual(self.find(["wlp2s0", "wlp1s0"]), "wlp1s0")

    def test_no_sysfs_info_falls_back_to_name(self):
        # nothing in the fake tree: behaves like the old name guess
        self.assertEqual(self.find(["eth0", "wlan0"]), "wlan0")
        self.assertEqual(self.find(["eth0", "wwan0"]), "wwan0")

    def test_none_found(self):
        self.sys.add("lo", state="unknown")
        self.sys.add("eth0")
        self.assertEqual(self.find(["lo", "eth0"]), "")


if __name__ == "__main__":
    unittest.main()
