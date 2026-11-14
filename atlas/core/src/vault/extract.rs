//! Text extraction for the Knowledge Vault: TXT, Markdown, PDF and DOCX, all in-process and local.
//!
//! Every format is checked by its content, not only its extension (a PDF must start with `%PDF-`, a
//! DOCX must be a zip holding `word/document.xml`, text must decode as text). Nothing in a document
//! is executed: DOCX macros (`vbaProject.bin`), embedded objects and external links are never read;
//! Markdown and HTML are kept as text and never rendered as markup. Limits bound the work a hostile
//! file can cause (decompressed size per PDF page and per DOCX part, total extracted characters).

use crate::error::{AtlasError, Result};
use std::io::Read;

/// Bump when extraction output changes, so documents can be re-indexed.
pub const EXTRACTOR_VERSION: i64 = 1;
/// Largest file accepted for import.
pub const MAX_FILE_BYTES: u64 = 50 * 1024 * 1024;
/// Most text kept from one document.
pub const MAX_CHARS: usize = 5_000_000;
/// Most decompressed content per PDF page.
const MAX_PDF_PAGE_BYTES: usize = 32 * 1024 * 1024;
/// Most decompressed bytes read from one DOCX part (against zip bombs).
const MAX_DOCX_PART_BYTES: u64 = 64 * 1024 * 1024;
/// Most pages read from one PDF.
const MAX_PDF_PAGES: u32 = 5_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Txt,
    Md,
    Pdf,
    Docx,
}

impl Kind {
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Txt => "txt",
            Kind::Md => "md",
            Kind::Pdf => "pdf",
            Kind::Docx => "docx",
        }
    }
    pub fn parse(s: &str) -> Option<Kind> {
        match s {
            "txt" => Some(Kind::Txt),
            "md" => Some(Kind::Md),
            "pdf" => Some(Kind::Pdf),
            "docx" => Some(Kind::Docx),
            _ => None,
        }
    }
    /// From a file name's extension (the claim, checked against the content by [`sniff`]).
    pub fn from_name(name: &str) -> Option<Kind> {
        let ext = name.rsplit_once('.')?.1.to_ascii_lowercase();
        match ext.as_str() {
            "txt" | "text" => Some(Kind::Txt),
            "md" | "markdown" => Some(Kind::Md),
            "pdf" => Some(Kind::Pdf),
            "docx" => Some(Kind::Docx),
            _ => None,
        }
    }
}

/// A stretch of a document with one location: a PDF page, or a heading path in text formats.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Section {
    pub page: Option<u32>,
    /// Heading path, e.g. "Budget › Travel"; empty when there is none.
    pub heading: String,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct Extracted {
    pub sections: Vec<Section>,
    /// Title from the document's own metadata, when it has one.
    pub title: Option<String>,
    pub pages: Option<u32>,
    /// Pages (PDF) that could not be read and were skipped.
    pub skipped_pages: u32,
}

impl Extracted {
    pub fn chars(&self) -> usize {
        self.sections.iter().map(|s| s.text.chars().count()).sum()
    }
}

/// Check that the content really is the kind the name claims. Returns the kind to use.
pub fn sniff(claimed: Kind, bytes: &[u8]) -> Result<Kind> {
    let pdf = bytes.len() >= 5 && bytes[..bytes.len().min(1024)].windows(5).any(|w| w == b"%PDF-");
    let zip = bytes.starts_with(b"PK\x03\x04");
    match claimed {
        Kind::Pdf if pdf => Ok(Kind::Pdf),
        Kind::Pdf => Err(AtlasError::Validation("this file is named .pdf but is not a PDF".into())),
        Kind::Docx if zip => Ok(Kind::Docx),
        Kind::Docx => Err(AtlasError::Validation("this file is named .docx but is not a Word document".into())),
        Kind::Txt | Kind::Md => {
            if pdf || zip {
                return Err(AtlasError::Validation("this file is named as text but contains a PDF or zip archive".into()));
            }
            if bytes[..bytes.len().min(8192)].contains(&0) && !bytes.starts_with(&[0xFF, 0xFE]) && !bytes.starts_with(&[0xFE, 0xFF]) {
                return Err(AtlasError::Validation("this file is named as text but contains binary data".into()));
            }
            Ok(claimed)
        }
    }
}

/// Extract the text of a document whose kind was checked with [`sniff`].
pub fn extract(kind: Kind, bytes: &[u8], cancel: &dyn Fn() -> bool) -> Result<Extracted> {
    let out = match kind {
        Kind::Txt => Ok(txt(&decode_text(bytes))),
        Kind::Md => Ok(markdown(&decode_text(bytes))),
        Kind::Pdf => pdf(bytes, cancel),
        Kind::Docx => docx(bytes, cancel),
    }?;
    Ok(cap(out))
}

