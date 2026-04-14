import ipaddress
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "speech-app"))

from robot_client import _pick_data_ports, active_hello_probe, discover_usb_robots  # noqa: E402


def make_port(device: str, serial_number: str, interface: str | None):
    return SimpleNamespace(
        device=device,
        serial_number=serial_number,
        interface=interface,
        vid=0x2E8A,
    )


class PickDataPortsTests(unittest.TestCase):
    def test_prefers_non_board_cdc_port_per_device(self):
        ports = [
            make_port("/dev/ttyACM0", "A", "Board CDC"),
            make_port("/dev/ttyACM1", "A", "Data CDC"),
            make_port("/dev/ttyACM2", "B", "Board CDC"),
            make_port("/dev/ttyACM3", "B", None),
        ]

        self.assertEqual(
            ["/dev/ttyACM1", "/dev/ttyACM3"],
            _pick_data_ports(ports),
        )

    def test_falls_back_to_only_port_when_device_has_single_interface(self):
        ports = [make_port("/dev/ttyACM0", "A", "Board CDC")]
        self.assertEqual(["/dev/ttyACM0"], _pick_data_ports(ports))


class ActiveHelloProbeTests(unittest.TestCase):
    def test_collects_all_successful_probes(self):
        network = ipaddress.ip_network("192.168.1.0/30")
        robots_by_host = {
            "192.168.1.1": {"host": "192.168.1.1", "port": 8080, "device_id": "robot-1"},
            "192.168.1.2": {"host": "192.168.1.2", "port": 8080, "device_id": "robot-2"},
        }

        with (
            mock.patch("robot_client.probe_networks", return_value=[network]),
            mock.patch("robot_client.hello_probe", side_effect=lambda host, port: robots_by_host.get(host)),
        ):
            robots = active_hello_probe([8080])

        self.assertEqual({"robot-1", "robot-2"}, {robot["device_id"] for robot in robots})


class DiscoverUsbRobotsTests(unittest.TestCase):
    def test_discovers_each_usb_robot_once(self):
        ports = [
            make_port("/dev/ttyACM0", "A", "Board CDC"),
            make_port("/dev/ttyACM1", "A", "Data CDC"),
            make_port("/dev/ttyACM2", "B", "Board CDC"),
            make_port("/dev/ttyACM3", "B", "Data CDC"),
        ]

        def fake_get_transport(config):
            serial_port = config["serial_port"]

            class FakeTransport:
                def request(self, method, path):
                    return {
                        "device_name": f"Robot {serial_port[-1]}",
                        "device_id": f"device-{serial_port[-1]}",
                        "paired": False,
                        "serial_framing": True,
                    }

            return FakeTransport()

        with (
            mock.patch("robot_client._list_pico_ports", return_value=ports),
            mock.patch("robot_client.get_transport", side_effect=fake_get_transport),
            mock.patch("robot_client.close_transport"),
        ):
            robots = discover_usb_robots()

        self.assertEqual(
            {"/dev/ttyACM1", "/dev/ttyACM3"},
            {robot["serial_port"] for robot in robots},
        )
        self.assertEqual(
            {"device-1", "device-3"},
            {robot["device_id"] for robot in robots},
        )


if __name__ == "__main__":
    unittest.main()
