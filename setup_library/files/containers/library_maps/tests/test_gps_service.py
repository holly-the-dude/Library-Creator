"""Run with: python3 -m unittest discover -s tests -v (no GPS or pySerial needed).

State tests use a controllable clock; monitor tests substitute discovery and
serial reads. HTTP tests use a real temporary loopback socket, so the test runner
must be allowed to bind localhost even though no external network is used.
"""

import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gps_service import GPSMonitor, GPSState, MAX_SENTENCE_BYTES, create_server
from read_gps import detect_port


def nmea(body):
    """Build a checksummed wire sentence so each test can vary semantic fields."""
    checksum = 0
    for byte in body.encode("ascii"):
        checksum ^= byte
    return f"${body}*{checksum:02X}\r\n".encode("ascii")


# GGA and RMC report the same known position; GSV fixtures report independent
# GPS (GP) and GLONASS (GL) totals. These are synthetic inputs, not live GPS data.
GGA = "GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,"
RMC = "GPRMC,123519,A,4807.038,N,01131.000,E,0,0,230394,,,A"
GSV_GP = "GPGSV,2,1,08,01,40,083,41,02,17,308,42,03,10,150,40,04,05,200,30"
GSV_GL = "GLGSV,2,1,06,65,40,083,41,66,17,308,42,67,10,150,40,68,05,200,30"
PORTS = [("/dev/test-gps", "u-blox GPS", True)]


class StateTests(unittest.TestCase):
    """Check fix validity and diagnostics independently of serial transport."""
    def setUp(self):
        self.now = 100.0
        self.state = GPSState(clock=lambda: self.now)
        self.state.scanned(PORTS, True, PORTS[0][0])
        self.state.connected()

    def test_valid_fix_includes_position_and_diagnostics(self):
        self.state.sentence(nmea(GGA))
        state = self.state.snapshot()
        self.assertEqual(state["status"], "fix")
        self.assertTrue(state["fix_valid"])
        self.assertTrue(state["gps_detected"])
        self.assertAlmostEqual(state["latitude"], 48.1173)
        self.assertAlmostEqual(state["longitude"], 11.5166666667)
        self.assertEqual(state["satellites_used"], 8)
        self.assertEqual(state["hdop"], 0.9)
        self.assertEqual(state["altitude_m"], 545.4)

    def test_no_fix_sentences_immediately_invalidate_last_position(self):
        # Exercise no-fix, dead-reckoning, void RMC and invalid mode reports
        # without advancing time: rejection must not wait for the age timeout.
        invalid_sentences = [GGA.replace(",E,1,08,", ",E,0,00,"),
                             GGA.replace(",E,1,08,", ",E,6,08,"),
                             RMC.replace(",A,4807", ",V,4807"),
                             RMC[:-1] + "N", RMC[:-1] + "E"]
        for invalid in invalid_sentences:
            with self.subTest(sentence=invalid):
                self.state.sentence(nmea(GGA))
                self.state.sentence(nmea(invalid))
                state = self.state.snapshot()
                self.assertFalse(state["fix_valid"])
                self.assertEqual(state["status"], "no_fix")
                self.assertAlmostEqual(state["latitude"], 48.1173)
                self.assertEqual(state["fix_age_seconds"], 0)

    def test_valid_rmc_recovers_after_invalid_gga(self):
        self.state.sentence(nmea(GGA.replace(",E,1,08,", ",E,0,00,")))
        self.state.sentence(nmea(RMC))
        self.assertTrue(self.state.snapshot()["fix_valid"])

    def test_gsv_data_does_not_refresh_a_position(self):
        self.state.sentence(nmea(GGA))
        self.now += 10
        self.assertTrue(self.state.snapshot()["fix_valid"])
        self.now += 0.1
        self.state.received_data()
        self.state.sentence(nmea(GSV_GP))
        state = self.state.snapshot()
        self.assertEqual(state["status"], "stale")
        self.assertFalse(state["fix_valid"])
        self.assertAlmostEqual(state["fix_age_seconds"], 10.1)
        self.assertEqual(state["last_data_age_seconds"], 0)

    def test_gsv_without_position_proves_gps_but_does_not_invent_a_fix(self):
        self.state.sentence(nmea(GSV_GP))
        state = self.state.snapshot()
        self.assertTrue(state["gps_detected"])
        self.assertFalse(state["fix_valid"])
        self.assertIsNone(state["latitude"])
        self.assertIsNone(state["fix_age_seconds"])

    def test_satellites_keep_talkers_separate_and_do_not_add_gsv_parts(self):
        self.state.sentence(nmea(GSV_GP))
        self.state.sentence(nmea(GSV_GP.replace("2,1,08", "2,2,08")))
        self.state.sentence(nmea(GSV_GL))
        self.assertEqual(self.state.snapshot()["satellites_in_view"], {"GP": 8, "GL": 6})

    def test_corrupt_and_unsupported_sentences_do_not_confirm_gps(self):
        corrupted = nmea(GGA).replace(b"4807.038", b"4808.038")
        self.state.sentence(corrupted)
        self.assertIsNone(self.state.snapshot()["last_sentence"])
        self.state.sentence(nmea("GPTXT,01,01,02,Receiver started"))
        self.assertFalse(self.state.snapshot()["gps_detected"])
        self.assertEqual(self.state.snapshot()["status"], "waiting")

    def test_disconnect_and_reconnect_retain_coordinates_but_require_new_fix(self):
        self.state.sentence(nmea(GGA))
        self.state.sentence(nmea(GSV_GP))
        self.state.unavailable("disconnected", "Receiver unplugged")
        self.assertFalse(self.state.snapshot()["fix_valid"])
        self.state.connected()
        state = self.state.snapshot()
        self.assertFalse(state["fix_valid"])
        self.assertFalse(state["gps_detected"])
        self.assertAlmostEqual(state["latitude"], 48.1173)
        self.assertIsNone(state["satellites_used"])
        self.assertEqual(state["satellites_in_view"], {})
        self.assertIsNone(state["hdop"])
        self.assertIsNone(state["altitude_m"])
        self.assertIsNone(state["last_sentence"])
        self.state.sentence(nmea(GSV_GP))
        self.assertFalse(self.state.snapshot()["fix_valid"])

    def test_nonfinite_diagnostics_are_null_in_valid_json(self):
        self.state.sentence(nmea(GGA.replace(",0.9,545.4,M", ",nan,inf,M")))
        state = self.state.snapshot()
        self.assertIsNone(state["hdop"])
        self.assertIsNone(state["altitude_m"])
        json.dumps(state, allow_nan=False)

    def test_http_snapshots_cannot_mutate_reader_state(self):
        self.state.sentence(nmea(GSV_GP))
        state = self.state.snapshot()
        state["satellites_in_view"]["GP"] = 999
        state["ports"][0]["device"] = "changed"
        self.assertEqual(self.state.snapshot()["satellites_in_view"], {"GP": 8})
        self.assertEqual(self.state.snapshot()["ports"][0]["device"], PORTS[0][0])