/// Keep at most [`MAX_CHARS`] characters.
fn cap(mut e: Extracted) -> Extracted {
    let mut left = MAX_CHARS;
    e.sections.retain_mut(|s| {
        if left == 0 {
            return false;
        }
        let n = s.text.chars().count();
        if n > left {
            s.text = s.text.chars().take(left).collect();
        }
        left = left.saturating_sub(n);
        true
    });
    e
}

/// Text in UTF-8 (with or without BOM), UTF-16 with a BOM, or else Windows-1252. Never fails:
/// undecodable bytes become U+FFFD.
pub fn decode_text(bytes: &[u8]) -> String {
    let (enc, rest) = if let Some(r) = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]) {
        (encoding_rs::UTF_8, r)
    } else if let Some(r) = bytes.strip_prefix(&[0xFF, 0xFE]) {
        (encoding_rs::UTF_16LE, r)
    } else if let Some(r) = bytes.strip_prefix(&[0xFE, 0xFF]) {
        (encoding_rs::UTF_16BE, r)
    } else if std::str::from_utf8(bytes).is_ok() {
        (encoding_rs::UTF_8, bytes)
    } else {
        (encoding_rs::WINDOWS_1252, bytes)
    };
    let (text, _, _) = enc.decode(rest);
    text.replace("\r\n", "\n").replace('\r', "\n")
}

fn txt(text: &str) -> Extracted {
    Extracted { sections: vec![Section { page: None, heading: String::new(), text: text.trim().to_string() }].into_iter().filter(|s| !s.text.is_empty()).collect(), ..Default::default() }
}

/// Markdown: sections by heading (ATX `#` and Setext underlines), code fences kept verbatim (a `#`
/// inside code is not a heading). Everything is kept as text.
fn markdown(text: &str) -> Extracted {
    let mut stack: Vec<(usize, String)> = Vec::new();
    let mut sections = Vec::new();
    let mut cur = String::new();
    let mut fence: Option<&str> = None;
    let lines: Vec<&str> = text.lines().collect();
    let path = |stack: &[(usize, String)]| stack.iter().map(|(_, h)| h.as_str()).collect::<Vec<_>>().join(" › ");
    let flush = |stack: &[(usize, String)], cur: &mut String, sections: &mut Vec<Section>| {
        let t = cur.trim();
        if !t.is_empty() {
            sections.push(Section { page: None, heading: path(stack), text: t.to_string() });
        }
        cur.clear();
    };
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i];
        let trimmed = line.trim_start();
        if let Some(f) = fence {
            cur.push_str(line);
            cur.push('\n');
            if trimmed.starts_with(f) {
                fence = None;
            }
            i += 1;
            continue;
        }
        if trimmed.starts_with("```") || trimmed.starts_with("~~~") {
            fence = Some(if trimmed.starts_with("```") { "```" } else { "~~~" });
            cur.push_str(line);
            cur.push('\n');
            i += 1;
            continue;
        }
        let hashes = trimmed.chars().take_while(|c| *c == '#').count();
        let atx = (1..=6).contains(&hashes) && trimmed[hashes..].starts_with([' ', '\t']) && line.len() - trimmed.len() < 4;
        let setext = !line.trim().is_empty()
            && lines.get(i + 1).is_some_and(|n| {
                let n = n.trim();
                n.len() >= 2 && (n.chars().all(|c| c == '=') || n.chars().all(|c| c == '-'))
            })
            && !trimmed.starts_with(['-', '*', '>', '|']);
        if atx || setext {
            flush(&stack, &mut cur, &mut sections);
            let (level, title) = if atx {
                (hashes, trimmed[hashes..].trim().trim_end_matches('#').trim().to_string())
            } else {
                (if lines[i + 1].trim().starts_with('=') { 1 } else { 2 }, line.trim().to_string())
            };
            while stack.last().is_some_and(|(l, _)| *l >= level) {
                stack.pop();
            }
            stack.push((level, title.chars().take(200).collect()));
            i += if setext { 2 } else { 1 };
            continue;
        }
        cur.push_str(line);
        cur.push('\n');
        i += 1;
    }
    flush(&stack, &mut cur, &mut sections);
    Extracted { sections, ..Default::default() }
}

