import math
from pathlib import Path
import subprocess
import sys
import unittest

from native_host_session import NativeSession, ObservationTimeout, RpcError, SessionError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).with_name("native_session_fixture.py")


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.workspace = ROOT
        self.sessions = []

    def tearDown(self):
        for session in reversed(self.sessions):
            try:
                session.close(timeout=1)
            except Exception:
                pass

    def new_session(self, mode="basic", **options):
        command = [sys.executable, str(FIXTURE), mode]
        session = NativeSession(command, self.workspace, **options)
        self.sessions.append(session)
        session.start()
        return session

    def test_initialize_returns_result_only_and_close_reports_owned_process(self):
        session = self.new_session()
        result = session.request(1, "initialize", {"client": "test"})
        self.assertTrue(result["ok"])
        self.assertNotIn("id", result)
        self.assertTrue(session.is_live())
        closed = session.close(timeout=1)
        self.assertEqual({"owned_process_exited": True, "exit_code": 0}, closed)
        self.assertFalse(session.is_live())

    def test_allowed_methods_and_initialized_notification(self):
        session = self.new_session()
        methods = (
            "initialize",
            "thread/start",
            "turn/start",
            "thread/read",
            "thread/unsubscribe",
            "turn/interrupt",
        )
        session.notify("initialized", {"ready": True})
        for request_id, method in enumerate(methods, 1):
            with self.subTest(method=method):
                result = session.request(request_id, method, {"request": request_id})
                self.assertEqual(method, result["method"])
        with self.assertRaises(SessionError):
            session.notify("initialize", {})
        with self.assertRaises(SessionError):
            session.request(20, "turn/steer", {})

    def test_chunked_crlf_frame_is_reassembled(self):
        session = self.new_session("chunked")
        result = session.request(1, "initialize", {})
        self.assertEqual("initialize", result["method"])

    def test_notification_requires_exact_method_and_thread(self):
        session = self.new_session("notifications")
        session.request(1, "turn/start", {})
        correct = session.next_notification("turn/started", "thread-1", timeout=1)
        self.assertEqual("right", correct["params"]["marker"])
        wrong_method = session.next_notification("turn/completed", "thread-1", timeout=1)
        self.assertEqual("wrong-method", wrong_method["params"]["marker"])
        wrong_thread = session.next_notification("turn/started", "other-thread", timeout=1)
        self.assertEqual("wrong-thread", wrong_thread["params"]["marker"])

    def test_duplicate_json_keys_are_rejected(self):
        for mode in ("duplicate", "duplicate_nested"):
            with self.subTest(mode=mode):
                session = self.new_session(mode)
                with self.assertRaises(SessionError):
                    session.request(1, "initialize", {})

    def test_bool_is_not_an_integer_rpc_id(self):
        session = self.new_session("bool_id")
        with self.assertRaises(SessionError):
            session.request(True, "initialize", {})
        result = session.request(1, "initialize", {})
        self.assertEqual("initialize", result["method"])

    def test_bool_and_wrong_integer_ids_are_not_misclaimed(self):
        for mode in ("bool_id", "wrong_id"):
            with self.subTest(mode=mode):
                session = self.new_session(mode)
                result = session.request(1, "initialize", {}, timeout=1)
                self.assertEqual("initialize", result["method"])

    def test_rpc_error_does_not_make_session_terminal(self):
        session = self.new_session("rpc_error")
        with self.assertRaises(RpcError) as raised:
            session.request(1, "initialize", {})
        self.assertEqual(409, raised.exception.code)
        self.assertTrue(session.is_live())
        result = session.request(2, "initialize", {})
        self.assertEqual([1, 2], result["receivedIds"])

    def test_jsonrpc_2_result_is_accepted(self):
        session = self.new_session("jsonrpc_2")
        result = session.request(1, "initialize", {}, timeout=1)
        self.assertEqual("initialize", result["method"])
        self.assertNotIn("jsonrpc", result)

    def test_jsonrpc_2_error_accepts_integer_code_string_message_and_optional_data(self):
        session = self.new_session("rpc_error_jsonrpc_2")
        with self.assertRaises(RpcError) as raised:
            session.request(1, "initialize", {}, timeout=1)
        self.assertEqual(-32601, raised.exception.code)
        self.assertTrue(session.is_live())
        result = session.request(2, "initialize", {}, timeout=1)
        self.assertEqual([1, 2], result["receivedIds"])

    def test_unsupported_jsonrpc_versions_are_rejected(self):
        modes = (
            "jsonrpc_1", "jsonrpc_future", "jsonrpc_null", "jsonrpc_number",
            "jsonrpc_bool", "jsonrpc_object", "jsonrpc_array",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                session = self.new_session(mode)
                with self.assertRaises(SessionError) as raised:
                    session.request(1, "initialize", {}, timeout=1)
                self.assertIs(type(raised.exception), SessionError)

    def test_malformed_rpc_errors_are_rejected_not_remote_errors(self):
        modes = (
            "error_null", "error_array", "error_string", "error_empty",
            "error_missing_code", "error_missing_message", "error_bool_code",
            "error_false_code", "error_float_code", "error_fraction_code",
            "error_string_code", "error_null_code", "error_null_message",
            "error_number_message", "error_bool_message", "error_array_message",
            "error_object_message",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                session = self.new_session(mode)
                with self.assertRaises(SessionError) as raised:
                    session.request(1, "initialize", {}, timeout=1)
                self.assertIs(type(raised.exception), SessionError)

    def test_rpc_response_requires_exactly_one_result_or_error(self):
        for mode in ("missing_payload", "both_payloads"):
            with self.subTest(mode=mode):
                session = self.new_session(mode)
                with self.assertRaises(SessionError) as raised:
                    session.request(1, "initialize", {}, timeout=1)
                self.assertIs(type(raised.exception), SessionError)

    def test_deep_json_parse_failure_fails_closed(self):
        session = self.new_session("deep_json")
        with self.assertRaisesRegex(SessionError, "Invalid native JSON frame") as raised:
            session.request(1, "initialize", {}, timeout=1)
        self.assertIs(type(raised.exception), SessionError)
        session._reader.join(timeout=1)
        self.assertFalse(session._reader.is_alive())
        self.assertIs(session._failure, raised.exception)
        self.assertTrue(session._stdout_done)
        with self.assertRaises(SessionError) as repeated:
            session.next_notification("turn/started", "thread-1", timeout=1)
        self.assertIs(repeated.exception, raised.exception)

    def test_observation_timeout_does_not_make_session_terminal(self):
        session = self.new_session("timeout")
        with self.assertRaises(ObservationTimeout):
            session.request(1, "initialize", {}, timeout=0.05)
        self.assertTrue(session.is_live())
        result = session.request(2, "initialize", {}, timeout=1)
        self.assertEqual([1, 2], result["receivedIds"])

    def test_duplicate_request_id_is_not_submitted_again(self):
        session = self.new_session()
        session.request(7, "initialize", {})
        with self.assertRaises(SessionError):
            session.request(7, "initialize", {})
        result = session.request(8, "initialize", {})
        self.assertEqual([7, 8], result["receivedIds"])

    def test_frame_budget_fails_closed(self):
        session = self.new_session("oversize", max_frame_bytes=128)
        with self.assertRaises(SessionError):
            session.request(1, "initialize", {}, timeout=1)

    def test_pending_frame_budget_fails_closed(self):
        session = self.new_session("burst", max_pending_frames=2)
        with self.assertRaises(SessionError):
            session.request(1, "initialize", {}, timeout=1)

    def test_non_finite_json_is_not_submitted(self):
        session = self.new_session()
        with self.assertRaises(SessionError):
            session.request(1, "initialize", {"value": math.nan})
        result = session.request(2, "initialize", {})
        self.assertEqual([2], result["receivedIds"])

    def test_close_only_affects_the_session_owned_process(self):
        sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            session = self.new_session("linger")
            closed = session.close(timeout=0.05)
            self.assertTrue(closed["owned_process_exited"])
            self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=2)

    def test_unstarted_close_does_not_create_or_close_other_processes(self):
        sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            session = NativeSession([sys.executable, str(FIXTURE), "basic"], self.workspace)
            closed = session.close(timeout=1)
            self.assertEqual({"owned_process_exited": True, "exit_code": None}, closed)
            self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=2)

    def test_server_request_with_same_id_is_not_a_response(self):
        modes = (
            "bidirectional", "bidirectional_result", "bidirectional_error",
            "bidirectional_null_method", "bidirectional_empty_method",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                session = self.new_session(mode)
                result = session.request(1, "initialize", {}, timeout=1)
                self.assertEqual("initialize", result["method"])
                self.assertEqual([1], result["receivedIds"])

    def test_close_releases_all_owned_pipes_and_reader_threads(self):
        for mode in ("basic", "exit_after_response", "linger"):
            with self.subTest(mode=mode):
                session = self.new_session(mode)
                session.request(1, "initialize", {}, timeout=1)
                if mode == "exit_after_response":
                    session._process.wait(timeout=1)
                session.close(timeout=0.1)
                for stream in (session._process.stdin, session._process.stdout, session._process.stderr):
                    self.assertTrue(stream.closed)
                self.assertFalse(session._reader.is_alive())
                self.assertFalse(session._stderr_reader.is_alive())
                self.assertTrue(session.close(timeout=1)["owned_process_exited"])


if __name__ == "__main__":
    unittest.main()
