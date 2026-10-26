"""
gui_markdown.py — rendering + speech helpers for the Prometheus HUD.

Two jobs, both pure Python (no Qt import, so both are unit-testable headless):

1. render_markdown(): turns an LLM's markdown into the small HTML subset that
   Qt's rich-text widgets understand — headers, lists, tables, blockquotes,
   inline code/bold/italic/links, and fenced code blocks with a copy link and
   lightweight syntax highlighting. Tolerant of *incomplete* markdown (an
   unterminated ``` fence, a dangling **) because it's re-run on every chunk
   while a response is still streaming in.

2. clean_for_speech() / SpeechFilter: what should actually be *spoken*.
   Reading "asterisk asterisk bold asterisk asterisk" or an entire 40-line
   code block aloud is the fastest way to make a voice assistant sound broken.
   These strip markdown, skip code blocks (announcing them once instead),
   turn URLs into "link", and drop emoji the TTS voice would spell out.

Everything the model wrote is HTML-escaped before any markup is added, so
model output can't inject tags into the console.
"""

import html
import re
from typing import Dict, List, Optional

COPY_PREFIX = "copy:"

DEFAULT_THEME: Dict[str, str] = {
    "text": "#EAEAF2",
    "dim": "#7C7C92",
    "amber": "#FFB300",
    "cyan": "#00E5FF",
    "code_bg": "#05050a",
    "code_head": "#10101a",
    "inline_bg": "#14141f",
    "border": "#2a2a3a",
    # syntax colours
    "kw": "#C792EA",
    "str": "#C3E88D",
    "com": "#5C6370",
    "num": "#F78C6C",
    "fn": "#82AAFF",
    "deco": "#FFCB6B",
    "builtin": "#89DDFF",
}


def esc(s: str) -> str:
    return html.escape(s, quote=False)


# ------------------------------------------------------------------------------
# Syntax highlighting
# ------------------------------------------------------------------------------
_PY_KEYWORDS = (
    "and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|"
    "global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield|"
    "None|True|False|self|cls"
)
_PY_BUILTINS = (
    "print|len|range|int|str|float|list|dict|set|tuple|open|type|isinstance|enumerate|zip|map|"
    "filter|sum|min|max|abs|sorted|reversed|any|all|super|object|bool|bytes|Exception|ValueError|"
    "TypeError|KeyError|RuntimeError"
)
_JS_KEYWORDS = (
    "const|let|var|function|return|if|else|for|while|do|switch|case|break|continue|class|extends|new|"
    "import|from|export|default|async|await|try|catch|finally|throw|this|null|undefined|true|false|"
    "typeof|instanceof|in|of|interface|type|enum|public|private|static"
)
_SH_KEYWORDS = (
    "if|then|else|elif|fi|for|while|do|done|case|esac|function|in|echo|cd|export|source|sudo|"
    "pip|python|python3|git|npm|ls|cat|grep|mkdir|rm|cp|mv|curl"
)

_PATTERNS: Dict[str, "re.Pattern"] = {
    "python": re.compile(
        r'(?P<com>#[^\n]*)'
        r'|(?P<str>[rbfRBF]{0,2}(?:"""[\s\S]*?(?:"""|\Z)|\'\'\'[\s\S]*?(?:\'\'\'|\Z)))'
        r'|(?P<str2>[rbfRBF]{0,2}"(?:\\.|[^"\\\n])*"?|[rbfRBF]{0,2}\'(?:\\.|[^\'\\\n])*\'?)'
        r'|(?P<deco>@[A-Za-z_][\w.]*)'
        r'|(?P<defn>\b(?:def|class)\b\s+[A-Za-z_]\w*)'
        r'|(?P<kw>\b(?:' + _PY_KEYWORDS + r')\b)'
        r'|(?P<builtin>\b(?:' + _PY_BUILTINS + r')\b)'
        r'|(?P<num>\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b)'
    ),
    "js": re.compile(
        r'(?P<com>//[^\n]*|/\*[\s\S]*?(?:\*/|\Z))'
        r'|(?P<str>`(?:\\.|[^`\\])*`?|"(?:\\.|[^"\\\n])*"?|\'(?:\\.|[^\'\\\n])*\'?)'
        r'|(?P<defn>\bfunction\b\s+[A-Za-z_$][\w$]*|\bclass\b\s+[A-Za-z_$][\w$]*)'
        r'|(?P<kw>\b(?:' + _JS_KEYWORDS + r')\b)'
        r'|(?P<num>\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b)'
    ),
    "json": re.compile(
        r'(?P<key>"(?:\\.|[^"\\\n])*"(?=\s*:))'
        r'|(?P<str>"(?:\\.|[^"\\\n])*"?)'
        r'|(?P<kw>\b(?:true|false|null)\b)'
        r'|(?P<num>-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)'
    ),
    "bash": re.compile(
        r'(?P<com>(?:^|(?<=\s))#[^\n]*)'
        r'|(?P<str>"(?:\\.|[^"\\])*"?|\'[^\']*\'?)'
        r'|(?P<deco>\$\{[^}\n]*\}|\$\w+)'
        r'|(?P<kw>\b(?:' + _SH_KEYWORDS + r')\b)'
        r'|(?P<num>\b\d+\b)'
    ),
}

