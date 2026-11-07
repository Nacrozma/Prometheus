//! SiblingBridge: Atlas's side of the link to a separately owned assistant (Prometheus).
//!
//! - Atlas never listens on the network. It connects as a client to the sibling's adapter, which
//!   must be on this computer (`http://127.0.0.1:<port>` or `http://localhost:<port>`).
//! - Pairing needs a one-time code shown in the sibling's terminal; the code never crosses the wire.
//! - The shared secret is stored in the OS credential store (never SQLite, logs or exports).
//! - Every request and reply is authenticated; replies that do not verify are treated as no reply.
//! - Status is only "connected" after a verified HEALTH_CHECK; nothing is shown as green on hope.
//! - Sibling replies are untrusted data. They can never trigger Atlas tools or change its policy.

pub mod missions;
pub mod protocol;

use crate::credentials::{validate_secret, SharedSecrets};
use crate::error::{AtlasError, Result};
use crate::storage::{now, Db};
use protocol::{Envelope, PROTOCOL};
use serde::Serialize;
use serde_json::{json, Value};
use std::time::Duration;

pub const DEFAULT_PORT: u16 = 47653;

pub fn secret_account(sibling_id: &str) -> String {
    format!("sibling:{sibling_id}")
}

/// Only plain-HTTP loopback endpoints: the link never leaves this computer.
pub fn validate_endpoint(raw: &str) -> Result<String> {
    let raw = raw.trim().trim_end_matches('/');
    let raw = if raw.contains("://") { raw.to_string() } else { format!("http://{raw}") };
    let url = reqwest::Url::parse(&raw).map_err(|_| AtlasError::Validation("enter an address like 127.0.0.1:47653".into()))?;
    let host = url.host_str().unwrap_or_default();
    if url.scheme() != "http" || !matches!(host, "127.0.0.1" | "localhost") || url.port().is_none() {
        return Err(AtlasError::Validation("the sibling link only connects to this computer: use 127.0.0.1:<port>".into()));
    }
    if url.path() != "/" || url.query().is_some() || !url.username().is_empty() {
        return Err(AtlasError::Validation("enter only host and port, e.g. 127.0.0.1:47653".into()));
    }
    Ok(format!("http://{host}:{}", url.port().unwrap_or(DEFAULT_PORT)))
}

/// HTTP client for the link: loopback only, never through a proxy, short timeouts.
pub fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .no_proxy()
        .connect_timeout(Duration::from_secs(3))
        .redirect(reqwest::redirect::Policy::none())
        .user_agent(concat!("ATLAS-CoPilot/", env!("CARGO_PKG_VERSION"), " sibling/1"))
        .build()
        .unwrap_or_default()
}

async fn post(http: &reqwest::Client, endpoint: &str, body: &Value, timeout: Duration) -> Result<(u16, Value)> {
    let resp = http
        .post(format!("{endpoint}/sibling/v1"))
        .header("X-Sibling-Protocol", "1")
        .json(body)
        .timeout(timeout)
        .send()
        .await
        .map_err(|e| {
            if e.is_connect() {
                AtlasError::Io("the sibling adapter is not running (nothing is listening at that address)".into())
            } else if e.is_timeout() {
                AtlasError::Timeout("the sibling did not answer in time".into())
            } else {
                AtlasError::Io(format!("could not reach the sibling: {e}"))
            }
        })?;
    let status = resp.status().as_u16();
    let bytes = resp.bytes().await.map_err(|e| AtlasError::Io(e.to_string()))?;
    if bytes.len() > 4 * 1024 * 1024 {
        return Err(AtlasError::Validation("the sibling's reply was too large".into()));
    }
    let v: Value = serde_json::from_slice(&bytes).map_err(|_| AtlasError::Validation("the sibling's reply was not valid JSON".into()))?;
    Ok((status, v))
}

#[derive(Debug, Clone, Serialize)]
pub struct Sibling {
    pub id: String,
    pub name: String,
    pub endpoint: String,
    pub status: String,
    pub remote_version: Option<String>,
    pub adapter_version: Option<String>,
    pub capabilities: Option<Value>,
    pub health: Option<Value>,
    pub last_seen_at: Option<String>,
    pub last_error: Option<String>,
    pub paired_at: String,
    pub revoked_at: Option<String>,
    /// True only if the last verified HEALTH_CHECK succeeded within the last two minutes.
    pub connected: bool,
    pub test_peer: bool,
}

fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Sibling> {
    let last_seen: Option<String> = r.get(8)?;
    let last_error: Option<String> = r.get(9)?;
    let status: String = r.get(3)?;
    let fresh = last_seen
        .as_deref()
        .and_then(|t| chrono::DateTime::parse_from_rfc3339(t).ok())
        .map(|t| chrono::Utc::now().signed_duration_since(t).num_seconds() < 120)
        .unwrap_or(false);
    let name: String = r.get(1)?;
    Ok(Sibling {
        id: r.get(0)?,
        test_peer: name.contains("TEST BACKEND"),
        name,
        endpoint: r.get(2)?,
        connected: status == "paired" && fresh && last_error.is_none(),
        status,
        remote_version: r.get(4)?,
        adapter_version: r.get(5)?,
        capabilities: r.get::<_, Option<String>>(6)?.and_then(|s| serde_json::from_str(&s).ok()),
        health: r.get::<_, Option<String>>(7)?.and_then(|s| serde_json::from_str(&s).ok()),
        last_seen_at: last_seen,
        last_error,
        paired_at: r.get(10)?,
        revoked_at: r.get(11)?,
    })
}

const COLS: &str = "id, name, endpoint, status, remote_version, adapter_version, capabilities, health, last_seen_at, last_error, paired_at, revoked_at";

pub fn list(db: &Db) -> Result<Vec<Sibling>> {
    let conn = db.conn()?;
    let mut stmt = conn.prepare(&format!("SELECT {COLS} FROM siblings ORDER BY paired_at DESC"))?;
    let rows = stmt.query_map([], row)?;
    Ok(rows.collect::<std::result::Result<_, _>>()?)
}

pub fn get(db: &Db, id: &str) -> Result<Sibling> {
    db.conn()?.query_row(&format!("SELECT {COLS} FROM siblings WHERE id = ?1"), [id], row).map_err(|e| match e {
        rusqlite::Error::QueryReturnedNoRows => AtlasError::NotFound("sibling".into()),
        o => o.into(),
    })
}

/// Pair with the adapter at `endpoint` using the one-time code from its terminal.
pub async fn pair(db: &Db, secrets: &SharedSecrets, http: &reqwest::Client, endpoint: &str, code: &str, atlas_instance_id: &str, atlas_name: &str) -> Result<Sibling> {
    let endpoint = validate_endpoint(endpoint)?;
    let norm = protocol::normalize_code(code);
    if norm.len() < 10 {
        return Err(AtlasError::Validation("the pairing code has 10 letters and digits, like ABCDE-FGH23".into()));
    }
    let atlas_nonce = protocol::random_hex(32);
    let payload = json!({
        "atlas_instance_id": atlas_instance_id,
        "atlas_name": atlas_name,
        "atlas_nonce": atlas_nonce,
        "proof": protocol::pair_proof(&norm, "request", &[atlas_instance_id, &atlas_nonce]),
    });
    let env = json!({"protocol": PROTOCOL, "type": "PAIR", "id": protocol::random_hex(16), "ts": protocol::now_ms(), "nonce": protocol::random_hex(16), "payload": payload.to_string()});
    let (status, body) = post(http, &endpoint, &env, Duration::from_secs(10)).await?;
    if status != 200 {
        let msg = body["message"].as_str().unwrap_or("the sibling refused the pairing request");
        return Err(AtlasError::PermissionDenied(msg.to_string()));
    }
    let sid = body["sibling_id"].as_str().unwrap_or_default().to_string();
    let prom_nonce = body["prometheus_nonce"].as_str().unwrap_or_default().to_string();
    if !sid.starts_with("sib_") || sid.len() > 80 || prom_nonce.len() < 32 || body["protocol"].as_str() != Some(PROTOCOL) {
        return Err(AtlasError::Validation("the sibling's pairing reply was malformed".into()));
    }
    // The adapter must prove it knows the code too; otherwise something else answered.
    if !protocol::verify_pair_accept(&norm, atlas_instance_id, &atlas_nonce, &prom_nonce, &sid, body["proof"].as_str().unwrap_or_default()) {
        return Err(AtlasError::PermissionDenied("the program at that address could not prove it showed this code; pairing was not completed".into()));
    }
    let secret = protocol::derive_secret(&norm, &atlas_nonce, &prom_nonce, &sid);
    let enc = validate_secret(&hex::encode(&secret))?;
    secrets.set(&secret_account(&sid), &enc)?;
    let name = body["prometheus_name"].as_str().unwrap_or("Prometheus").chars().take(80).collect::<String>();
    db.conn()?.execute(
        "INSERT INTO siblings(id, name, endpoint, status, paired_at) VALUES (?1,?2,?3,'paired',?4)",
        rusqlite::params![sid, name, endpoint, now()],
    )?;
    get(db, &sid)
}

pub struct Link<'a> {
    pub db: &'a Db,
    pub secrets: &'a SharedSecrets,
    pub http: &'a reqwest::Client,
}

