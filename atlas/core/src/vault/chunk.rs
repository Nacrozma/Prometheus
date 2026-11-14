//! Splitting extracted sections into searchable passages.
//!
//! A passage never crosses a section boundary, so its page (PDF) or heading path (text formats) is
//! exact and a citation can point to it. Passages are built from whole paragraphs where possible;
//! a paragraph longer than the maximum is split at sentence ends, then at spaces. Consecutive
//! passages of one section share a short overlap so a sentence at a boundary is still found; the
//! overlap length is stored so the reader can show the text without repeating it.

use super::extract::Section;

/// Bump when chunking changes, so documents can be re-indexed.
pub const INDEX_VERSION: i64 = 1;

#[derive(Debug, Clone, Copy)]
pub struct ChunkConfig {
    /// Aim for passages about this long (characters).
    pub target: usize,
    /// Never longer than this (characters, overlap included).
    pub max: usize,
    /// Characters carried over from the previous passage of the same section.
    pub overlap: usize,
}

impl Default for ChunkConfig {
    fn default() -> Self {
        Self { target: 1100, max: 1800, overlap: 160 }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Chunk {
    pub seq: usize,
    pub page: Option<u32>,
    pub heading: String,
    /// Character offset of the passage's new text (after the overlap) within the whole document.
    pub start_offset: usize,
    /// Characters at the start that repeat the end of the previous passage.
    pub overlap: usize,
    pub content: String,
}

/// Paragraph-ish pieces no longer than `max`.
fn pieces(text: &str, max: usize) -> Vec<String> {
    let mut out = Vec::new();
    for para in text.split("\n\n").map(str::trim).filter(|p| !p.is_empty()) {
        if para.chars().count() <= max {
            out.push(para.to_string());
            continue;
        }
        // Long paragraph: sentences, then words, packed up to `max`.
        let mut cur = String::new();
        for sentence in split_sentences(para) {
            for word_group in split_to(&sentence, max) {
                if cur.chars().count() + word_group.chars().count() + 1 > max && !cur.is_empty() {
                    out.push(std::mem::take(&mut cur));
                }
                if !cur.is_empty() {
                    cur.push(' ');
                }
                cur.push_str(&word_group);
            }
        }
        if !cur.is_empty() {
            out.push(cur);
        }
    }
    out
}

fn split_sentences(p: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let chars: Vec<char> = p.chars().collect();
    for (i, &c) in chars.iter().enumerate() {
        cur.push(c);
        if matches!(c, '.' | '!' | '?') && chars.get(i + 1).is_none_or(|n| n.is_whitespace()) {
            out.push(cur.trim().to_string());
            cur.clear();
        }
    }
    if !cur.trim().is_empty() {
        out.push(cur.trim().to_string());
    }
    out
}

/// Split at spaces (or hard, if one word is longer than `max`).
fn split_to(s: &str, max: usize) -> Vec<String> {
    if s.chars().count() <= max {
        return vec![s.to_string()];
    }
    let mut out = Vec::new();
    let mut cur = String::new();
    for w in s.split_whitespace() {
        let mut w = w.to_string();
        while w.chars().count() > max {
            let head: String = w.chars().take(max).collect();
            w = w.chars().skip(max).collect();
            if !cur.is_empty() {
                out.push(std::mem::take(&mut cur));
            }
            out.push(head);
        }
        if cur.chars().count() + w.chars().count() + 1 > max && !cur.is_empty() {
            out.push(std::mem::take(&mut cur));
        }
        if !cur.is_empty() {
            cur.push(' ');
        }
        cur.push_str(&w);
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

/// The last `n` characters of `s`, starting at a word boundary.
fn tail(s: &str, n: usize) -> String {
    let count = s.chars().count();
    if count <= n {
        return String::new();
    }
    let t: String = s.chars().skip(count - n).collect();
    match t.find(char::is_whitespace) {
        Some(i) => t[i..].trim_start().to_string(),
        None => String::new(),
    }
}

pub fn chunk(sections: &[Section], cfg: ChunkConfig) -> Vec<Chunk> {
    let mut out = Vec::new();
    let mut offset = 0usize;
    for s in sections {
        let body_max = cfg.max.saturating_sub(cfg.overlap + 1).max(200);
        let mut cur = String::new();
        let mut cur_start = offset;
        let mut carried = String::new();
        let emit = |cur: &mut String, carried: &mut String, cur_start: usize, out: &mut Vec<Chunk>| {
            if cur.is_empty() {
                return;
            }
            let (content, overlap) = if carried.is_empty() { (cur.clone(), 0) } else { (format!("{carried} {cur}"), carried.chars().count() + 1) };
            out.push(Chunk { seq: out.len(), page: s.page, heading: s.heading.clone(), start_offset: cur_start, overlap, content });
            *carried = tail(cur, cfg.overlap);
            cur.clear();
        };
        for piece in pieces(&s.text, body_max) {
            let n = piece.chars().count();
            if !cur.is_empty() && cur.chars().count() + n + 2 > cfg.target.min(body_max) {
                let len = cur.chars().count();
                emit(&mut cur, &mut carried, cur_start, &mut out);
                cur_start += len + 2;
            }
            if !cur.is_empty() {
                cur.push_str("\n\n");
            }
            cur.push_str(&piece);
        }
        emit(&mut cur, &mut carried, cur_start, &mut out);
        offset += s.text.chars().count() + 2;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sec(page: Option<u32>, heading: &str, text: &str) -> Section {
        Section { page, heading: heading.into(), text: text.into() }
    }

    #[test]
    fn passages_never_cross_a_page_or_heading_and_keep_their_location() {
        let s = vec![sec(Some(1), "", "Page one text."), sec(Some(2), "", "Page two text."), sec(None, "A › B", "Under B.")];
        let c = chunk(&s, ChunkConfig::default());
        assert_eq!(c.len(), 3);
        assert_eq!((c[0].page, c[1].page, c[2].heading.as_str()), (Some(1), Some(2), "A › B"));
        assert_eq!(c.iter().map(|x| x.seq).collect::<Vec<_>>(), [0, 1, 2]);
    }

    #[test]
    fn long_text_splits_at_paragraphs_with_overlap_and_respects_the_maximum() {
        let para = "This is a sentence about budgets and travel plans. ".repeat(12);
        let text = vec![para.trim(); 6].join("\n\n");
        let cfg = ChunkConfig { target: 700, max: 900, overlap: 100 };
        let c = chunk(&[sec(Some(3), "", &text)], cfg);
        assert!(c.len() >= 4, "{}", c.len());
        assert!(c.iter().all(|x| x.content.chars().count() <= cfg.max), "{:?}", c.iter().map(|x| x.content.len()).collect::<Vec<_>>());
        assert_eq!(c[0].overlap, 0);
        assert!(c[1].overlap > 0, "later passages repeat a little of the previous one");
        // Without the overlap, the passages give back every word of the section, in order.
        let rebuilt: String = c.iter().map(|x| x.content.chars().skip(x.overlap).collect::<String>()).collect::<Vec<_>>().join(" ");
        let norm = |s: &str| s.split_whitespace().collect::<Vec<_>>().join(" ");
        assert_eq!(norm(&rebuilt), norm(&text));
    }

    #[test]
    fn a_huge_word_is_split_hard() {
        let c = chunk(&[sec(None, "", &"x".repeat(5000))], ChunkConfig::default());
        assert!(c.len() >= 3 && c.iter().all(|x| x.content.chars().count() <= 1800));
    }
}