_LANG_ALIASES = {
    "py": "python", "python": "python", "python3": "python", "py3": "python",
    "js": "js", "javascript": "js", "ts": "js", "typescript": "js", "jsx": "js", "tsx": "js",
    "json": "json", "jsonc": "json",
    "sh": "bash", "bash": "bash", "shell": "bash", "zsh": "bash", "console": "bash", "cmd": "bash",
}


def highlight_code(code: str, lang: str, theme: Dict[str, str]) -> str:
    """Return HTML (escaped) for `code`, coloured when `lang` is recognised."""
    family = _LANG_ALIASES.get((lang or "").strip().lower())
    pattern = _PATTERNS.get(family) if family else None
    if pattern is None:
        return esc(code)

    color_for = {
        "com": theme["com"], "str": theme["str"], "str2": theme["str"], "deco": theme["deco"],
        "kw": theme["kw"], "builtin": theme["builtin"], "num": theme["num"], "key": theme["fn"],
    }
    out: List[str] = []
    pos = 0
    for m in pattern.finditer(code):
        if m.start() > pos:
            out.append(esc(code[pos:m.start()]))
        kind = m.lastgroup
        text = m.group(0)
        if kind == "defn":
            # colour the def/class keyword and the name differently
            parts = re.match(r"(\w+)(\s+)(.*)", text, re.S)
            if parts:
                out.append(f'<span style="color:{theme["kw"]}">{esc(parts.group(1))}</span>'
                           f'{esc(parts.group(2))}'
                           f'<span style="color:{theme["fn"]}">{esc(parts.group(3))}</span>')
            else:
                out.append(esc(text))
        else:
            out.append(f'<span style="color:{color_for.get(kind, theme["text"])}">{esc(text)}</span>')
        pos = m.end()
    if pos < len(code):
        out.append(esc(code[pos:]))
    return "".join(out)


# ------------------------------------------------------------------------------
# Inline markdown
# ------------------------------------------------------------------------------
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITAL_STAR_RE = re.compile(r"(?<![\*\w])\*(?![\s\*])(.+?)(?<![\s\*])\*(?![\*\w])")
_ITAL_UND_RE = re.compile(r"(?<![\w_])_(?![\s_])(.+?)(?<![\s_])_(?![\w_])")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")


def render_inline(text: str, theme: Dict[str, str]) -> str:
    pieces: List[str] = []
    pos = 0
    for m in _CODE_SPAN_RE.finditer(text):
        pieces.append(_render_inline_plain(text[pos:m.start()], theme))
        pieces.append(
            f'<span style="font-family:Consolas,monospace; background-color:{theme["inline_bg"]}; '
            f'color:{theme["amber"]};">&nbsp;{esc(m.group(1))}&nbsp;</span>'
        )
        pos = m.end()
    pieces.append(_render_inline_plain(text[pos:], theme))
    return "".join(pieces)


def _emphasis(s: str) -> str:
    s = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", s)
    s = _ITAL_STAR_RE.sub(lambda m: f"<i>{m.group(1)}</i>", s)
    s = _ITAL_UND_RE.sub(lambda m: f"<i>{m.group(1)}</i>", s)
    s = _STRIKE_RE.sub(lambda m: f"<s>{m.group(1)}</s>", s)
    return s