impl Link<'_> {
    fn secret(&self, sid: &str) -> Result<Vec<u8>> {
        let s = self.secrets.get(&secret_account(sid))?.ok_or_else(|| AtlasError::Credential("the pairing secret for this sibling is missing; pair again".into()))?;
        hex::decode(s.trim()).map_err(|_| AtlasError::Credential("the stored pairing secret is damaged; pair again".into()))
    }

    /// One authenticated request. Records reachability honestly on the sibling row.
    pub async fn call(&self, sid: &str, typ: &str, payload: Value, timeout: Duration) -> Result<(String, Value)> {
        let sib = get(self.db, sid)?;
        if sib.status != "paired" {
            return Err(AtlasError::PermissionDenied("this sibling was unpaired".into()));
        }
        let secret = self.secret(sid)?;
        let env = protocol::seal(&secret, sid, typ, &payload);
        let res = async {
            let (status, body) = post(self.http, &sib.endpoint, &serde_json::to_value(&env)?, timeout).await?;
            if status == 401 {
                return Err(AtlasError::PermissionDenied("the sibling no longer accepts this pairing (it may have been revoked there); pair again".into()));
            }
            if status != 200 {
                return Err(AtlasError::Io(format!("the sibling answered with an error ({status})")));
            }
            let reply: Envelope = serde_json::from_value(body).map_err(|_| AtlasError::Validation("the sibling's reply was malformed".into()))?;
            let v = protocol::open(&secret, sid, &env.id, &reply)?;
            Ok((reply.typ, v))
        }
        .await;
        let conn = self.db.conn()?;
        match &res {
            Ok(_) => {
                conn.execute("UPDATE siblings SET last_seen_at = ?1, last_error = NULL WHERE id = ?2", rusqlite::params![now(), sid])?;
            }
            Err(e) => {
                conn.execute("UPDATE siblings SET last_error = ?1 WHERE id = ?2", rusqlite::params![crate::redact::redact(&e.to_string()), sid])?;
            }
        }
        res
    }

    /// HELLO + CAPABILITIES + HEALTH_CHECK: what the sibling says it is and can do, verified.
    pub async fn refresh(&self, sid: &str, atlas_version: &str) -> Result<Sibling> {
        let t = Duration::from_secs(8);
        let (_, hello) = self.call(sid, "HELLO", json!({"atlas_version": atlas_version}), t).await?;
        let (_, caps) = self.call(sid, "CAPABILITIES", json!({}), t).await?;
        let (_, health) = self.call(sid, "HEALTH_CHECK", json!({}), t).await?;
        let name = hello["prometheus_name"].as_str().unwrap_or("Prometheus").chars().take(80).collect::<String>();
        self.db.conn()?.execute(
            "UPDATE siblings SET name = ?1, remote_version = ?2, adapter_version = ?3, capabilities = ?4, health = ?5 WHERE id = ?6",
            rusqlite::params![
                name,
                hello["prometheus_version"].as_str().map(|s| s.chars().take(40).collect::<String>()),
                hello["adapter_version"].as_str().map(|s| s.chars().take(40).collect::<String>()),
                caps.to_string(),
                health.to_string(),
                sid
            ],
        )?;
        get(self.db, sid)
    }

    pub async fn health(&self, sid: &str) -> Result<Sibling> {
        let (_, health) = self.call(sid, "HEALTH_CHECK", json!({}), Duration::from_secs(5)).await?;
        self.db.conn()?.execute("UPDATE siblings SET health = ?1 WHERE id = ?2", rusqlite::params![health.to_string(), sid])?;
        get(self.db, sid)
    }
}

/// Stop using a sibling: delete the secret here and mark it revoked. (The sibling's owner revokes
/// on their side with `python sibling_adapter.py --revoke <id>`.)
pub fn revoke(db: &Db, secrets: &SharedSecrets, sid: &str) -> Result<Sibling> {
    get(db, sid)?;
    secrets.delete(&secret_account(sid))?;
    db.conn()?.execute("UPDATE siblings SET status = 'revoked', revoked_at = ?1 WHERE id = ?2", rusqlite::params![now(), sid])?;
    get(db, sid)
}

/// Remove a revoked sibling's record entirely (its missions stay in the ledger).
pub fn forget(db: &Db, secrets: &SharedSecrets, sid: &str) -> Result<()> {
    secrets.delete(&secret_account(sid))?;
    db.conn()?.execute("DELETE FROM siblings WHERE id = ?1", [sid])?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn endpoints_are_loopback_only() {
        assert_eq!(validate_endpoint("127.0.0.1:47653").unwrap(), "http://127.0.0.1:47653");
        assert_eq!(validate_endpoint("http://localhost:9000/").unwrap(), "http://localhost:9000");
        for bad in ["192.168.1.5:47653", "example.com:80", "https://127.0.0.1:47653", "127.0.0.1", "http://127.0.0.1:1/x", "http://u@127.0.0.1:1", "0.0.0.0:47653", "[::1]:47653"] {
            assert!(validate_endpoint(bad).is_err(), "{bad} must be refused");
        }
    }
}
