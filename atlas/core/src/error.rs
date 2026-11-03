//! Error type shared by the core. Every variant serialises to `{ code, message }` so the
//! desktop shell can forward it to the UI. Messages must never contain secrets: anything that
//! could carry provider output or user paths is passed through [`crate::redact`] first.

use serde::Serialize;

#[derive(Debug, thiserror::Error)]
pub enum AtlasError {
    #[error("storage error: {0}")]
    Storage(String),
    #[error("invalid input: {0}")]
    Validation(String),
    #[error("not found: {0}")]
    NotFound(String),
    #[error("permission denied: {0}")]
    PermissionDenied(String),
    #[error("credential store: {0}")]
    Credential(String),
    #[error("provider error: {0}")]
    Provider(#[from] crate::ai::ProviderError),
    #[error("tool error: {0}")]
    Tool(String),
    #[error("cancelled")]
    Cancelled,
    #[error("timed out: {0}")]
    Timeout(String),
    #[error("conflict: {0}")]
    Conflict(String),
    #[error("io error: {0}")]
    Io(String),
    #[error("internal error: {0}")]
    Internal(String),
}

impl AtlasError {
    pub fn code(&self) -> &'static str {
        match self {
            AtlasError::Storage(_) => "storage",
            AtlasError::Validation(_) => "validation",
            AtlasError::NotFound(_) => "not_found",
            AtlasError::PermissionDenied(_) => "permission_denied",
            AtlasError::Credential(_) => "credential",
            AtlasError::Provider(_) => "provider",
            AtlasError::Tool(_) => "tool",
            AtlasError::Cancelled => "cancelled",
            AtlasError::Timeout(_) => "timeout",
            AtlasError::Conflict(_) => "conflict",
            AtlasError::Io(_) => "io",
            AtlasError::Internal(_) => "internal",
        }
    }
}

impl From<rusqlite::Error> for AtlasError {
    fn from(e: rusqlite::Error) -> Self {
        match e {
            rusqlite::Error::QueryReturnedNoRows => AtlasError::NotFound("record".into()),
            other => AtlasError::Storage(other.to_string()),
        }
    }
}

impl From<std::io::Error> for AtlasError {
    fn from(e: std::io::Error) -> Self {
        AtlasError::Io(e.to_string())
    }
}

impl From<serde_json::Error> for AtlasError {
    fn from(e: serde_json::Error) -> Self {
        AtlasError::Validation(format!("json: {e}"))
    }
}

#[derive(Serialize)]
struct WireError<'a> {
    code: &'a str,
    message: String,
}

impl Serialize for AtlasError {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        WireError { code: self.code(), message: crate::redact::redact(&self.to_string()) }.serialize(s)
    }
}

pub type Result<T> = std::result::Result<T, AtlasError>;
