//! Runs commands inside a Forge project.
//!
//! No shell is involved: the command line is split into an argument vector and the program is
//! started directly, so `;`, `|`, `&&`, `$()` and globs have no special meaning. Commands the
//! model asks for go through `model_policy` (which refuses shells, inline-code interpreters,
//! deletion, privilege changes, network clients and publishing) and then through a per-call
//! approval. Every run has a wall-clock limit, a bounded output buffer, a scrubbed environment
//! (no variables that look like credentials) and redacted output.

use crate::error::{AtlasError, Result};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{Duration, Instant};
use tokio::io::AsyncReadExt;
use tokio_util::sync::CancellationToken;

pub const MAX_ARGS: usize = 64;

/// Split a command line into arguments. Supports '...' (literal) and "..." (with \" and \\
/// escapes). A backslash elsewhere is literal, so Windows paths work unquoted.
pub fn parse_command(line: &str) -> Result<Vec<String>> {
    if line.contains('\0') || line.len() > 4000 {
        return Err(AtlasError::Validation("invalid command".into()));
    }
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut in_word = false;
    let mut chars = line.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\'' => {
                in_word = true;
                loop {
                    match chars.next() {
                        Some('\'') => break,
                        Some(x) => cur.push(x),
                        None => return Err(AtlasError::Validation("unclosed ' quote".into())),
                    }
                }
            }
            '"' => {
                in_word = true;
                loop {
                    match chars.next() {
                        Some('"') => break,
                        Some('\\') if matches!(chars.peek(), Some('"') | Some('\\')) => cur.push(chars.next().unwrap_or_default()),
                        Some(x) => cur.push(x),
                        None => return Err(AtlasError::Validation("unclosed \" quote".into())),
                    }
                }
            }
            c if c.is_whitespace() => {
                if in_word {
                    out.push(std::mem::take(&mut cur));
                    in_word = false;
                }
            }
            c => {
                in_word = true;
                cur.push(c);
            }
        }
    }
    if in_word {
        out.push(cur);
    }
    if out.is_empty() {
        return Err(AtlasError::Validation("the command is empty".into()));
    }
    if out.len() > MAX_ARGS {
        return Err(AtlasError::Validation(format!("too many arguments (max {MAX_ARGS})")));
    }
    Ok(out)
}

/// Render an argv for display (quotes arguments that need it).
pub fn display_command(argv: &[String]) -> String {
    argv.iter()
        .map(|a| if a.is_empty() || a.chars().any(|c| c.is_whitespace() || c == '"' || c == '\'') { format!("\"{}\"", a.replace('\\', "\\\\").replace('"', "\\\"")) } else { a.clone() })
        .collect::<Vec<_>>()
        .join(" ")
}

fn program_name(argv0: &str) -> String {
    let base = argv0.rsplit(['/', '\\']).next().unwrap_or(argv0).to_ascii_lowercase();
    for ext in [".exe", ".cmd", ".bat", ".com", ".ps1"] {
        if let Some(b) = base.strip_suffix(ext) {
            return b.to_string();
        }
    }
    base
}