def _render_inline_plain(text: str, theme: Dict[str, str]) -> str:
    # NUL delimits the link placeholders below, so strip any the model emitted.
    s = esc(text).replace("\x00", "")
    links: List[str] = []

    def stash_link(m):
        href = m.group(2).replace(chr(34), "%22")
        links.append(f'<a href="{href}" style="color:{theme["cyan"]};">{_emphasis(m.group(1))}</a>')
        return f"\x00{len(links) - 1}\x00"

    # Links are lifted out BEFORE emphasis runs: otherwise an underscore or
    # asterisk inside a URL (https://x.com/_a_/) becomes <i>/<b> tags in the
    # middle of the href attribute and breaks the link.
    s = _LINK_RE.sub(stash_link, s)
    s = _emphasis(s)
    return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], s)


# ------------------------------------------------------------------------------
# Block markdown
# ------------------------------------------------------------------------------
_FENCE_OPEN_RE = re.compile(r"^\s*```\s*([\w+#.-]*)[^`]*$")
_FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")
_HEADER_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_block_start(line: str, nxt: Optional[str]) -> bool:
    return bool(
        _FENCE_OPEN_RE.match(line) or _HEADER_RE.match(line) or _HR_RE.match(line)
        or _LIST_RE.match(line) or _QUOTE_RE.match(line)
        or (line.strip().startswith("|") and nxt is not None and _TABLE_SEP_RE.match(nxt))
    )


def _render_code_block(code: str, lang: str, block_id: str, theme: Dict[str, str]) -> str:
    label = (lang or "code").upper()
    body = highlight_code(code, lang, theme)
    return (
        f'<table width="100%" cellspacing="0" cellpadding="6" style="margin:6px 0 6px 0;">'
        f'<tr><td bgcolor="{theme["code_head"]}">'
        f'<span style="color:{theme["dim"]}; font-size:8pt; font-weight:bold;">{esc(label)}</span>'
        f'&nbsp;&nbsp;<a href="{COPY_PREFIX}{block_id}" style="color:{theme["cyan"]}; font-size:8pt;">COPY</a>'
        f'</td></tr>'
        f'<tr><td bgcolor="{theme["code_bg"]}">'
        f'<pre style="margin:0; white-space:pre-wrap; font-family:Consolas,monospace; font-size:9pt; '
        f'color:{theme["text"]};">{body}</pre>'
        f'</td></tr></table>'
    )


