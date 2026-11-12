//! Permission policy. Enforced in the trusted dispatcher; the model's prompt only describes it.

use crate::settings::{GatePolicy, Settings};
use crate::tools::PermissionClass;
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "decision", rename_all = "snake_case")]
pub enum Decision {
    Allow,
    Ask,
    Deny { reason: String },
}

/// Decide for a specific tool. The owner's task list has its own gate: adding or editing a
/// to-do is local and reversible, so it follows `permissions.planner` instead of the general
/// local-write gate. Everything else (including deleting a task, which is consequential) goes
/// through `decide`.
pub fn decide_tool(category: &str, class: PermissionClass, network: bool, settings: &Settings) -> Decision {
    if category == "planner" && class == PermissionClass::LocalWrite && !network {
        return match settings.permissions.planner {
            GatePolicy::Ask => Decision::Ask,
            GatePolicy::Allow => Decision::Allow,
        };
    }
    decide(class, network, settings)
}

pub fn decide(class: PermissionClass, network: bool, settings: &Settings) -> Decision {
    if network && settings.network.offline_mode {
        return Decision::Deny { reason: "offline mode is on, so network tools are disabled".into() };
    }
    let gate = |g: GatePolicy| match g {
        GatePolicy::Ask => Decision::Ask,
        GatePolicy::Allow => Decision::Allow,
    };
    match class {
        PermissionClass::Destructive => Decision::Deny {
            reason: "destructive and privileged operations are not permitted".into(),
        },
        // Consequential actions always require a fresh, action-specific approval.
        PermissionClass::Consequential => Decision::Ask,
        PermissionClass::LocalWrite => {
            let d = gate(settings.permissions.local_write);
            if network && d == Decision::Allow { gate(settings.permissions.network_tools) } else { d }
        }
        PermissionClass::ReadOnly if network => gate(settings.permissions.network_tools),
        PermissionClass::ReadOnly => Decision::Allow,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matrix() {
        let mut s = Settings::default();
        assert_eq!(decide(PermissionClass::ReadOnly, false, &s), Decision::Allow);
        assert_eq!(decide(PermissionClass::ReadOnly, true, &s), Decision::Ask);
        assert_eq!(decide(PermissionClass::LocalWrite, false, &s), Decision::Ask);
        assert_eq!(decide(PermissionClass::Consequential, false, &s), Decision::Ask);
        assert!(matches!(decide(PermissionClass::Destructive, false, &s), Decision::Deny { .. }));
        s.permissions.local_write = GatePolicy::Allow;
        s.permissions.network_tools = GatePolicy::Allow;
        assert_eq!(decide(PermissionClass::LocalWrite, false, &s), Decision::Allow);
        // Settings can never relax consequential or destructive classes.
        assert_eq!(decide(PermissionClass::Consequential, false, &s), Decision::Ask);
        assert!(matches!(decide(PermissionClass::Destructive, false, &s), Decision::Deny { .. }));
        s.network.offline_mode = true;
        assert!(matches!(decide(PermissionClass::ReadOnly, true, &s), Decision::Deny { .. }));

        // The task list has its own gate; it never loosens anything else.
        let mut s = Settings::default();
        assert_eq!(decide_tool("planner", PermissionClass::LocalWrite, false, &s), Decision::Allow);
        assert_eq!(decide_tool("files", PermissionClass::LocalWrite, false, &s), Decision::Ask);
        assert_eq!(decide_tool("planner", PermissionClass::Consequential, false, &s), Decision::Ask, "deleting a task always asks");
        assert!(matches!(decide_tool("planner", PermissionClass::Destructive, false, &s), Decision::Deny { .. }));
        assert_eq!(decide_tool("planner", PermissionClass::LocalWrite, true, &s), Decision::Ask, "a networked tool cannot hide in the planner category");
        s.permissions.planner = GatePolicy::Ask;
        assert_eq!(decide_tool("planner", PermissionClass::LocalWrite, false, &s), Decision::Ask);
    }
}