/// Extra rules for commands the *model* proposes. The owner's own terminal commands are not
/// restricted (it is their computer), but they still run without a shell.
pub fn model_policy(argv: &[String]) -> std::result::Result<(), String> {
    let prog = program_name(&argv[0]);
    let args: Vec<String> = argv[1..].iter().map(|a| a.to_ascii_lowercase()).collect();
    let has = |a: &str| args.iter().any(|x| x == a);
    let sub = args.first().map(String::as_str).unwrap_or("");
    const SHELLS: &[&str] = &["sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "cmd", "powershell", "pwsh", "wsl", "env", "xargs", "nohup", "start"];
    const DENIED: &[&str] = &[
        "rm", "rmdir", "del", "erase", "rd", "shred", "format", "mkfs", "diskpart", "dd", "shutdown", "reboot", "halt", "sudo", "su",
        "doas", "runas", "chmod", "chown", "icacls", "takeown", "reg", "setx", "curl", "wget", "ssh", "scp", "sftp", "ftp", "nc", "ncat",
        "netcat", "telnet", "rsync", "gh", "kill", "pkill", "killall", "taskkill", "crontab", "schtasks", "launchctl", "systemctl",
    ];
    if SHELLS.contains(&prog.as_str()) {
        return Err(format!("'{prog}' would run arbitrary shell code; ask the owner to run it in the Forge terminal instead"));
    }
    if DENIED.contains(&prog.as_str()) {
        return Err(format!("'{prog}' can delete data, change privileges or reach the network, so Atlas does not run it for the model"));
    }
    let inline_code = match prog.as_str() {
        p if p.starts_with("python") => has("-c"),
        "node" | "deno" | "bun" => has("-e") || has("--eval") || has("-p") || has("--print") || sub == "eval",
        "perl" | "ruby" => has("-e"),
        "php" => has("-r"),
        _ => false,
    };
    if inline_code {
        return Err(format!("'{prog}' with inline code is not allowed; put the code in a file in the project and run that"));
    }
    let denied_sub = match prog.as_str() {
        "git" => {
            matches!(sub, "push" | "clean" | "filter-branch" | "filter-repo" | "config" | "remote" | "credential" | "gc" | "prune" | "update-ref" | "reflog")
                || (sub == "reset" && has("--hard"))
                || (sub == "checkout" && args.iter().any(|a| a == "--" || a == "."))
                || (sub == "branch" && (has("-d") || has("-D") || has("--delete")))
                || (sub == "stash" && args.get(1).is_some_and(|a| a == "drop" || a == "clear"))
        }
        "npm" | "pnpm" | "yarn" | "bun" => matches!(sub, "publish" | "login" | "adduser" | "logout" | "token" | "owner" | "unpublish" | "deprecate" | "exec" | "dlx" | "x"),
        "npx" | "pnpx" | "bunx" => true,
        "cargo" => matches!(sub, "publish" | "login" | "logout" | "owner" | "yank" | "install" | "uninstall"),
        "twine" => true,
        "pip" | "pip3" | "uv" | "poetry" => matches!(sub, "upload" | "publish"),
        "docker" | "podman" => matches!(sub, "push" | "login" | "run" | "exec" | "rm" | "rmi" | "system"),
        _ => false,
    };
    if denied_sub {
        return Err(format!("'{} {sub}' publishes, deletes or reaches outside the project, so Atlas does not run it for the model", prog));
    }
    Ok(())
}

/// Environment variable names that look like credentials are not passed to child processes.
pub fn is_sensitive_env(name: &str) -> bool {
    let n = name.to_ascii_uppercase();
    ["API_KEY", "APIKEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "PRIVATE_KEY", "ACCESS_KEY", "AUTH"].iter().any(|p| n.contains(p))
}

/// Find the program on PATH (honouring PATHEXT on Windows) so `npm` resolves to `npm.cmd`.
pub fn resolve_program(argv0: &str, cwd: &Path) -> Result<PathBuf> {
    let p = Path::new(argv0);
    if p.components().count() > 1 {
        let full = if p.is_absolute() { p.to_path_buf() } else { cwd.join(p) };
        return if full.is_file() { Ok(full) } else { Err(AtlasError::NotFound(format!("'{argv0}' was not found"))) };
    }
    let exts: Vec<String> = if cfg!(windows) {
        let pe = std::env::var("PATHEXT").unwrap_or_else(|_| ".COM;.EXE;.BAT;.CMD".into());
        let mut v: Vec<String> = pe.split(';').filter(|e| !e.is_empty()).map(|e| e.to_ascii_lowercase()).collect();
        v.insert(0, String::new());
        v
    } else {
        vec![String::new()]
    };
    let path = std::env::var_os("PATH").unwrap_or_default();
    for dir in std::env::split_paths(&path) {
        for e in &exts {
            let cand = dir.join(format!("{argv0}{e}"));
            if cand.is_file() {
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    if cand.metadata().map(|m| m.permissions().mode() & 0o111 == 0).unwrap_or(true) {
                        continue;
                    }
                }
                return Ok(cand);
            }
        }
    }
    Err(AtlasError::NotFound(format!("'{argv0}' is not installed or not on PATH")))
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct TestSummary {
    pub framework: String,
    pub passed: u64,
    pub failed: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct RunOutput {
    pub argv: Vec<String>,
    /// "succeeded" | "failed" | "timed_out" | "cancelled"
    pub status: String,
    pub exit_code: Option<i32>,
    pub duration_ms: u64,
    pub output: String,
    pub truncated: bool,
    pub tests: Option<TestSummary>,
}

/// Keep the beginning and (mostly) the end of long output; errors usually appear last.
fn bound(mut s: String, max: usize) -> (String, bool) {
    if s.len() <= max {
        return (s, false);
    }
    let head = max * 2 / 5;
    let tail = max - head;
    let mut h = head;
    while !s.is_char_boundary(h) {
        h -= 1;
    }
    let mut t = s.len() - tail;
    while !s.is_char_boundary(t) {
        t += 1;
    }
    let dropped = t - h;
    let end = s.split_off(t);
    s.truncate(h);
    (format!("{s}\n… [{dropped} bytes of output omitted] …\n{end}"), true)
}

fn num_before(text: &str, word: &str) -> Option<u64> {
    let idx = text.rfind(word)?;
    let before = text[..idx].trim_end();
    let digits: String = before.chars().rev().take_while(|c| c.is_ascii_digit()).collect::<Vec<_>>().into_iter().rev().collect();
    digits.parse().ok()
}

/// Best-effort summary for common test runners. None when the output is not recognised.
pub fn parse_tests(output: &str) -> Option<TestSummary> {
    let mk = |f: &str, p: u64, x: u64| Some(TestSummary { framework: f.into(), passed: p, failed: x });
    // cargo: "test result: ok. 50 passed; 0 failed;" (one line per test binary; sum them)
    let cargo: Vec<&str> = output.lines().filter(|l| l.contains("test result:")).collect();
    if !cargo.is_empty() {
        let (mut p, mut f) = (0, 0);
        for l in cargo {
            p += num_before(l, " passed").unwrap_or(0);
            f += num_before(l, " failed").unwrap_or(0);
        }
        return mk("cargo", p, f);
    }
    // vitest: " Tests  15 passed (15)" / " Tests  1 failed | 14 passed (15)"
    if let Some(l) = output.lines().rev().find(|l| l.trim_start().starts_with("Tests ") && l.contains('(')) {
        return mk("vitest", num_before(l, " passed").unwrap_or(0), num_before(l, " failed").unwrap_or(0));
    }
    // jest: "Tests:       1 failed, 2 passed, 3 total"
    if let Some(l) = output.lines().rev().find(|l| l.trim_start().starts_with("Tests:")) {
        return mk("jest", num_before(l, " passed").unwrap_or(0), num_before(l, " failed").unwrap_or(0));
    }
    // pytest: "==== 3 failed, 351 passed, 36 skipped in 30.21s ====" or "351 passed in 2s"
    if let Some(l) = output.lines().rev().find(|l| (l.contains(" passed") || l.contains(" failed")) && l.contains(" in ") && l.trim_end().ends_with(['s', '=']))
    {
        return mk("pytest", num_before(l, " passed").unwrap_or(0), num_before(l, " failed").unwrap_or(0));
    }
    // go test: lines starting "ok  " / "FAIL\t"
    let go_ok = output.lines().filter(|l| l.starts_with("ok  \t") || l.starts_with("ok \t")).count() as u64;
    let go_fail = output.lines().filter(|l| l.starts_with("FAIL\t")).count() as u64;
    if go_ok + go_fail > 0 {
        return mk("go (packages)", go_ok, go_fail);
    }
    None
}

#[cfg(unix)]
fn kill_tree(pid: u32) {
    // The child leads its own process group; signal the whole group.
    let _ = std::process::Command::new("kill").args(["-KILL", &format!("-{pid}")]).stdout(Stdio::null()).stderr(Stdio::null()).status();
}

#[cfg(windows)]
fn kill_tree(pid: u32) {
    use std::os::windows::process::CommandExt;
    let _ = std::process::Command::new("taskkill")
        .args(["/T", "/F", "/PID", &pid.to_string()])
        .creation_flags(0x0800_0000)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

pub struct RunSpec<'a> {
    pub argv: &'a [String],
    pub cwd: &'a Path,
    pub timeout: Duration,
    pub max_output: usize,
    pub extra_env: &'a [(&'a str, &'a str)],
}

pub async fn run(spec: RunSpec<'_>, cancel: &CancellationToken) -> Result<RunOutput> {
    let program = resolve_program(&spec.argv[0], spec.cwd)?;
    let mut cmd = tokio::process::Command::new(&program);
    cmd.args(&spec.argv[1..]).current_dir(spec.cwd).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped()).kill_on_drop(true);
    for (k, _) in std::env::vars_os() {
        if is_sensitive_env(&k.to_string_lossy()) {
            cmd.env_remove(&k);
        }
    }
    cmd.env("NO_COLOR", "1").env("CLICOLOR", "0").env("GIT_TERMINAL_PROMPT", "0").env("CI", "1");
    for (k, v) in spec.extra_env {
        cmd.env(k, v);
    }
    #[cfg(unix)]
    cmd.process_group(0);
    #[cfg(windows)]
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    let started = Instant::now();
    let mut child = cmd.spawn().map_err(|e| AtlasError::Io(format!("could not start '{}': {e}", spec.argv[0])))?;
    let pid = child.id();
    let mut out = child.stdout.take().ok_or_else(|| AtlasError::Internal("stdout".into()))?;
    let mut err = child.stderr.take().ok_or_else(|| AtlasError::Internal("stderr".into()))?;
    let cap = spec.max_output * 4;
    let read_all = async move {
        let (mut a, mut b) = (Vec::new(), Vec::new());
        let (mut ba, mut bb) = ([0u8; 8192], [0u8; 8192]);
        let (mut da, mut db) = (false, false);
        while !(da && db) {
            tokio::select! {
                r = out.read(&mut ba), if !da => match r { Ok(0) | Err(_) => da = true, Ok(n) => if a.len() < cap { a.extend_from_slice(&ba[..n]) } },
                r = err.read(&mut bb), if !db => match r { Ok(0) | Err(_) => db = true, Ok(n) => if b.len() < cap { b.extend_from_slice(&bb[..n]) } },
            }
        }
        (a, b)
    };
    let (status, (o, e)) = tokio::select! {
        r = async { let io = read_all.await; (child.wait().await, io) } => (Some(r.0), r.1),
        _ = tokio::time::sleep(spec.timeout) => { if let Some(p) = pid { kill_tree(p); } (None, (vec![], b"".to_vec())) },
        _ = cancel.cancelled() => { if let Some(p) = pid { kill_tree(p); } return Ok(RunOutput { argv: spec.argv.to_vec(), status: "cancelled".into(), exit_code: None, duration_ms: started.elapsed().as_millis() as u64, output: String::new(), truncated: false, tests: None }) },
    };
    let duration_ms = started.elapsed().as_millis() as u64;
    let mut text = String::from_utf8_lossy(&o).to_string();
    if !e.is_empty() {
        if !text.is_empty() && !text.ends_with('\n') {
            text.push('\n');
        }
        text.push_str(&String::from_utf8_lossy(&e));
    }
    let text = crate::redact::redact(&text);
    let tests = parse_tests(&text);
    let (output, truncated) = bound(text, spec.max_output);
    let (status, exit_code) = match status {
        None => ("timed_out".to_string(), None),
        Some(Ok(s)) => (if s.success() { "succeeded" } else { "failed" }.to_string(), s.code()),
        Some(Err(e)) => return Err(AtlasError::Io(e.to_string())),
    };
    Ok(RunOutput { argv: spec.argv.to_vec(), status, exit_code, duration_ms, output, truncated, tests })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(s: &[&str]) -> Vec<String> {
        s.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn parses_without_shell_semantics() {
        assert_eq!(parse_command("cargo test -p atlas-core").unwrap(), v(&["cargo", "test", "-p", "atlas-core"]));
        assert_eq!(parse_command(r#"pytest -k "not slow" 'a b'"#).unwrap(), v(&["pytest", "-k", "not slow", "a b"]));
        assert_eq!(parse_command(r"python C:\tools\x.py").unwrap(), v(&["python", r"C:\tools\x.py"]));
        // Metacharacters are plain argument text.
        assert_eq!(parse_command("echo a; rm -rf / && x | y").unwrap(), v(&["echo", "a;", "rm", "-rf", "/", "&&", "x", "|", "y"]));
        assert!(parse_command("  ").is_err());
        assert!(parse_command("echo 'open").is_err());
        assert_eq!(display_command(&v(&["pytest", "-k", "not slow"])), r#"pytest -k "not slow""#);
    }

    #[test]
    fn model_policy_blocks_shells_deletion_network_and_publishing() {
        for bad in [
            "bash -c ls", "cmd /c dir", "powershell -Command x", "rm -rf build", "python -c print(1)", "python3 -c x", "node -e x",
            "curl https://x", "git push", "git reset --hard HEAD~1", "git clean -fdx", "npm publish", "cargo publish", "npx something",
            "sudo make", "C:\\Windows\\System32\\cmd.exe /c x", "/bin/sh -c x", "docker run x", "git config core.hooksPath x",
        ] {
            assert!(model_policy(&parse_command(bad).unwrap()).is_err(), "{bad} must be refused");
        }
        for ok in ["cargo test", "pytest -q", "npm test", "pnpm run build", "git status", "git diff", "python -m pytest", "node scripts/check.js", "go test ./..."] {
            assert!(model_policy(&parse_command(ok).unwrap()).is_ok(), "{ok} must be allowed");
        }
    }

    #[test]
    fn sensitive_env_names() {
        for n in ["OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "DB_PASSWORD", "anthropic_api_key"] {
            assert!(is_sensitive_env(n), "{n}");
        }
        for n in ["PATH", "HOME", "CARGO_HOME", "LANG"] {
            assert!(!is_sensitive_env(n), "{n}");
        }
    }

    #[test]
    fn test_summaries() {
        let cargo = "test result: ok. 50 passed; 0 failed; 1 ignored\ntest result: FAILED. 3 passed; 2 failed; 0 ignored";
        assert_eq!(parse_tests(cargo), Some(TestSummary { framework: "cargo".into(), passed: 53, failed: 2 }));
        assert_eq!(parse_tests(" Test Files  5 passed (5)\n      Tests  1 failed | 14 passed (15)").unwrap(), TestSummary { framework: "vitest".into(), passed: 14, failed: 1 });
        assert_eq!(parse_tests("===== 2 failed, 351 passed, 36 skipped in 30.21s =====").unwrap().passed, 351);
        assert_eq!(parse_tests("Tests:       1 failed, 2 passed, 3 total").unwrap().failed, 1);
        assert_eq!(parse_tests("hello"), None);
    }

    #[test]
    fn bounds_output_keeping_head_and_tail() {
        let s = format!("{}{}", "a".repeat(1000), "END");
        let (b, t) = bound(s, 100);
        assert!(t && b.starts_with("aaaa") && b.ends_with("END") && b.contains("omitted"));
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn runs_times_out_and_scrubs_env() {
        let dir = tempfile::tempdir().unwrap();
        let c = CancellationToken::new();
        let argv = v(&["sh", "-c", "echo out; echo err 1>&2; echo \"k=${ATLAS_TEST_API_KEY:-none}\"; exit 3"]);
        // SAFETY: test-only; no other threads in this test read this variable.
        unsafe { std::env::set_var("ATLAS_TEST_API_KEY", "sk-should-not-leak") };
        let r = run(RunSpec { argv: &argv, cwd: dir.path(), timeout: Duration::from_secs(10), max_output: 10_000, extra_env: &[] }, &c).await.unwrap();
        assert_eq!((r.status.as_str(), r.exit_code), ("failed", Some(3)));
        assert!(r.output.contains("out") && r.output.contains("err") && r.output.contains("k=none"), "{}", r.output);
        let argv = v(&["sh", "-c", "sleep 30"]);
        let r = run(RunSpec { argv: &argv, cwd: dir.path(), timeout: Duration::from_millis(300), max_output: 1000, extra_env: &[] }, &c).await.unwrap();
        assert_eq!(r.status, "timed_out");
        assert!(r.duration_ms < 5000);
        assert!(run(RunSpec { argv: &v(&["definitely-not-a-program-xyz"]), cwd: dir.path(), timeout: Duration::from_secs(1), max_output: 10, extra_env: &[] }, &c).await.is_err());
    }
}