fn pdf(bytes: &[u8], cancel: &dyn Fn() -> bool) -> Result<Extracted> {
    let has_encrypt = bytes.windows(8).any(|w| w == b"/Encrypt");
    let mut doc = match lopdf::Document::load_mem(bytes) {
        Ok(d) => d,
        Err(_) if has_encrypt => return Err(AtlasError::Validation("this PDF is password-protected; Atlas cannot open protected PDFs yet".into())),
        Err(e) => return Err(AtlasError::Validation(format!("this PDF could not be read (damaged or unsupported): {}", short(&e.to_string())))),
    };
    if doc.is_encrypted() {
        return Err(AtlasError::Validation("this PDF is password-protected; Atlas cannot open protected PDFs yet".into()));
    }
    let pages = doc.get_pages();
    let total = pages.len() as u32;
    if total == 0 {
        return Err(AtlasError::Validation("this PDF has no pages".into()));
    }
    let mut sections = Vec::new();
    let mut skipped = 0;
    for &n in pages.keys().take(MAX_PDF_PAGES as usize) {
        if cancel() {
            return Err(AtlasError::Cancelled);
        }
        if let Some(&page_id) = pages.get(&n) {
            mark_line_moves(&mut doc, page_id);
        }
        match doc.extract_text_with_limit(&[n], MAX_PDF_PAGE_BYTES) {
            Ok(t) => {
                let t = tidy_pdf_text(&t);
                if !t.is_empty() {
                    sections.push(Section { page: Some(n), heading: String::new(), text: t });
                }
            }
            Err(_) => skipped += 1,
        }
    }
    if sections.is_empty() {
        let why = if skipped == total {
            "no page of this PDF could be read".to_string()
        } else {
            "this PDF has no text layer (it may be scanned images); text recognition (OCR) is not available yet, so it cannot be searched".to_string()
        };
        return Err(AtlasError::Validation(why));
    }
    Ok(Extracted { sections, title: pdf_title(&doc), pages: Some(total), skipped_pages: skipped })
}

/// lopdf ends a line of text only at `T*` and `ET`, but many PDFs start each new line with a
/// positioning operator (`Td`/`TD` with a vertical move, or `Tm`). Without a break there, the last word
/// of one line and the first of the next run together ("staffingThe") and neither can be found. This
/// adds a `T*` before every vertical move (extraction only; the stored document is not changed).
fn mark_line_moves(doc: &mut lopdf::Document, page_id: lopdf::ObjectId) {
    use lopdf::content::{Content, Operation};
    let Ok(bytes) = doc.get_page_content_with_limit(page_id, MAX_PDF_PAGE_BYTES) else { return };
    let Ok(content) = Content::decode(&bytes) else { return };
    let num = |o: &lopdf::Object| match o {
        lopdf::Object::Integer(i) => Some(*i as f64),
        lopdf::Object::Real(r) => Some(*r as f64),
        _ => None,
    };
    let mut ops = Vec::with_capacity(content.operations.len() + 16);
    let mut changed = false;
    for op in content.operations {
        let vertical = match op.operator.as_str() {
            "Td" | "TD" => op.operands.get(1).and_then(num).is_some_and(|y| y.abs() > 0.01),
            "Tm" | "'" | "\"" => true,
            _ => false,
        };
        if vertical {
            ops.push(Operation::new("T*", vec![]));
            changed = true;
        }
        ops.push(op);
    }
    if changed && let Ok(enc) = (Content { operations: ops }).encode() {
        let _ = doc.change_page_content(page_id, enc);
    }
}

/// lopdf puts each text run on its own line; join lines into paragraphs where the page has no
/// blank lines, keep blank lines as paragraph breaks.
fn tidy_pdf_text(t: &str) -> String {
    let mut out = String::new();
    for line in t.lines() {
        let l = line.trim();
        if l.is_empty() {
            if !out.ends_with("\n\n") && !out.is_empty() {
                out.push_str("\n\n");
            }
            continue;
        }
        if !out.is_empty() && !out.ends_with('\n') {
            // A word broken across lines ("manage-" / "ment") is joined; otherwise lines join with a space.
            let broken = out.ends_with('-') && out.chars().rev().nth(1).is_some_and(char::is_alphabetic) && l.starts_with(char::is_lowercase);
            if broken {
                out.pop();
            } else {
                out.push(' ');
            }
        }
        out.push_str(l);
    }
    out.trim().to_string()
}

