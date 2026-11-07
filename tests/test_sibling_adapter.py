"""Tests for sibling_adapter.py (Sibling Protocol v1, Prometheus side).

They drive a real loopback HTTP server with the deterministic TestBackend and an in-memory secret
store, so they need no provider keys and never import prometheus.py.
"""
import hashlib
import hmac
import http.client
import json
import os
import secrets
import tempfile
import threading
import time
import unittest
import uuid

os.environ["PROMETHEUS_SIBLING_DIR"] = tempfile.mkdtemp(prefix="sibling-test-")

import sibling_adapter as S  # noqa: E402


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Peer:
    """A minimal Atlas-side client for the tests."""

    def __init__(self, port):
        self.port = port
        self.sid = None
        self.secret = None

    def post(self, env, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        body = json.dumps(env).encode()
        h = {"Content-Type": "application/json", "X-Sibling-Protocol": "1", "Host": host or f"127.0.0.1:{self.port}"}
        if headers is not None:
            h = headers
        c.request("POST", "/sibling/v1", body=body, headers=h)
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        return r.status, data

    def pair(self, code, atlas_id="atlas-test"):
        nonce = secrets.token_hex(32)
        payload = json.dumps({"atlas_instance_id": atlas_id, "atlas_name": "Test Atlas", "atlas_nonce": nonce, "proof": S.pair_proof(code, "request", atlas_id, nonce)})
        st, body = self.post({"protocol": S.PROTOCOL, "type": "PAIR", "id": uuid.uuid4().hex, "ts": S.now_ms(), "nonce": secrets.token_hex(16), "payload": payload})
        if st != 200:
            return st, body
        expected = S.pair_proof(code, "accept", atlas_id, nonce, body["prometheus_nonce"], body["sibling_id"])
        assert hmac.compare_digest(expected, body["proof"]), "adapter must prove it knows the code"
        self.sid = body["sibling_id"]
        self.secret = S.derive_secret(code, nonce, body["prometheus_nonce"], self.sid)
        return st, body

    def envelope(self, typ, payload, ts=None, nonce=None, mac_secret=None):
        p = json.dumps(payload)
        mid, ts, nonce = uuid.uuid4().hex, ts or S.now_ms(), nonce or secrets.token_hex(16)
        mac = S.envelope_mac(mac_secret or self.secret, typ, mid, self.sid, ts, nonce, p)
        return {"protocol": S.PROTOCOL, "type": typ, "id": mid, "sibling_id": self.sid, "ts": ts, "nonce": nonce, "payload": p, "mac": mac}

    def call(self, typ, payload):
        st, env = self.post(self.envelope(typ, payload))
        assert st == 200, (st, env)
        expect = S.envelope_mac(self.secret, env["type"], env["id"], env["sibling_id"], env["ts"], env["nonce"], env["payload"])
        assert hmac.compare_digest(expect, env["mac"]), "responses are authenticated"
        return env["type"], json.loads(env["payload"])


class SiblingAdapterTests(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.adapter = S.Adapter(S.TestBackend(), S.SecretStore(memory=True), S.Registry(persist=False), self.port)
        self.httpd = S.serve(self.adapter)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.peer = Peer(self.port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def paired(self):
        code = self.adapter.start_pairing()
        st, _ = self.peer.pair(code)
        self.assertEqual(st, 200)
        return code

    def test_known_answer_vectors_match_atlas(self):
        # The same vectors are asserted in atlas/core/src/sibling/protocol.rs; both sides must agree.
        self.assertEqual(S.envelope_mac(b"\x01" * 32, "HELLO", "m1", "sib_x", 1700000000000, "n" * 16, '{"a":1}'),
                         "aa6348e52a3ab355660552bda9a2a1a54c66d0377d54492c1b5572f43d272ced")
        self.assertEqual(S.pair_proof("abcde-fghjk", "request", "atlas-1", "00" * 32),
                         "538a95dc902bfde6548f49d99bd892962a6ac1a2594c52b78bbdad4738b0c62e")
        self.assertEqual(S.derive_secret("abcde-fghjk", "aa" * 32, "bb" * 32, "sib_x").hex(),
                         "4f4db99e0dc4a25a12a83cf623a7f8144f9bcccd9f0c226f0277c3bc2da3bdbe")
        # Independent recomputation of the MAC construction.
        expect = hmac.new(b"ABCDEFGHJK", "\n".join([S.PROTOCOL, "pair", "request", "atlas-1", "00" * 32]).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(S.pair_proof("abcde-fghjk", "request", "atlas-1", "00" * 32), expect)

    def test_pairing_requires_the_code_and_is_single_use(self):
        code = self.adapter.start_pairing()
        st, body = self.peer.pair("WRONG-CODE0")
        self.assertEqual(st, 403)
        st, _ = self.peer.pair(code)
        self.assertEqual(st, 200)
        st, body = Peer(self.port).pair(code)
        self.assertEqual(st, 403, "the code is consumed by the first successful pairing")

    def test_code_is_invalidated_after_too_many_wrong_attempts(self):
        code = self.adapter.start_pairing()
        for _ in range(S.CODE_MAX_ATTEMPTS):
            Peer(self.port).pair("AAAAA-AAAAA")
        st, _ = self.peer.pair(code)
        self.assertEqual(st, 403)

    def test_requests_are_authenticated_fresh_and_single_use(self):
        self.paired()
        t, hello = self.peer.call("HELLO", {"atlas_version": "test"})
        self.assertEqual((t, hello["protocol"]), ("HELLO", S.PROTOCOL))
        # Wrong secret
        st, _ = self.peer.post(self.peer.envelope("HELLO", {}, mac_secret=b"x" * 32))
        self.assertEqual(st, 401)
        # Stale timestamp
        st, _ = self.peer.post(self.peer.envelope("HELLO", {}, ts=S.now_ms() - 120_000))
        self.assertEqual(st, 401)
        # Replay
        env = self.peer.envelope("HELLO", {})
        self.assertEqual(self.peer.post(env)[0], 200)
        self.assertEqual(self.peer.post(env)[0], 401)
        # Tampered payload
        env = self.peer.envelope("HELLO", {"a": 1})
        env["payload"] = json.dumps({"a": 2})
        self.assertEqual(self.peer.post(env)[0], 401)

    def test_browser_style_and_foreign_host_requests_are_refused(self):
        self.paired()
        env = self.peer.envelope("HELLO", {})
        st, _ = self.peer.post(env, headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(st, 403, "no X-Sibling-Protocol header (a browser form post) is refused")
        st, _ = self.peer.post(self.peer.envelope("HELLO", {}), host=f"evil.example:{self.port}")
        self.assertEqual(st, 403, "DNS-rebinding style Host headers are refused")

    def test_revoked_siblings_are_refused(self):
        self.paired()
        self.adapter.registry.data["siblings"][self.peer.sid]["revoked"] = True
        self.assertEqual(self.peer.post(self.peer.envelope("HELLO", {}))[0], 401)

    def test_capabilities_are_discovered_and_flag_dangerous_tools(self):
        self.paired()
        _, caps = self.peer.call("CAPABILITIES", {})
        names = {t["name"]: t for t in caps["tools"]}
        self.assertTrue(names["execute_shell"]["dangerous"])
        self.assertFalse(names["execute_shell"]["available_to_siblings"])
        _, h = self.peer.call("HEALTH_CHECK", {})
        self.assertEqual(h["status"], "ok")

    def wait_state(self, mid, states, after=0):
        for _ in range(100):
            _, st = self.peer.call("MISSION_STATUS", {"mission_id": mid, "after_seq": after, "wait_ms": 500})
            if st["state"] in states:
                return st
        self.fail(f"mission never reached {states}")

    def test_consultation_mission_and_idempotent_create(self):
        self.paired()
        mid = "m_" + uuid.uuid4().hex
        req = {"mission_id": mid, "idempotency_key": "k1", "mode": "consultation", "objective": "Is SQLite WAL safe here?", "context": ""}
        _, ack = self.peer.call("MISSION_CREATE", req)
        self.assertTrue(ack["accepted"])
        self.assertFalse(ack["duplicate"])
        _, ack2 = self.peer.call("MISSION_CREATE", req)
        self.assertTrue(ack2["duplicate"], "the same create is never started twice")
        st = self.wait_state(mid, {"completed"})
        self.assertIn("received", st["result"]["summary"])
        self.assertEqual(len([e for e in st["events"] if e["kind"] == "message"]), 1)
        # Reusing a mission id with a different key is refused.
        _, ack3 = self.peer.call("MISSION_CREATE", dict(req, idempotency_key="other"))
        self.assertFalse(ack3["accepted"])

    def test_collaborative_mission_round_trips_messages(self):
        self.paired()
        mid = "m_" + uuid.uuid4().hex
        self.peer.call("MISSION_CREATE", {"mission_id": mid, "idempotency_key": "k", "mode": "collaborative", "objective": "Review my patch", "context": "diff..."})
        st = self.wait_state(mid, {"waiting_for_atlas"})
        seq = max(e["seq"] for e in st["events"])
        self.peer.call("MISSION_EVENT", {"mission_id": mid, "kind": "message", "text": "Here is v2"})
        st = self.wait_state(mid, {"waiting_for_atlas"}, after=seq)
        kinds = [e["kind"] for e in st["events"]]
        self.assertIn("atlas_message", kinds)
        self.assertIn("message", kinds)
        _, st = self.peer.call("MISSION_EVENT", {"mission_id": mid, "kind": "complete", "text": "Merged."})
        self.assertEqual(st["state"], "completed")

    def test_delegated_mission_refuses_dangerous_tools_and_can_be_cancelled(self):
        self.paired()
        mid = "m_" + uuid.uuid4().hex
        self.peer.call("MISSION_CREATE", {"mission_id": mid, "idempotency_key": "k", "mode": "delegated", "objective": "slow task", "context": ""})
        time.sleep(0.2)
        _, st = self.peer.call("MISSION_CANCEL", {"mission_id": mid})
        self.assertEqual(st["state"], "cancelled")
        st = self.wait_state(mid, {"cancelled"})
        self.assertTrue(any("refused" in e["text"] for e in st["events"] if e["kind"] == "tool_result"))

    def test_other_siblings_cannot_see_a_mission(self):
        self.paired()
        mid = "m_" + uuid.uuid4().hex
        self.peer.call("MISSION_CREATE", {"mission_id": mid, "idempotency_key": "k", "mode": "consultation", "objective": "x", "context": ""})
        other = Peer(self.port)
        code = self.adapter.start_pairing()
        other.pair(code, atlas_id="atlas-2")
        _, st = other.call("MISSION_STATUS", {"mission_id": mid})
        self.assertEqual(st["state"], "unknown")

    def test_secret_store_refuses_silent_plaintext(self):
        try:
            import keyring  # noqa: F401
            self.skipTest("an OS keyring module is installed here")
        except ImportError:
            pass
        with self.assertRaises(RuntimeError):
            S.SecretStore()
        self.assertEqual(S.SecretStore(allow_file=True).kind, "file", "plaintext only when explicitly allowed")


if __name__ == "__main__":
    unittest.main()


class FakeCall:
    def __init__(self, i, name, args):
        self.id = f"c{i}"
        self.function = type("F", (), {"name": name, "arguments": json.dumps(args)})()


class FakePrometheus:
    """Stands in for prometheus.py's public names so the sibling tool policy can be unit-tested.
    The same policy is exercised against the real runtime in atlas/core/tests/real_prometheus_runtime.rs."""

    SYSTEM_PROMPT = "fake system prompt"
    DANGEROUS_TOOLS = {"execute_shell", "write_file", "ghost_control"}

    def __init__(self, base, script):
        self.BASE_DIR = base
        self.TOOLS = [{"type": "function", "function": {"name": n, "description": n}} for n in
                      ["read_file", "recall_memory", "update_memory", "engineering_calc", "execute_shell", "write_file", "ghost_control", "web_search"]]
        self.dispatched = []
        self.offered = []
        script = list(script)
        outer = self

        class Router:
            active_providers = ["fake"]

            def completion(self, messages, tools=None, max_tokens=0):
                outer.offered.append([t["function"]["name"] for t in tools or []])
                step = sum(1 for m in messages if m.get("role") == "tool")
                if step < len(script):
                    msg = type("M", (), {"content": None, "tool_calls": [FakeCall(step, *script[step])]})()
                else:
                    msg = type("M", (), {"content": "done", "tool_calls": None})()
                return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

        self.llm_router = Router()

    def dispatch_tool(self, name, args):
        self.dispatched.append((name, args))
        if name == "read_file":
            with open(args["path"], encoding="utf-8") as f:
                return {"status": "success", "content": f.read()}
        return {"status": "success", "tool": name}

    def _confirm_tool(self, name, args):
        return True


class SiblingToolPolicyTests(unittest.TestCase):
    def run_mission(self, script, allow_dangerous=False, context="ctx-ok"):
        base = tempfile.mkdtemp()
        with open(os.path.join(base, "memory.json"), "w") as f:
            f.write("PRIVATE-MEMORY")
        P = FakePrometheus(base, script)
        b = S.PrometheusBackend(allow_dangerous=allow_dangerous, module=P)
        events = []
        outcome, _ = b.run_tools("obj", context, lambda k, t: events.append((k, t)), lambda: False, 10, mission_id="mis_abc")
        return P, b, events, outcome

    def test_private_state_and_network_tools_are_never_offered_or_run(self):
        P, b, ev, outcome = self.run_mission([("recall_memory", {"query": "x"}), ("update_memory", {"fact": "y"}), ("web_search", {"query": "z"}), ("ghost_control", {})])
        self.assertEqual(outcome, "completed")
        self.assertEqual(P.dispatched, [], "none of them reached Prometheus's dispatcher")
        self.assertEqual(set(P.offered[0]), {"read_file", "engineering_calc"})
        self.assertTrue(all("refused" in t for k, t in ev if k == "tool_result"))
        caps = {t["name"]: t["available_to_siblings"] for t in b.capabilities()["tools"]}
        self.assertEqual({k for k, v in caps.items() if v}, {"read_file", "engineering_calc"}, "capabilities report the real policy")

    def test_file_tools_are_confined_to_the_mission_workspace(self):
        P, _, ev, _ = self.run_mission([("read_file", {"path": "../../memory.json"}), ("read_file", {"path": os.path.join(tempfile.gettempdir(), "x")}), ("read_file", {"path": "atlas_context.md"})])
        results = [t for k, t in ev if k == "tool_result"]
        self.assertIn("outside this mission", results[0])
        self.assertIn("outside this mission", results[1])
        self.assertIn("ctx-ok", results[2])
        self.assertTrue(all("PRIVATE-MEMORY" not in t for _, t in ev))
        self.assertEqual(len(P.dispatched), 1)

    def test_dangerous_tools_need_the_flag_and_stay_confined(self):
        P, _, ev, _ = self.run_mission([("execute_shell", {"command": "ls"})])
        self.assertEqual(P.dispatched, [])
        P, _, ev, _ = self.run_mission([("write_file", {"path": "../escape.txt", "content": "x"}), ("write_file", {"path": "ok.txt", "content": "x"}), ("ghost_control", {})], allow_dangerous=True)
        names = [n for n, _ in P.dispatched]
        self.assertEqual(names, ["write_file"], "only the in-workspace write ran; desktop control never does")
        self.assertTrue(P.dispatched[0][1]["path"].endswith(os.path.join("sibling_missions", "mis_abc", "ok.txt")))

    def test_mission_ids_that_are_not_safe_folder_names_are_refused(self):
        self.assertIsNone(S.safe_mission_dir_name("../x"))
        self.assertIsNone(S.safe_mission_dir_name("a/b"))
        self.assertEqual(S.safe_mission_dir_name("mis_1-2"), "mis_1-2")
