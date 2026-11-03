//! Text transformation and structured-data conversion.

use super::descriptor;
use crate::tools::{PermissionClass, Tool, ToolContext, ToolDescriptor, ToolError};
use async_trait::async_trait;
use serde_json::{json, Map, Value};

pub struct Transform(ToolDescriptor);

const OPS: &[&str] = &[
    "uppercase", "lowercase", "title_case", "word_count", "sort_lines", "dedupe_lines", "trim_lines",
    "json_format", "json_minify", "csv_to_json", "json_to_csv", "extract_urls", "extract_emails",
];

impl Transform {
    pub fn new() -> Self {
        Self(descriptor(
            "text.transform",
            "Text & data transform",
            "Deterministically transform text: change case, count words, sort or de-duplicate lines, \
             pretty-print or minify JSON, convert CSV↔JSON (CSV with a header row; JSON as an array of flat objects), \
             or extract URLs/emails.",
            "compute",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{
                "operation":{"type":"string","enum":OPS},
                "text":{"type":"string","maxLength":200000}
            },"required":["operation","text"],"additionalProperties":false}),
            json!({"type":"object","properties":{"operation":{"type":"string"},"result":{}},"required":["operation","result"]}),
            5,
            "Operates only on the text provided in the request.",
        ))
    }
}

impl Default for Transform {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for Transform {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        let op = input["operation"].as_str().unwrap_or_default();
        let text = input["text"].as_str().unwrap_or_default();
        let result = apply(op, text).map_err(|m| ToolError::new("transform_failed", m))?;
        Ok(json!({"operation": op, "result": result}))
    }
}

pub fn apply(op: &str, text: &str) -> Result<Value, String> {
    Ok(match op {
        "uppercase" => json!(text.to_uppercase()),
        "lowercase" => json!(text.to_lowercase()),
        "title_case" => json!(text
            .split(' ')
            .map(|w| {
                let mut c = w.chars();
                match c.next() {
                    Some(f) => f.to_uppercase().collect::<String>() + &c.as_str().to_lowercase(),
                    None => String::new(),
                }
            })
            .collect::<Vec<_>>()
            .join(" ")),
        "word_count" => json!({
            "words": text.split_whitespace().count(),
            "characters": text.chars().count(),
            "lines": if text.is_empty() { 0 } else { text.lines().count() },
        }),
        "sort_lines" => {
            let mut l: Vec<&str> = text.lines().collect();
            l.sort_unstable();
            json!(l.join("\n"))
        }
        "dedupe_lines" => {
            let mut seen = std::collections::HashSet::new();
            json!(text.lines().filter(|l| seen.insert(*l)).collect::<Vec<_>>().join("\n"))
        }
        "trim_lines" => json!(text.lines().map(str::trim).collect::<Vec<_>>().join("\n")),
        "json_format" => json!(serde_json::to_string_pretty(&parse_json(text)?).unwrap_or_default()),
        "json_minify" => json!(parse_json(text)?.to_string()),
        "csv_to_json" => Value::Array(parse_csv(text)?.into_iter().map(Value::Object).collect()),
        "json_to_csv" => json!(to_csv(&parse_json(text)?)?),
        "extract_urls" => json!(find_all(r#"https?://[^\s<>"')\]]+"#, text)),
        "extract_emails" => json!(find_all(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)),
        other => return Err(format!("unknown operation '{other}'")),
    })
}

fn parse_json(text: &str) -> Result<Value, String> {
    serde_json::from_str(text).map_err(|e| format!("invalid JSON: {e}"))
}

fn find_all(pattern: &str, text: &str) -> Vec<String> {
    let re = regex::Regex::new(pattern).expect("static regex");
    let mut v: Vec<String> = re.find_iter(text).map(|m| m.as_str().to_string()).collect();
    v.dedup();
    v.truncate(500);
    v
}

/// RFC 4180-style CSV parsing (quoted fields, escaped quotes, embedded newlines).
pub fn parse_csv_rows(text: &str) -> Result<Vec<Vec<String>>, String> {
    let mut rows = Vec::new();
    let mut row = Vec::new();
    let mut field = String::new();
    let mut in_quotes = false;
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if in_quotes {
            match c {
                '"' if chars.peek() == Some(&'"') => {
                    field.push('"');
                    chars.next();
                }
                '"' => in_quotes = false,
                _ => field.push(c),
            }
        } else {
            match c {
                '"' if field.is_empty() => in_quotes = true,
                ',' => row.push(std::mem::take(&mut field)),
                '\r' => {}
                '\n' => {
                    row.push(std::mem::take(&mut field));
                    rows.push(std::mem::take(&mut row));
                }
                _ => field.push(c),
            }
        }
    }
    if in_quotes {
        return Err("unterminated quoted field".into());
    }
    if !field.is_empty() || !row.is_empty() {
        row.push(field);
        rows.push(row);
    }
    Ok(rows)
}

pub fn parse_csv(text: &str) -> Result<Vec<Map<String, Value>>, String> {
    let rows = parse_csv_rows(text)?;
    let mut it = rows.into_iter();
    let header = it.next().ok_or("CSV is empty")?;
    Ok(it
        .filter(|r| !(r.len() == 1 && r[0].is_empty()))
        .map(|r| {
            header
                .iter()
                .enumerate()
                .map(|(i, h)| (h.clone(), Value::String(r.get(i).cloned().unwrap_or_default())))
                .collect()
        })
        .collect())
}

fn csv_escape(s: &str) -> String {
    if s.contains([',', '"', '\n', '\r']) { format!("\"{}\"", s.replace('"', "\"\"")) } else { s.to_string() }
}

pub fn to_csv(v: &Value) -> Result<String, String> {
    let arr = v.as_array().ok_or("JSON must be an array of objects")?;
    let mut headers: Vec<String> = Vec::new();
    for item in arr {
        let obj = item.as_object().ok_or("every array item must be an object")?;
        for k in obj.keys() {
            if !headers.contains(k) {
                headers.push(k.clone());
            }
        }
    }
    let mut out = headers.iter().map(|h| csv_escape(h)).collect::<Vec<_>>().join(",");
    for item in arr {
        out.push('\n');
        let line: Vec<String> = headers
            .iter()
            .map(|h| match &item[h] {
                Value::Null => String::new(),
                Value::String(s) => csv_escape(s),
                other => csv_escape(&other.to_string()),
            })
            .collect();
        out.push_str(&line.join(","));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn csv_roundtrip_with_quotes() {
        let csv = "name,note\n\"Lee, A\",\"said \"\"hi\"\"\"\nBo,\"multi\nline\"\n";
        let json = apply("csv_to_json", csv).unwrap();
        assert_eq!(json[0]["name"], "Lee, A");
        assert_eq!(json[0]["note"], "said \"hi\"");
        assert_eq!(json[1]["note"], "multi\nline");
        let back = apply("json_to_csv", &json.to_string()).unwrap();
        assert_eq!(apply("csv_to_json", back.as_str().unwrap()).unwrap(), json);
    }

    #[test]
    fn misc_ops() {
        assert_eq!(apply("word_count", "a b\nc").unwrap()["words"], 3);
        assert_eq!(apply("dedupe_lines", "a\nb\na").unwrap(), "a\nb");
        assert_eq!(apply("extract_emails", "x a@b.co y").unwrap()[0], "a@b.co");
        assert!(apply("json_format", "{bad").is_err());
    }
}