def render_markdown(text: str, theme: Optional[Dict[str, str]] = None,
                    code_registry: Optional[Dict[str, str]] = None, id_prefix: str = "blk") -> str:
    """Render `text` to Qt-safe HTML. Raw code for every fenced block is stored
    in `code_registry[block_id]` so the console's COPY links can retrieve it."""
    theme = theme or DEFAULT_THEME
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: List[str] = []
    n = len(lines)
    i = 0
    block_no = 0
    para: List[str] = []

    def flush_para():
        if para:
            body = "<br/>".join(render_inline(p, theme) for p in para)
            out.append(f'<p style="margin:3px 0; color:{theme["text"]};">{body}</p>')
            para.clear()

    while i < n:
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < n else None

        m = _FENCE_OPEN_RE.match(line)
        if m:
            flush_para()
            lang = m.group(1)
            i += 1
            code_lines: List[str] = []
            while i < n and not _FENCE_CLOSE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence (or run off the end if unterminated mid-stream)
            code = "\n".join(code_lines)
            block_id = f"{id_prefix}-{block_no}"
            block_no += 1
            if code_registry is not None:
                code_registry[block_id] = code
            out.append(_render_code_block(code, lang, block_id, theme))
            continue

        if not line.strip():
            flush_para()
            i += 1
            continue

        m = _HEADER_RE.match(line)
        if m:
            flush_para()
            level = len(m.group(1))
            size = {1: "13pt", 2: "12pt", 3: "11pt", 4: "10pt"}[level]
            out.append(
                f'<p style="margin:8px 0 2px 0; font-size:{size}; font-weight:bold; color:{theme["amber"]};">'
                f'{render_inline(m.group(2), theme)}</p>'
            )
            i += 1
            continue

        if _HR_RE.match(line):
            flush_para()
            out.append(f'<p style="margin:4px 0; color:{theme["border"]};">{"─" * 36}</p>')
            i += 1
            continue

        if line.strip().startswith("|") and nxt is not None and _TABLE_SEP_RE.match(nxt):
            flush_para()
            header = _split_row(line)
            i += 2
            rows: List[List[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            th = "".join(
                f'<th align="left" bgcolor="{theme["code_head"]}" style="color:{theme["amber"]};">'
                f'{render_inline(c, theme)}</th>' for c in header)
            trs = "".join(
                "<tr>" + "".join(f'<td style="color:{theme["text"]};">{render_inline(c, theme)}</td>' for c in r) + "</tr>"
                for r in rows)
            out.append(
                f'<table border="1" cellspacing="0" cellpadding="5" style="margin:5px 0; border-color:{theme["border"]};">'
                f'<tr>{th}</tr>{trs}</table>')
            continue

        m = _QUOTE_RE.match(line)
        if m:
            flush_para()
            quote_lines: List[str] = []
            while i < n:
                qm = _QUOTE_RE.match(lines[i])
                if not qm:
                    break
                quote_lines.append(qm.group(1))
                i += 1
            body = "<br/>".join(render_inline(q, theme) for q in quote_lines)
            out.append(f'<p style="margin:3px 0 3px 8px; color:{theme["dim"]};">'
                       f'<span style="color:{theme["amber"]};">&#9612;</span>&nbsp;{body}</p>')
            continue

        m = _LIST_RE.match(line)
        if m:
            flush_para()
            indent = min(3, len(m.group(1).replace("\t", "  ")) // 2)
            marker = m.group(2)
            bullet = "&bull;" if marker in "-*+" else esc(marker)
            out.append(
                f'<p style="margin:1px 0 1px {12 + 18 * indent}px; color:{theme["text"]};">'
                f'<span style="color:{theme["amber"]};">{bullet}</span>&nbsp;{render_inline(m.group(3), theme)}</p>')
            i += 1
            continue

        para.append(line)
        i += 1
        # a paragraph continues until a blank line or another block starts
        while i < n and lines[i].strip() and not _is_block_start(lines[i], lines[i + 1] if i + 1 < n else None):
            para.append(lines[i])
            i += 1

    flush_para()
    return "".join(out)


# ------------------------------------------------------------------------------
# Speech sanitising
# ------------------------------------------------------------------------------
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u2460-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")
_URL_RE = re.compile(r"https?://\S+")
_SPOKEN_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((?:https?://[^\s)]+)\)")

CODE_ANNOUNCEMENT = "I've put the code in the console."


def _tidy_speech(text: str) -> str:
    text = _EMOJI_RE.sub("", text)
    text = _SPOKEN_LINK_RE.sub(r"\1", text)
    text = _URL_RE.sub("link", text)
    text = _CODE_SPAN_RE.sub(r"\1", text)
    lines_out: List[str] = []
    for raw in text.split("\n"):
        ln = raw.strip()
        if not ln or _HR_RE.match(ln) or ln.startswith("|") or _TABLE_SEP_RE.match(ln):
            continue
        ln = re.sub(r"^#{1,6}\s+", "", ln)
        ln = re.sub(r"^>\s?", "", ln)
        ln = re.sub(r"^([-*+]|\d+[.)])\s+", "", ln)
        ln = re.sub(r"(\*\*|__|~~)", "", ln)
        ln = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", ln)
        ln = re.sub(r"(?<![\w])_(?=\S)|(?<=\S)_(?![\w])", "", ln)
        ln = ln.replace("`", "").strip()
        if not ln:
            continue
        if ln[-1] not in ".!?:;,":
            ln += "."
        lines_out.append(ln)
    return re.sub(r"\s+", " ", " ".join(lines_out)).strip()


def clean_for_speech(text: str) -> str:
    """Whole-message version: drops fenced code (announcing it once)."""
    f = SpeechFilter()
    return f.feed(text)


class SpeechFilter:
    """Stateful version for streamed chunks: a ``` fence can open in one chunk
    and close several chunks later, so "am I inside code?" has to persist
    across calls. Create one per response."""

    def __init__(self) -> None:
        self.in_code = False
        self.announced = False

    def feed(self, chunk: str) -> str:
        parts = chunk.split("```")
        spoken: List[str] = []
        for idx, part in enumerate(parts):
            if idx > 0:
                self.in_code = not self.in_code
                if self.in_code and not self.announced:
                    self.announced = True
                    spoken.append(CODE_ANNOUNCEMENT)
            if not self.in_code:
                spoken.append(part)
        cleaned = _tidy_speech("\n".join(spoken))
        return cleaned
