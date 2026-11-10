//! ATLAS Co-Pilot core: the trusted layer that owns providers, credentials, tools,
//! permissions, approvals, tasks, memory and storage. See docs/ARCHITECTURE.md.
pub mod ai;
pub mod app;
pub mod approvals;
pub mod audit;
pub mod context;
pub mod conversations;
pub mod credentials;
pub mod engine;
pub mod error;
pub mod events;
pub mod forge;
pub mod grants;
pub mod integrations;
pub mod map;
pub mod memory;
pub mod policy;
pub mod pricing;
pub mod projects;
pub mod providers;
pub mod redact;
pub mod settings;
pub mod sibling;
pub mod storage;
pub mod tasks;
pub mod tools;
pub mod usage;
pub mod desktop;
pub mod voice;
pub mod workspace;

pub use app::{Atlas, AtlasConfig};
