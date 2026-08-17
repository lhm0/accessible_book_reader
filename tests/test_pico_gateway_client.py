import termios
import unittest

from abr.hardware.pico_gateway_client import baudrate_to_termios


class PicoGatewayClientTests(unittest.TestCase):
    def test_baudrate_to_termios_maps_115200(self) -> None:
        self.assertEqual(baudrate_to_termios(115200), termios.B115200)

    def test_baudrate_to_termios_rejects_unknown_rate(self) -> None:
        with self.assertRaises(ValueError):
            baudrate_to_termios(12345)


if __name__ == "__main__":
    unittest.main()
