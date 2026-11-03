# Developing a tool

Tools live in `core/src/tools/builtin/` and implement `Tool` (`core/src/tools/mod.rs`).

```rust
pub struct WordCount(ToolDescriptor);

impl WordCount {
    pub fn new() -> Self {
        Self(descriptor(
            "text.word_count",                 // unique id: lowercase, dotted
            "Word count",                       // display name
            "Count words in the given text.",   // what the model sees
            "compute",                          // category (map group)
            PermissionClass::ReadOnly,          // read_only | local_write | consequential | destructive
            false,                              // sends data off this computer?
            json!({"type":"object","properties":{"text":{"type":"string","maxLength":100000}},
                   "required":["text"],"additionalProperties":false}),
            json!({"type":"object","properties":{"words":{"type":"integer"}},"required":["words"]}),
            5,                                  // timeout (seconds)
            "Only the text in the request.",    // data scope shown to the user
        ))
    }
}

#[async_trait]
impl Tool for WordCount {
    fn descriptor(&self) -> &ToolDescriptor { &self.0 }
    async fn execute(&self, input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        Ok(json!({"words": input["text"].as_str().unwrap_or("").split_whitespace().count()}))
    }
}
```

Register it in `builtin::register_all`. It then appears automatically in the model's tool list (when enabled,
available and permitted), Integrations → Tools, the command palette, and the Atlas Map.

## Rules

* **Never** call `execute` yourself; the dispatcher validates input, applies policy, obtains approval, enforces
  timeouts and validates output.
* Declare the narrowest permission class. Anything that writes is at least `LocalWrite`; anything that sends,
  publishes or changes external state is `Consequential`.
* Implement `preview` for gated tools: the approval card must show the exact target and content.
* Implement `availability` when the tool needs configuration (workspace, integration key).
* Treat everything you read (files, web) as untrusted; label it as such in the output.
* Verify outcomes (re-read what you wrote) instead of trusting a call's return.
* Use `ctx.secrets` only for your own integration's key; never return or log secrets.
* Add tests: input validation, permission behaviour and a real execution.

## Planned: external tools

User-defined HTTP tools and plugin protocols are designed to run **outside** the privileged process with
declared schemas and permission classes, and to require explicit approval before they are enabled. They are not
implemented in this version.