class MonitorTests(unittest.TestCase):
    """Exercise buffering, device selection, and reconnects with fake receivers."""
    def setUp(self):
        self.state = GPSState()
        self.monitor = GPSMonitor(self.state, None, port_lister=lambda: PORTS)

    def test_partial_lines_and_binary_prefix_resynchronize(self):
        self.state.connected()
        sentence = nmea(GGA)
        self.monitor.consume(b"\x00\xffpartial" + sentence[:20])
        self.assertFalse(self.state.snapshot()["fix_valid"])
        self.monitor.consume(sentence[20:])
        self.assertTrue(self.state.snapshot()["fix_valid"])
        self.assertEqual(self.state.snapshot()["last_sentence"], sentence.decode().strip())

    def test_binary_or_oversized_lines_are_bounded_and_recover(self):
        self.state.connected()
        for _ in range(3):
            self.monitor.consume(b"X" * 4096)
            self.assertLessEqual(len(self.monitor.pending), MAX_SENTENCE_BYTES)
        self.monitor.consume(nmea("GPTXT," + "x" * 2000))
        self.assertIsNone(self.state.snapshot()["last_sentence"])
        self.monitor.consume(nmea(GGA))
        self.assertTrue(self.state.snapshot()["fix_valid"])

    def test_scan_is_unambiguous_and_reuses_cli_selection(self):
        self.assertEqual(self.monitor.scan(), PORTS[0][0])
        self.assertEqual(detect_port(PORTS), PORTS[0][0])
        self.monitor.port_lister = lambda: [("/dev/a", "USB serial", True),
                                            ("/dev/b", "USB serial", True)]
        self.assertIsNone(self.monitor.scan())
        state = self.state.snapshot()
        self.assertTrue(state["detected"])
        self.assertFalse(state["connected"])
        self.assertEqual(state["status"], "ambiguous")
        self.assertEqual(len(state["ports"]), 2)
        self.monitor.port_lister = lambda: []
        self.assertIsNone(self.monitor.scan())
        self.assertEqual(self.state.snapshot()["status"], "no_device")
        self.assertFalse(self.state.snapshot()["detected"])

    def test_explicit_port_resolves_ambiguity_and_reports_missing_receiver(self):
        self.monitor.port = "/dev/b"
        self.monitor.port_lister = lambda: [("/dev/a", "USB serial", True),
                                            ("/dev/b", "USB serial", True)]
        self.assertEqual(self.monitor.scan(), "/dev/b")
        self.monitor.port_lister = lambda: []
        self.assertIsNone(self.monitor.scan())
        self.assertEqual(self.state.snapshot()["port"], "/dev/b")
        self.assertFalse(self.state.snapshot()["detected"])

    def test_unexpected_reader_error_invalidates_fix_and_retries(self):
        snapshots = []
        opens = []
        stop = threading.Event()
        state = self.state

        class Receiver:
            # First session supplies a fix then fails; the second stops the
            # monitor after exposing the reset state at the start of reconnect.
            in_waiting = 4096

            def __init__(self, session):
                self.session = session
                self.reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, size):
                self.reads += 1
                if self.session == 1:
                    if self.reads == 1:
                        return nmea(GGA) + nmea(GSV_GP)
                    snapshots.append(state.snapshot())
                    raise RuntimeError("unexpected serial failure")
                snapshots.append(state.snapshot())
                stop.set()
                return b""

        def serial_factory(port, **kwargs):
            opens.append((port, kwargs))
            if len(opens) == 2:
                snapshots.append(state.snapshot())
            return Receiver(len(opens))

        monitor = GPSMonitor(state, serial_factory, port_lister=lambda: PORTS,
                             stop=stop, retry_seconds=0)
        monitor.run()
        # Snapshots capture a live fix, the disconnected state before reopen,
        # and a reopened receiver that has not yet supplied a new valid fix.
        self.assertEqual(len(opens), 2)
        self.assertTrue(snapshots[0]["fix_valid"])
        self.assertFalse(snapshots[1]["fix_valid"])
        self.assertEqual(snapshots[1]["status"], "disconnected")
        self.assertIn("unexpected serial failure", snapshots[1]["message"])
        self.assertFalse(snapshots[2]["fix_valid"])
        self.assertEqual(snapshots[2]["satellites_in_view"], {})
        self.assertAlmostEqual(snapshots[2]["latitude"], 48.1173)
        self.assertEqual(opens[0][1], {"baudrate": 9600, "timeout": 1})
        self.assertFalse(state.snapshot()["connected"])

    def test_hotplug_retries_when_device_appears(self):
        scans = []
        stop = threading.Event()

        def port_lister():
            scans.append(True)
            return [] if len(scans) == 1 else PORTS

        def serial_factory(*args, **kwargs):
            stop.set()
            raise OSError("test reader stopped after device appeared")

        GPSMonitor(self.state, serial_factory, port_lister=port_lister,
                   stop=stop, retry_seconds=0).run()
        self.assertEqual(len(scans), 2)
        self.assertTrue(self.state.snapshot()["detected"])
        self.assertFalse(self.state.snapshot()["fix_valid"])