fn pdf_title(doc: &lopdf::Document) -> Option<String> {
    let info = doc.trailer.get(b"Info").ok()?.as_reference().ok()?;
    let title = doc.get_dictionary(info).ok()?.get(b"Title").ok()?.as_str().ok()?;
    let t = if let Some(rest) = title.strip_prefix(&[0xFE, 0xFF]) {
        let units: Vec<u16> = rest.chunks_exact(2).map(|c| u16::from_be_bytes([c[0], c[1]])).collect();
        String::from_utf16_lossy(&units)
    } else {
        title.iter().map(|&b| b as char).collect()
    };
    let t = t.trim().chars().filter(|c| !c.is_control()).take(200).collect::<String>();
    (!t.is_empty()).then_some(t)
}

fn short(s: &str) -> String {
    s.chars().take(160).collect()
}

/// Read one part of a zip with a decompressed-size cap.
fn zip_part(zip: &mut zip::ZipArchive<std::io::Cursor<&[u8]>>, name: &str) -> Result<Option<String>> {
    let Ok(file) = zip.by_name(name) else { return Ok(None) };
    let mut buf = Vec::new();
    file.take(MAX_DOCX_PART_BYTES + 1).read_to_end(&mut buf).map_err(|e| AtlasError::Validation(format!("the Word document could not be read: {e}")))?;
    if buf.len() as u64 > MAX_DOCX_PART_BYTES {
        return Err(AtlasError::Validation("the Word document is too large once decompressed".into()));
    }
    Ok(Some(String::from_utf8_lossy(&buf).into_owned()))
}

/// DOCX: paragraphs, headings (Heading1-9, Title), list items, tables (cells separated by " | ").
/// Only `word/document.xml` and `docProps/core.xml` are read.
fn docx(bytes: &[u8], cancel: &dyn Fn() -> bool) -> Result<Extracted> {
    let mut zip = zip::ZipArchive::new(std::io::Cursor::new(bytes)).map_err(|_| AtlasError::Validation("this Word document could not be opened (damaged or not a .docx)".into()))?;
    let Some(xml) = zip_part(&mut zip, "word/document.xml")? else {
        return Err(AtlasError::Validation("this file is a zip archive but not a Word document".into()));
    };
    let title = zip_part(&mut zip, "docProps/core.xml")?.and_then(|c| core_title(&c));
    use quick_xml::events::Event;
    let mut reader = quick_xml::Reader::from_str(&xml);
    let mut stack: Vec<(usize, String)> = Vec::new();
    let mut sections: Vec<Section> = Vec::new();
    let mut body = String::new();
    let mut para = String::new();
    let mut in_text = false;
    let mut level: Option<usize> = None;
    let mut list_item = false;
    let mut table_depth = 0usize;
    let mut row: Vec<String> = Vec::new();
    let mut cell = String::new();
    let mut steps = 0u64;
    let path = |stack: &[(usize, String)]| stack.iter().map(|(_, h)| h.as_str()).collect::<Vec<_>>().join(" › ");
    loop {
        steps += 1;
        if steps.is_multiple_of(20_000) && cancel() {
            return Err(AtlasError::Cancelled);
        }
        match reader.read_event() {
            Ok(Event::Start(e)) | Ok(Event::Empty(e)) => match e.local_name().as_ref() {
                "p" => {
                    para.clear();
                    level = None;
                    list_item = false;
                }
                "t" => in_text = true,
                "tab" => para.push('\t'),
                "br" | "cr" => para.push('\n'),
                "pStyle" => {
                    for a in e.attributes().flatten() {
                        if a.key.local_name().as_ref() == "val" {
                            let v = a.value.to_ascii_lowercase();
                            if v == "title" {
                                level = Some(1);
                            } else if let Some(n) = v.strip_prefix("heading").and_then(|d| d.parse::<usize>().ok()) {
                                level = Some(n.clamp(1, 9));
                            }
                        }
                    }
                }
                "numPr" => list_item = true,
                "tbl" => table_depth += 1,
                "tr" => row.clear(),
                "tc" => cell.clear(),
                _ => {}
            },
            Ok(Event::Text(t)) if in_text => para.push_str(&t.xml10_content()),
            Ok(Event::GeneralRef(r)) if in_text => {
                if let Ok(Some(c)) = r.resolve_char_ref() {
                    para.push(c);
                } else {
                    let name: &str = &r;
                    para.push_str(match name {
                        "amp" => "&",
                        "lt" => "<",
                        "gt" => ">",
                        "quot" => "\"",
                        "apos" => "'",
                        _ => "",
                    });
                }
            }
            Ok(Event::End(e)) => match e.local_name().as_ref() {
                "t" => in_text = false,
                "p" => {
                    let text = para.trim().to_string();
                    if table_depth > 0 {
                        if !text.is_empty() {
                            if !cell.is_empty() {
                                cell.push(' ');
                            }
                            cell.push_str(&text);
                        }
                    } else if let Some(l) = level.filter(|_| !text.is_empty()) {
                        if !body.trim().is_empty() {
                            sections.push(Section { page: None, heading: path(&stack), text: body.trim().to_string() });
                        }
                        body.clear();
                        while stack.last().is_some_and(|(x, _)| *x >= l) {
                            stack.pop();
                        }
                        stack.push((l, text.chars().take(200).collect()));
                    } else if !text.is_empty() {
                        if list_item {
                            body.push_str("• ");
                        }
                        body.push_str(&text);
                        body.push_str(if list_item { "\n" } else { "\n\n" });
                    }
                }
                "tc" => row.push(std::mem::take(&mut cell)),
                "tr" => {
                    if table_depth == 1 && row.iter().any(|c| !c.is_empty()) {
                        body.push_str(&row.join(" | "));
                        body.push('\n');
                    }
                }
                "tbl" => {
                    table_depth = table_depth.saturating_sub(1);
                    if table_depth == 0 {
                        body.push('\n');
                    }
                }
                _ => {}
            },
            Ok(Event::Eof) => break,
            Err(e) => return Err(AtlasError::Validation(format!("this Word document could not be read (damaged XML): {}", short(&e.to_string())))),
            _ => {}
        }
    }
    if !body.trim().is_empty() {
        sections.push(Section { page: None, heading: path(&stack), text: body.trim().to_string() });
    }
    if sections.is_empty() {
        return Err(AtlasError::Validation("this Word document has no text".into()));
    }
    Ok(Extracted { sections, title, pages: None, skipped_pages: 0 })
}

