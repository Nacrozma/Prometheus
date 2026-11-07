//! Global change notifications. The core emits coarse "topic changed" events; the UI refetches
//! the affected data. Per-turn streaming uses a dedicated sink (see `engine`).

use serde::Serialize;
use std::sync::Arc;

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Topic {
    Tasks,
    Approvals,
    Registry,
    Providers,
    Memory,
    Projects,
    Conversations,
    Settings,
    Usage,
    Forge,
    Siblings,
    Missions,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChangeEvent {
    pub topic: Topic,
    /// Optional id of the record that changed.
    pub id: Option<String>,
}

pub trait EventBus: Send + Sync {
    fn changed(&self, event: ChangeEvent);
}

pub type SharedBus = Arc<dyn EventBus>;

/// Bus that drops events (headless use and tests).
pub struct NullBus;
impl EventBus for NullBus {
    fn changed(&self, _event: ChangeEvent) {}
}

/// Bus that records events (tests).
#[derive(Default)]
pub struct RecordingBus(pub std::sync::Mutex<Vec<ChangeEvent>>);
impl EventBus for RecordingBus {
    fn changed(&self, event: ChangeEvent) {
        if let Ok(mut v) = self.0.lock() {
            v.push(event);
        }
    }
}

pub fn notify(bus: &SharedBus, topic: Topic, id: Option<&str>) {
    bus.changed(ChangeEvent { topic, id: id.map(str::to_string) });
}
