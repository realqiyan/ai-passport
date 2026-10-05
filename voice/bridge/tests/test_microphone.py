import unittest
from voice_bridge import microphone

class FakeHal:
    def __init__(self, names, uids=None, default=0):
        self.names = dict(names)
        self.uids = dict(uids or {})
        self.current = default

    def find(self, wanted):
        if wanted in self.names:
            return self.names[wanted]
        folded = [d for n, d in self.names.items() if n.casefold() == wanted.casefold()]
        return folded[0] if len(folded) == 1 else None

    def uid(self, device):
        return self.uids.get(device)

    def default_input(self):
        return self.current

    def name(self, device):
        for title, identifier in self.names.items():
            if identifier == device:
                return title
        return None

class FakeAggregates:
    def __init__(self, device=120, create_status=0, destroy_status=0):
        self.device = device
        self.create_status = create_status
        self.destroy_status = destroy_status
        self.created = []
        self.destroyed = []

    def create(self, description):
        self.created.append(description)
        if self.create_status:
            raise RuntimeError(f"status {self.create_status}")
        return self.device

    def destroy(self, device):
        self.destroyed.append(device)
        if self.destroy_status:
            raise RuntimeError(f"status {self.destroy_status}")

def hal(with_mic=True):
    names = {"BlackHole 2ch": 102, "MacBook Pro麦克风": 97}
    if with_mic:
        names["Passport Mic"] = 120
    return FakeHal(names, {102: "BlackHole2ch_UID"}, 97)

class DescriptionTests(unittest.TestCase):
    def test_description_matches_the_coreaudio_key_names(self):
        self.assertEqual(microphone.description("Probe", "com.example.probe", "BlackHole2ch_UID"), {
            "name": "Probe",
            "uid": "com.example.probe",
            "private": False,
            "stacked": False,
            "subdevices": [{"uid": "BlackHole2ch_UID"}],
        })

    def test_description_is_not_private_so_the_device_survives_a_restart(self):
        self.assertFalse(microphone.description("Probe", "x", "y")["private"])

class DescribeTests(unittest.TestCase):
    def test_reports_every_device_of_the_chain(self):
        lines = microphone.describe(hal())
        self.assertIn("BlackHole 2ch: present (device 102)", lines)
        self.assertIn("Passport Mic: present (device 120)", lines)
        self.assertIn("Default input: MacBook Pro麦克风", lines)

    def test_reports_a_missing_aggregate(self):
        self.assertIn("Passport Mic: missing", microphone.describe(hal(with_mic=False)))

class CreateTests(unittest.TestCase):
    def test_creates_the_aggregate_from_the_subdevice_uid(self):
        aggregates = FakeAggregates()
        device = microphone.create(hal(with_mic=False), aggregates)
        self.assertEqual(device, 120)
        self.assertEqual(aggregates.created,
                         [microphone.description("Passport Mic",
                                                 "com.ai-passport.aggregate.mic",
                                                 "BlackHole2ch_UID")])

    def test_existing_device_is_not_replaced(self):
        aggregates = FakeAggregates()
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            microphone.create(hal(), aggregates)
        self.assertEqual(aggregates.created, [])

    def test_missing_subdevice_names_the_install_command(self):
        missing = FakeHal({"MacBook Pro麦克风": 97}, default=97)
        with self.assertRaisesRegex(RuntimeError, "blackhole-2ch"):
            microphone.create(missing, FakeAggregates())

    def test_subdevice_without_a_uid_reports_an_error(self):
        no_uid = FakeHal({"BlackHole 2ch": 102}, default=97)
        with self.assertRaisesRegex(RuntimeError, "identifier"):
            microphone.create(no_uid, FakeAggregates())

    def test_coreaudio_failure_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "status 560947818"):
            microphone.create(hal(with_mic=False), FakeAggregates(create_status=560947818))

class RemoveTests(unittest.TestCase):
    def test_removes_the_aggregate(self):
        aggregates = FakeAggregates()
        microphone.remove(hal(), aggregates)
        self.assertEqual(aggregates.destroyed, [120])

    def test_refuses_to_remove_the_default_input(self):
        aggregates = FakeAggregates()
        with self.assertRaisesRegex(RuntimeError, "default input"):
            microphone.remove(FakeHal({"Passport Mic": 120}, default=120), aggregates)
        self.assertEqual(aggregates.destroyed, [])

    def test_missing_device_reports_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "Passport Mic"):
            microphone.remove(hal(with_mic=False), FakeAggregates())

    def test_coreaudio_failure_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "560947818"):
            microphone.remove(hal(), FakeAggregates(destroy_status=560947818))

class FakeFramework:
    def __init__(self, create=(0, 120), destroy=0):
        self.create_result = create
        self.destroy_result = destroy
        self.calls = []

    def AudioHardwareCreateAggregateDevice(self, description, out):
        self.calls.append(("create", description, out))
        return self.create_result

    def AudioHardwareDestroyAggregateDevice(self, device):
        self.calls.append(("destroy", device))
        return self.destroy_result

class AggregateHalTests(unittest.TestCase):
    """The pyobjc binding returns a (status, device) pair and takes a null out argument."""

    def test_create_returns_the_new_device_identifier(self):
        framework = FakeFramework(create=(0, 153))
        self.assertEqual(microphone.AggregateHal(framework).create({"name": "Probe"}), 153)
        self.assertEqual(framework.calls, [("create", {"name": "Probe"}, None)])

    def test_create_reports_a_coreaudio_status(self):
        with self.assertRaisesRegex(RuntimeError, "560947818"):
            microphone.AggregateHal(FakeFramework(create=(560947818, 0))).create({})

    def test_destroy_passes_the_device_identifier(self):
        framework = FakeFramework()
        microphone.AggregateHal(framework).destroy(120)
        self.assertEqual(framework.calls, [("destroy", 120)])

    def test_destroy_reports_a_coreaudio_status(self):
        with self.assertRaisesRegex(RuntimeError, "560947818"):
            microphone.AggregateHal(FakeFramework(destroy=560947818)).destroy(120)

if __name__ == "__main__":
    unittest.main()