class HTTPTests(unittest.TestCase):
    """Verify the JSON contract and isolation of HTTP clients from serial reads."""
    def setUp(self):
        self.state = GPSState()
        # Port zero avoids collisions with a running appliance or another test.
        self.server = create_server(self.state, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.client = http.client.HTTPConnection(*self.server.server_address, timeout=2)

    def tearDown(self):
        self.client.close()
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def test_loopback_endpoint_has_contract_and_disables_caching(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.client.request("GET", "/api/gps?refresh=1")
        response = self.client.getresponse()
        data = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(set(data), {
            "detected", "connected", "gps_detected", "status", "message", "port", "baud",
            "latitude", "longitude", "fix_valid", "fix_age_seconds", "satellites_used",
            "satellites_in_view", "hdop", "altitude_m", "last_sentence",
            "last_data_age_seconds", "ports",
        })
        self.assertFalse(data["fix_valid"])
        self.assertEqual(data["status"], "no_device")

    def test_unknown_path_is_json_404(self):
        self.client.request("GET", "/not-a-gps-endpoint")
        response = self.client.getresponse()
        self.assertEqual(response.status, 404)
        self.assertEqual(json.loads(response.read()), {"error": "Not found"})

    def test_http_reads_shared_state_without_opening_a_receiver(self):
        self.state.scanned(PORTS, True, PORTS[0][0])
        self.state.connected()
        self.state.sentence(nmea(GGA))
        for _ in range(2):
            self.client.request("GET", "/api/gps")
            data = json.loads(self.client.getresponse().read())
            self.assertTrue(data["fix_valid"])
            self.assertAlmostEqual(data["latitude"], 48.1173)


if __name__ == "__main__":
    unittest.main()
