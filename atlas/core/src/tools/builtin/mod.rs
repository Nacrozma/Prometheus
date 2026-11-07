//! Built-in tools. Each one is a real implementation; none returns canned success.

pub mod calc;
pub mod data;
pub mod files;
pub mod forge_tools;
pub mod memory_tools;
pub mod sibling_tools;
pub mod system;
#[cfg(any(test, feature = "test-support"))]
pub mod test_tools;
pub mod text;
pub mod time;
pub mod web;

use super::{PermissionClass, Tool, ToolDescriptor};
use super::registry::ToolRegistry;
use serde_json::Value;
use std::sync::Arc;

#[allow(clippy::too_many_arguments)]
pub(crate) fn descriptor(
    id: &str,
    name: &str,
    description: &str,
    category: &str,
    permission: PermissionClass,
    network: bool,
    input_schema: Value,
    output_schema: Value,
    timeout_secs: u32,
    data_scope: &str,
) -> ToolDescriptor {
    ToolDescriptor {
        id: id.into(),
        name: name.into(),
        description: description.into(),
        category: category.into(),
        version: "1.0.0".into(),
        input_schema,
        output_schema,
        permission,
        network,
        requires: vec![],
        timeout_secs,
        max_output_bytes: 64 * 1024,
        data_scope: data_scope.into(),
    }
}

/// Register every built-in tool.
pub fn register_all(reg: &ToolRegistry) -> crate::error::Result<()> {
    let tools: Vec<Arc<dyn Tool>> = vec![
        Arc::new(calc::Calculator::new()),
        Arc::new(time::Now::new()),
        Arc::new(text::Transform::new()),
        Arc::new(files::ListFiles::new()),
        Arc::new(files::ReadFile::new()),
        Arc::new(files::CreateFile::new()),
        Arc::new(files::DraftDocument::new()),
        Arc::new(system::Diagnostics::new()),
        Arc::new(system::ProviderHealth::new()),
        Arc::new(system::TaskStatus::new()),
        Arc::new(memory_tools::SearchMemory::new()),
        Arc::new(memory_tools::SaveMemory::new()),
        Arc::new(web::WebSearch::new()),
        Arc::new(data::ImportPreview::new()),
        Arc::new(data::Export::new()),
        Arc::new(forge_tools::Tree::new()),
        Arc::new(forge_tools::ReadFile::new()),
        Arc::new(forge_tools::Search::new()),
        Arc::new(forge_tools::GitStatus::new()),
        Arc::new(forge_tools::GitDiff::new()),
        Arc::new(forge_tools::GitLog::new()),
        Arc::new(forge_tools::EditFile::new()),
        Arc::new(forge_tools::WriteFile::new()),
        Arc::new(forge_tools::RunTests::new()),
        Arc::new(forge_tools::RunCommand::new()),
        Arc::new(forge_tools::GitCommit::new()),
        Arc::new(sibling_tools::Consult::new()),
    ];
    for t in tools {
        reg.register(t)?;
    }
    Ok(())
}
