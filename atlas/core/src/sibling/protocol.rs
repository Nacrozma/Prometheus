//! Sibling Protocol v1 wire format and cryptography. Mirrors `sibling_adapter.py` exactly; the
//! known-answer vectors in the tests are asserted on both sides.
//!
//! Every authenticated message is an envelope whose `payload` is a JSON *string*, so the MAC covers
//! exact bytes and no JSON canonicalisation is needed across languages:
//!
//! `mac = HMAC-SHA256(secret, "sibling/1\n{type}\n{id}\n{sibling_id}\n{ts}\n{nonce}\n{payload}")`

use crate::error::{AtlasError, Result};
use hmac::{Hmac, KeyInit, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;

pub const PROTOCOL: &str = "sibling/1";
pub const CLOCK_SKEW_MS: i64 = 60_000;

type HmacSha256 = Hmac<Sha256>;

fn mac_raw(key: &[u8], parts: &[&str]) -> Vec<u8> {
    let mut m = <HmacSha256 as KeyInit>::new_from_slice(key).expect("HMAC accepts any key length");
    m.update(parts.join("\n").as_bytes());
    m.finalize().into_bytes().to_vec()
}

fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

pub fn envelope_mac(secret: &[u8], typ: &str, id: &str, sibling_id: &str, ts: i64, nonce: &str, payload: &str) -> String {
    hex::encode(mac_raw(secret, &[PROTOCOL, typ, id, sibling_id, &ts.to_string(), nonce, payload]))
}

/// Upper-case and keep only letters and digits, so "abcde-fghjk" and "ABCDEFGHJK" are the same code.
pub fn normalize_code(code: &str) -> String {
    code.chars().filter(|c| c.is_ascii_alphanumeric()).map(|c| c.to_ascii_uppercase()).collect()
}

pub fn pair_proof(code: &str, label: &str, parts: &[&str]) -> String {
    let mut all = vec![PROTOCOL, "pair", label];
    all.extend_from_slice(parts);
    hex::encode(mac_raw(normalize_code(code).as_bytes(), &all))
}

pub fn derive_secret(code: &str, atlas_nonce: &str, prometheus_nonce: &str, sibling_id: &str) -> Vec<u8> {
    mac_raw(normalize_code(code).as_bytes(), &[PROTOCOL, "secret", atlas_nonce, prometheus_nonce, sibling_id])
}

pub fn random_hex(bytes: usize) -> String {
    let mut out = String::with_capacity(bytes * 2);
    while out.len() < bytes * 2 {
        out.push_str(&uuid::Uuid::new_v4().simple().to_string());
    }
    out.truncate(bytes * 2);
    out
}

pub fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Envelope {
    pub protocol: String,
    #[serde(rename = "type")]
    pub typ: String,
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub in_reply_to: Option<String>,
    pub sibling_id: String,
    pub ts: i64,
    pub nonce: String,
    pub payload: String,
    pub mac: String,
}

pub fn seal(secret: &[u8], sibling_id: &str, typ: &str, payload: &serde_json::Value) -> Envelope {
    let payload = serde_json::to_string(payload).unwrap_or_else(|_| "{}".into());
    let id = uuid::Uuid::new_v4().simple().to_string();
    let ts = now_ms();
    let nonce = random_hex(16);
    let mac = envelope_mac(secret, typ, &id, sibling_id, ts, &nonce, &payload);
    Envelope { protocol: PROTOCOL.into(), typ: typ.into(), id, in_reply_to: None, sibling_id: sibling_id.into(), ts, nonce, payload, mac }
}

/// Check a response: right protocol, sibling and request, fresh, and authentic. Anything that fails
/// is treated as if no answer had arrived.
pub fn open(secret: &[u8], sibling_id: &str, request_id: &str, env: &Envelope) -> Result<serde_json::Value> {
    let bad = |why: &str| AtlasError::PermissionDenied(format!("the sibling's reply could not be verified ({why})"));
    if env.protocol != PROTOCOL {
        return Err(bad("protocol"));
    }
    if env.sibling_id != sibling_id || env.in_reply_to.as_deref() != Some(request_id) {
        return Err(bad("wrong conversation"));
    }
    if (now_ms() - env.ts).abs() > CLOCK_SKEW_MS {
        return Err(bad("stale"));
    }
    let expect = envelope_mac(secret, &env.typ, &env.id, &env.sibling_id, env.ts, &env.nonce, &env.payload);
    if !ct_eq(expect.as_bytes(), env.mac.as_bytes()) {
        return Err(bad("signature"));
    }
    serde_json::from_str(&env.payload).map_err(|_| bad("payload"))
}

pub fn verify_pair_accept(code: &str, atlas_id: &str, atlas_nonce: &str, prometheus_nonce: &str, sibling_id: &str, proof: &str) -> bool {
    let expect = pair_proof(code, "accept", &[atlas_id, atlas_nonce, prometheus_nonce, sibling_id]);
    ct_eq(expect.as_bytes(), proof.as_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_answer_vectors_match_the_python_adapter() {
        // Same vectors as tests/test_sibling_adapter.py::test_known_answer_vectors_match_atlas.
        assert_eq!(
            envelope_mac(&[1u8; 32], "HELLO", "m1", "sib_x", 1_700_000_000_000, &"n".repeat(16), r#"{"a":1}"#),
            "aa6348e52a3ab355660552bda9a2a1a54c66d0377d54492c1b5572f43d272ced"
        );
        assert_eq!(pair_proof("abcde-fghjk", "request", &["atlas-1", &"00".repeat(32)]), "538a95dc902bfde6548f49d99bd892962a6ac1a2594c52b78bbdad4738b0c62e");
        assert_eq!(
            hex::encode(derive_secret("abcde-fghjk", &"aa".repeat(32), &"bb".repeat(32), "sib_x")),
            "4f4db99e0dc4a25a12a83cf623a7f8144f9bcccd9f0c226f0277c3bc2da3bdbe"
        );
        assert_eq!(normalize_code(" abcde-FGHJK "), "ABCDEFGHJK");
    }

    #[test]
    fn open_rejects_tampering_staleness_and_wrong_request() {
        let secret = [7u8; 32];
        let mut reply = seal(&secret, "sib_1", "HELLO", &serde_json::json!({"ok": true}));
        reply.in_reply_to = Some("req1".into());
        assert_eq!(open(&secret, "sib_1", "req1", &reply).unwrap()["ok"], true);
        assert!(open(&secret, "sib_1", "other", &reply).is_err());
        assert!(open(&secret, "sib_2", "req1", &reply).is_err());
        assert!(open(&[8u8; 32], "sib_1", "req1", &reply).is_err());
        let mut t = reply.clone();
        t.payload = r#"{"ok":false}"#.into();
        assert!(open(&secret, "sib_1", "req1", &t).is_err());
        let mut old = seal(&secret, "sib_1", "HELLO", &serde_json::json!({}));
        old.in_reply_to = Some("r".into());
        old.ts -= 120_000;
        old.mac = envelope_mac(&secret, &old.typ, &old.id, &old.sibling_id, old.ts, &old.nonce, &old.payload);
        assert!(open(&secret, "sib_1", "r", &old).is_err(), "stale replies are refused even with a valid MAC");
        assert_eq!(random_hex(32).len(), 64);
    }
}
