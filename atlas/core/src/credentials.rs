//! Credential storage. Secrets live only in the operating system's credential store
//! (macOS Keychain, Windows Credential Manager, Secret Service on Linux). They are read
//! inside the core immediately before an outbound request and are never returned to the UI,
//! written to SQLite, logged, or included in prompts. There is deliberately no plaintext
//! fallback: if the OS store is unavailable the user is told so.

use crate::error::{AtlasError, Result};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

const SERVICE: &str = "atlas-copilot";

pub trait SecretStore: Send + Sync {
    fn get(&self, account: &str) -> Result<Option<String>>;
    fn set(&self, account: &str, secret: &str) -> Result<()>;
    fn delete(&self, account: &str) -> Result<()>;
    /// Human-readable backend name for diagnostics.
    fn backend(&self) -> &'static str;
    /// Ok if the backend can currently be used.
    fn health(&self) -> Result<()>;
}

pub type SharedSecrets = Arc<dyn SecretStore>;

/// Account naming: `provider:<id>` or `integration:<id>`.
pub fn provider_account(id: &str) -> String {
    format!("provider:{id}")
}
pub fn integration_account(id: &str) -> String {
    format!("integration:{id}")
}

pub struct OsKeyring;

impl OsKeyring {
    fn entry(account: &str) -> Result<keyring::Entry> {
        keyring::Entry::new(SERVICE, account).map_err(|e| AtlasError::Credential(describe(&e)))
    }
}

fn describe(e: &keyring::Error) -> String {
    match e {
        keyring::Error::NoDefaultStore => {
            "no system credential store is available (on Linux, a Secret Service provider such as GNOME Keyring or KWallet must be running)".into()
        }
        keyring::Error::NoStorageAccess(_) => "the system credential store is locked or access was denied".into(),
        keyring::Error::PlatformFailure(_) => "the system credential store reported a failure".into(),
        other => format!("credential store error ({})", crate::redact::redact(&other.to_string())),
    }
}

impl SecretStore for OsKeyring {
    fn get(&self, account: &str) -> Result<Option<String>> {
        match Self::entry(account)?.get_password() {
            Ok(s) => Ok(Some(s)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(e) => Err(AtlasError::Credential(describe(&e))),
        }
    }
    fn set(&self, account: &str, secret: &str) -> Result<()> {
        Self::entry(account)?.set_password(secret).map_err(|e| AtlasError::Credential(describe(&e)))
    }
    fn delete(&self, account: &str) -> Result<()> {
        match Self::entry(account)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(e) => Err(AtlasError::Credential(describe(&e))),
        }
    }
    fn backend(&self) -> &'static str {
        if cfg!(target_os = "macos") {
            "macOS Keychain"
        } else if cfg!(target_os = "windows") {
            "Windows Credential Manager"
        } else {
            "Secret Service (D-Bus)"
        }
    }
    fn health(&self) -> Result<()> {
        // A lookup of a non-existent account exercises the full path without writing anything.
        self.get("health-check").map(|_| ())
    }
}

/// In-memory store for tests. Never used by the desktop build.
#[derive(Default)]
pub struct MemorySecrets(Mutex<HashMap<String, String>>);

impl SecretStore for MemorySecrets {
    fn get(&self, account: &str) -> Result<Option<String>> {
        Ok(self.0.lock().map_err(|_| AtlasError::Internal("lock".into()))?.get(account).cloned())
    }
    fn set(&self, account: &str, secret: &str) -> Result<()> {
        self.0.lock().map_err(|_| AtlasError::Internal("lock".into()))?.insert(account.into(), secret.into());
        Ok(())
    }
    fn delete(&self, account: &str) -> Result<()> {
        self.0.lock().map_err(|_| AtlasError::Internal("lock".into()))?.remove(account);
        Ok(())
    }
    fn backend(&self) -> &'static str {
        "in-memory (test)"
    }
    fn health(&self) -> Result<()> {
        Ok(())
    }
}

/// Validate a secret before storing it: non-empty, single line, bounded length.
pub fn validate_secret(secret: &str) -> Result<String> {
    let s = secret.trim();
    if s.is_empty() {
        return Err(AtlasError::Validation("the key is empty".into()));
    }
    // Windows Credential Manager stores at most 2560 bytes per secret; stay well inside it.
    if s.len() > 2048 || s.contains(['\n', '\r']) {
        return Err(AtlasError::Validation("the key must be a single line under 2048 characters".into()));
    }
    Ok(s.to_string())
}

/// Masked hint for display, e.g. `sk-ant…7f3a`. Shows at most 4 trailing characters.
pub fn mask(secret: &str) -> String {
    let chars: Vec<char> = secret.chars().collect();
    if chars.len() <= 8 {
        return "••••".into();
    }
    let prefix: String = chars.iter().take(6).collect();
    let suffix: String = chars[chars.len() - 4..].iter().collect();
    format!("{prefix}…{suffix}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mask_never_reveals_middle() {
        let m = mask("sk-ant-api03-SECRETSECRETSECRET-7f3a");
        assert_eq!(m, "sk-ant…7f3a");
        assert_eq!(mask("short"), "••••");
    }

    #[test]
    fn validates_secret_shape() {
        assert!(validate_secret("  ").is_err());
        assert!(validate_secret("a\nb").is_err());
        assert_eq!(validate_secret(" abc ").unwrap(), "abc");
    }
}

/// Requires a running OS credential store (on Linux: a Secret Service such as GNOME Keyring).
/// Run with `cargo test -p atlas-core os_keyring -- --ignored`.
#[cfg(test)]
mod os_store_tests {
    use super::*;

    #[test]
    #[ignore]
    fn os_keyring_roundtrip() {
        let store = OsKeyring;
        store.health().expect("credential store reachable");
        let account = format!("test:{}", uuid::Uuid::new_v4());
        assert_eq!(store.get(&account).unwrap(), None);
        store.set(&account, "sk-test-roundtrip-value-1234").unwrap();
        assert_eq!(store.get(&account).unwrap().as_deref(), Some("sk-test-roundtrip-value-1234"));
        store.delete(&account).unwrap();
        assert_eq!(store.get(&account).unwrap(), None);
        store.delete(&account).expect("deleting a missing entry is not an error");
    }
}