fn core_title(xml: &str) -> Option<String> {
    let start = xml.find("<dc:title>")? + "<dc:title>".len();
    let end = xml[start..].find("</dc:title>")? + start;
    let t = quick_xml::escape::unescape(&xml[start..end]).ok()?.trim().chars().filter(|c| !c.is_control()).take(200).collect::<String>();
    (!t.is_empty()).then_some(t)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn content_must_match_the_name() {
        assert_eq!(sniff(Kind::Pdf, b"%PDF-1.7\n...").unwrap(), Kind::Pdf);
        assert!(sniff(Kind::Pdf, b"hello").is_err());
        assert!(sniff(Kind::Docx, b"%PDF-1.4").is_err());
        assert!(sniff(Kind::Txt, b"PK\x03\x04rest").is_err());
        assert!(sniff(Kind::Md, b"abc\0def").is_err());
        assert!(sniff(Kind::Txt, &[0xFF, 0xFE, b'h', 0]).is_ok(), "UTF-16 text with a BOM is text");
        assert_eq!(Kind::from_name("Report.PDF"), Some(Kind::Pdf));
        assert_eq!(Kind::from_name("notes.exe"), None);
    }

    #[test]
    fn text_decodes_any_common_encoding() {
        assert_eq!(decode_text("caf\u{e9}".as_bytes()), "café");
        assert_eq!(decode_text(&[b'c', b'a', b'f', 0xE9]), "café", "Windows-1252 fallback");
        assert_eq!(decode_text(&[0xFF, 0xFE, b'h', 0, b'i', 0]), "hi");
        assert_eq!(decode_text(b"a\r\nb"), "a\nb");
    }

    #[test]
    fn markdown_sections_follow_headings_and_ignore_hashes_in_code() {
        let md = "Intro line\n\n# Budget\nTotals here.\n\n## Travel\nTrains.\n```\n# not a heading\n```\nAfter code.\n\nPlan\n====\nSetext body.\n";
        let e = markdown(md);
        let heads: Vec<_> = e.sections.iter().map(|s| s.heading.as_str()).collect();
        assert_eq!(heads, ["", "Budget", "Budget › Travel", "Plan"]);
        assert!(e.sections[2].text.contains("# not a heading"));
        assert!(e.sections[2].text.contains("After code."));
    }

    #[test]
    fn pdf_problems_are_reported_not_hidden() {
        assert!(pdf(b"%PDF-1.4 garbage", &|| false).unwrap_err().to_string().contains("could not be read"));
        let enc = b"%PDF-1.4\n1 0 obj << /Filter /Standard >> endobj\ntrailer << /Encrypt 1 0 R >>\n%%EOF";
        assert!(pdf(enc, &|| false).unwrap_err().to_string().contains("password-protected"));
    }

    #[test]
    fn docx_that_is_not_a_word_document_is_refused() {
        assert!(docx(b"PK\x03\x04not really", &|| false).is_err());
    }
}
