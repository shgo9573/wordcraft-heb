//! i18n-he: dictation — Voice › Dictate (`tools.dictate`) on a local speech service, and Cancel
//! (`tools.dictateCancel`). This file is added whole by `i18n-he/tools/dictate_patch.py`, which
//! the daily sync can also run in reverse (`--remove`) and then build without it.
//!
//! WordCraft has no speech recogniser of its own: no model is bundled and nothing is sent to a
//! cloud. It talks to the small local services that Hebrew dictation already runs on, over
//! loopback, in the order they answer:
//!
//! * **Otzaria Voice** (`127.0.0.1:47811`, <https://github.com/yakov100/otzaria-voice>) — the
//!   service behind the Otzaria dictation plugin. It records from the microphone itself and streams
//!   newline-delimited JSON back (`/status`, `/dictate`, `/stop`, `/cancel`). Its Hebrew model
//!   carries the Otzaria library's word list, which is what makes Rabbinic Hebrew and Talmudic
//!   phrases come out right — Hebrew dictation by a general model writes them as nonsense.
//! * **KolScribe** (`127.0.0.1:47321`, the desktop app the Otzaria Word plugin talks to) — a
//!   write-ahead event log the editor polls (`/api/plugin/hello`, `/api/plugin/sync?after=&wait=`,
//!   `/api/plugin/command`). Speaking that protocol is what lets dictation started in the plugin's
//!   own window type into this one too, and the two can run side by side.
//!
//! The service is a separate program the user installs once. When neither answers, the command
//! says so with both download links instead of failing silently, which is the whole reason the
//! ribbon's Dictate button was dead in the first place (this fork's `docs/gaps.md` #28): there was
//! no engine behind the command.
//!
//! The work runs on a background thread that holds the connection; finished sentences come back
//! over a channel and [`tick`] types each one with `text.insert`, so undo, track changes, autosave
//! and the status bar all see ordinary typing at the caret.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::mpsc::{Receiver, TryRecvError, channel};
use std::time::Duration;

use serde_json::{Value, json};

use crate::WordApp;

/// Where Otzaria Voice listens (its default; loopback only).
pub const OTZARIA_VOICE: &str = "127.0.0.1:47811";
/// Where KolScribe listens.
pub const KOLSCRIBE: &str = "127.0.0.1:47321";

/// How much silence ends listening in Otzaria Voice.
const END_AFTER_SILENCE_MS: u32 = 1500;
/// How long it waits for speech before it gives up on a run with nothing said.
const NO_SPEECH_MS: u32 = 8_000;

/// Where the services come from: shown when neither answers.
pub const DOWNLOADS: [(&str, &str); 2] = [
    ("Otzaria Voice", "https://github.com/yakov100/otzaria-voice/releases/latest"),
    ("KolScribe", "https://github.com/shlomyeisenberg-lang/live-transcribe/releases/latest"),
];

/// What one dictation run reports to the UI thread.
#[derive(Clone, Debug, PartialEq)]
pub enum Event {
    /// The service is recording.
    Listening(&'static str),
    /// A finished sentence, to be typed at the caret.
    Text(String),
    /// The run ended: `None` when it stopped as asked, `Some(reason)` when it could not go on.
    Ended(Option<String>),
}

/// The dictation in flight, if any.
#[derive(Default)]
pub struct Dictation {
    events: Option<Receiver<Event>>,
    /// The service this run talks to (`""` when none answered).
    pub service: &'static str,
    /// Whether the service is recording.
    pub listening: bool,
    /// The last thing the run said, for a window that should not lose it.
    pub message: Option<String>,
    /// The user asked it to stop: the sentences already heard still arrive.
    pub stop_asked: bool,
}

impl Dictation {
    /// Whether a run is in flight.
    pub fn running(&self) -> bool {
        self.events.is_some()
    }
}

/// One HTTP/1.1 request to a loopback service, and the reader over its body. The bodies are
/// line-delimited JSON, so the reply is not read whole — `Connection: close` ends it.
fn request(
    addr: &str,
    method: &str,
    path: &str,
    headers: &[(&str, &str)],
    body: &str,
    read_timeout: Duration,
) -> Result<(u16, BufReader<TcpStream>), String> {
    let sock: SocketAddr = addr.parse().map_err(|_| format!("bad address {addr}"))?;
    let stream = TcpStream::connect_timeout(&sock, Duration::from_millis(700)).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(read_timeout)).map_err(|e| e.to_string())?;
    stream.set_write_timeout(Some(Duration::from_secs(5))).map_err(|e| e.to_string())?;
    let mut head = format!("{method} {path} HTTP/1.1\r\nHost: {addr}\r\nConnection: close\r\nAccept: application/json\r\n");
    for (k, v) in headers {
        head.push_str(&format!("{k}: {v}\r\n"));
    }
    if !body.is_empty() {
        head.push_str(&format!("Content-Type: application/json\r\nContent-Length: {}\r\n", body.len()));
    } else if method == "POST" {
        head.push_str("Content-Length: 0\r\n");
    }
    head.push_str("\r\n");
    let mut sender = stream.try_clone().map_err(|e| e.to_string())?;
    sender.write_all(head.as_bytes()).and_then(|()| sender.write_all(body.as_bytes())).and_then(|()| sender.flush()).map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(stream);
    let mut status_line = String::new();
    reader.read_line(&mut status_line).map_err(|e| e.to_string())?;
    let status: u16 = status_line.split_whitespace().nth(1).and_then(|s| s.parse().ok()).ok_or_else(|| format!("unexpected reply from {addr}"))?;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line).map_err(|e| e.to_string())? == 0 || line.trim().is_empty() {
            break;
        }
    }
    Ok((status, reader))
}

/// The whole body of a short reply, as JSON.
fn read_json(reader: &mut impl Read) -> Option<Value> {
    let mut text = String::new();
    reader.read_to_string(&mut text).ok()?;
    serde_json::from_str(text.trim()).ok()
}

/// Whether Otzaria Voice runs here and has a model to dictate with.
fn otzaria_ready() -> bool {
    let Ok((200, mut reader)) = request(OTZARIA_VOICE, "GET", "/status", &[("X-Otzaria-Voice", "1")], "", Duration::from_secs(2)) else {
        return false;
    };
    read_json(&mut reader).is_some_and(|v| v.get("runtime").and_then(Value::as_bool) == Some(true))
}

/// Whether KolScribe runs here.
fn kols_ready() -> bool {
    request(KOLSCRIBE, "GET", "/api/plugin/hello", &[("X-Hlt-Client", "wordcraft")], "", Duration::from_secs(2))
        .is_ok_and(|(status, _)| status == 200)
}

/// Which service a dictation would use, asking each in turn: `None` when neither runs.
pub fn available() -> Option<&'static str> {
    if otzaria_ready() {
        Some("otzaria")
    } else if kols_ready() {
        Some("kols")
    } else {
        None
    }
}

/// Starts a run in the background. `before` is the text just before the caret: both services take
/// the last words as context, which is what keeps a sentence's spelling and spacing right.
pub fn start(before: &str) -> (Receiver<Event>, &'static str, Option<String>) {
    let (tx, rx) = channel();
    let Some(service) = available() else {
        let _ = tx.send(Event::Ended(Some("no_service".into())));
        return (rx, "", Some("no_service".into()));
    };
    let context: Vec<String> = before.split_whitespace().rev().take(2).map(str::to_string).collect::<Vec<_>>().into_iter().rev().collect();
    let sender = tx.clone();
    // The thread ends when it is done or when the UI drops the receiver at its next send.
    std::thread::spawn(move || {
        let outcome = match service {
            "otzaria" => run_otzaria(&sender, &context),
            _ => run_kols(&sender),
        };
        let _ = sender.send(Event::Ended(outcome));
    });
    (rx, service, None)
}

/// Otzaria Voice: `POST /dictate` streams one JSON object per line — `ready`, `update` (a segment's
/// text, `final` once it will not change), `error`, `end` (with a reason).
fn run_otzaria(tx: &std::sync::mpsc::Sender<Event>, context: &[String]) -> Option<String> {
    let body = json!({ "context": context, "endAfterSilenceMs": END_AFTER_SILENCE_MS, "noSpeechMs": NO_SPEECH_MS }).to_string();
    let (status, reader) = match request(OTZARIA_VOICE, "POST", "/dictate", &[("X-Otzaria-Voice", "1")], &body, Duration::from_secs(130)) {
        Ok(r) => r,
        Err(e) => return Some(e),
    };
    if status != 200 {
        return Some(format!("HTTP {status}"));
    }
    let _ = tx.send(Event::Listening("otzaria"));
    // Each segment's newest text, and how many have been typed: a segment is corrected while it is
    // still being heard, and typed once, when it is final.
    let mut segments: Vec<String> = Vec::new();
    let mut typed = 0;
    for line in reader.lines() {
        let Ok(line) = line else { return Some("the service stopped answering".into()) };
        let Ok(event) = serde_json::from_str::<Value>(line.trim()) else { continue };
        match event.get("type").and_then(Value::as_str) {
            Some("update") => {
                let at = event.get("segment").and_then(Value::as_u64).unwrap_or(0) as usize;
                if segments.len() <= at {
                    segments.resize(at + 1, String::new());
                }
                segments[at] = event.get("text").and_then(Value::as_str).unwrap_or("").to_string();
                if event.get("final").and_then(Value::as_bool) == Some(true) {
                    while typed <= at {
                        let text = segments.get(typed).cloned().unwrap_or_default();
                        typed += 1;
                        if !text.trim().is_empty() && tx.send(Event::Text(text)).is_err() {
                            return None;
                        }
                    }
                }
            }
            Some("error") => return Some(event.get("message").and_then(Value::as_str).unwrap_or("the service reported an error").to_string()),
            Some("end") => {
                // A sentence still being heard is typed too: the recording is over either way.
                for text in segments.iter().skip(typed) {
                    if !text.trim().is_empty() && tx.send(Event::Text(text.clone())).is_err() {
                        return None;
                    }
                }
                return match event.get("reason").and_then(Value::as_str) {
                    None | Some("" | "stopped" | "silence" | "no_speech" | "cancelled") => None,
                    Some("time_limit") => Some("time_limit".into()),
                    Some(other) => Some(other.to_string()),
                };
            }
            _ => {}
        }
    }
    None
}

/// KolScribe: `/api/plugin/sync` long-polls the app's event log; a finished sentence is a `line`
/// event, and the app's `state` says whether it is still recording.
fn run_kols(tx: &std::sync::mpsc::Sender<Event>) -> Option<String> {
    let headers = [("X-Hlt-Client", "wordcraft")];
    match request(KOLSCRIBE, "GET", "/api/plugin/hello", &headers, "", Duration::from_secs(3)) {
        Ok((200, mut reader)) => {
            let ready = read_json(&mut reader).and_then(|h| h.get("state").and_then(|s| s.get("pageReady")).and_then(Value::as_bool));
            if ready == Some(false) {
                return Some("page_not_ready".into());
            }
        }
        Ok((status, _)) => return Some(format!("HTTP {status}")),
        Err(e) => return Some(e),
    }
    // Start recording in the app's own panel: the sync stream then carries what it hears. Its
    // plugin API takes `{"command": "<name>"}`, the same command names its own UI sends.
    match request(KOLSCRIBE, "POST", "/api/plugin/command", &headers, &json!({ "command": "live-start" }).to_string(), Duration::from_secs(5)) {
        Ok((200, _)) => {}
        Ok((status, _)) => return Some(format!("HTTP {status}")),
        Err(e) => return Some(e),
    }
    let _ = tx.send(Event::Listening("kols"));
    let mut seq = 0;
    loop {
        let path = format!("/api/plugin/sync?after={seq}&wait=20");
        let (status, reader) = match request(KOLSCRIBE, "GET", &path, &headers, "", Duration::from_secs(45)) {
            Ok(r) => r,
            Err(e) => return Some(e),
        };
        if status != 200 {
            return Some(format!("HTTP {status}"));
        }
        let mut heard = false;
        for line in reader.lines() {
            let Ok(line) = line else { return Some("the app stopped answering".into()) };
            let Ok(event) = serde_json::from_str::<Value>(line.trim()) else { continue };
            heard = true;
            if let Some(n) = event.get("seq").and_then(Value::as_u64) {
                seq = n;
            }
            match event.get("type").and_then(Value::as_str) {
                Some("line") => {
                    if let Some(text) = event.get("line").and_then(|l| l.get("text")).and_then(Value::as_str)
                        && !text.trim().is_empty()
                        && tx.send(Event::Text(text.to_string())).is_err()
                    {
                        return None;
                    }
                }
                // Frames the app drew before the run started are not typed again.
                Some("snapshot") => {}
                Some("state") if event.get("state").and_then(|s| s.get("recording")).and_then(Value::as_bool) == Some(false) => return None,
                _ => {}
            }
        }
        // A poll that answers nothing ends the run rather than spinning on it.
        if !heard {
            return None;
        }
    }
}

/// Ask the service to stop recording; what it already heard still arrives.
fn stop_service(service: &str) {
    let _ = match service {
        "otzaria" => request(OTZARIA_VOICE, "POST", "/stop", &[("X-Otzaria-Voice", "1")], "", Duration::from_secs(3)),
        "kols" => request(
            KOLSCRIBE,
            "POST",
            "/api/plugin/command",
            &[("X-Hlt-Client", "wordcraft")],
            &json!({ "command": "live-stop" }).to_string(),
            Duration::from_secs(3),
        ),
        _ => return,
    };
}

/// The words just before the caret, as context for the recogniser.
fn before_caret(app: &WordApp) -> String {
    let pos = app.session.sel.focus.clone();
    let Some(para) = app.session.doc.para_at(&pos) else { return String::new() };
    let end = pos.off.min(para.text.len());
    let start = end.saturating_sub(200);
    para.text.get(start..end).unwrap_or_default().to_string()
}

/// A run that could not start (or could not go on), in the interface's language.
pub fn explain(reason: &str) -> String {
    let t = crate::i18n::t;
    match reason {
        "no_service" => format!(
            "{} Otzaria Voice: {} KolScribe: {}",
            t("Dictation needs a speech service installed on this computer: neither answered. Install one, start it, and click Dictate again."),
            DOWNLOADS[0].1,
            DOWNLOADS[1].1
        ),
        "page_not_ready" => t("The dictation app is still starting. Try again in a moment.").to_string(),
        "time_limit" => t("Dictation reached the service's time limit. Click Dictate to carry on.").to_string(),
        other if other.starts_with("HTTP ") => crate::i18n::fmt(t("The speech service answered with an error ({error})."), &[("error", other)]),
        other => other.to_string(),
    }
}

impl WordApp {
    /// Voice › Dictate: start listening, or stop a run that is going.
    pub(crate) fn dictate(&mut self) -> Result<Value, String> {
        if self.dictation.running() {
            self.stop_dictating();
            return Ok(json!({ "listening": false }));
        }
        // The recogniser is a program on this computer; the browser build has none to reach.
        if cfg!(target_arch = "wasm32") {
            let msg = crate::i18n::t("Dictation needs the desktop app: it records through a speech service installed on this computer.").to_string();
            self.status(msg.clone());
            return Err(msg);
        }
        let before = before_caret(self);
        let (rx, service, failed) = start(&before);
        self.dictation.events = Some(rx);
        self.dictation.service = service;
        self.dictation.listening = false;
        self.dictation.stop_asked = false;
        self.dictation.message = None;
        if let Some(reason) = failed {
            self.dictation.events = None;
            let msg = explain(&reason);
            self.status(msg.clone());
            return Err(msg);
        }
        self.status(crate::i18n::t("Listening. Speak, and the words are typed where the caret is. Click Dictate again to stop."));
        Ok(json!({ "listening": true, "service": service }))
    }

    /// Stop recording; the sentences already heard are still typed.
    pub(crate) fn stop_dictating(&mut self) {
        if !self.dictation.service.is_empty() {
            stop_service(self.dictation.service);
        }
        self.dictation.stop_asked = true;
        self.status(crate::i18n::t("Stopping dictation…"));
    }
}

/// Type what the service heard. Called once a frame: the run's thread never touches the document.
pub(crate) fn tick(app: &mut WordApp) {
    loop {
        let event = match app.dictation.events.as_ref() {
            Some(rx) => match rx.try_recv() {
                Ok(e) => e,
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    app.dictation.events = None;
                    app.dictation.listening = false;
                    break;
                }
            },
            None => break,
        };
        match event {
            Event::Listening(service) => {
                app.dictation.listening = true;
                app.dictation.service = service;
                app.status(crate::i18n::t("Listening. Speak, and the words are typed where the caret is."));
            }
            Event::Text(mut text) => {
                if !text.ends_with(' ') && !text.ends_with('\n') {
                    text.push(' ');
                }
                // Typed as typing: undo, track changes and autosave all see an ordinary edit.
                if let Err(e) = app.run("text.insert", json!({ "text": text })) {
                    app.status(e);
                }
            }
            Event::Ended(reason) => {
                app.dictation.events = None;
                app.dictation.listening = false;
                match reason {
                    None => app.status(crate::i18n::t("Dictation stopped.")),
                    Some(reason) => {
                        let msg = explain(&reason);
                        app.status(msg.clone());
                        app.dictation.message = Some(msg);
                    }
                }
            }
        }
    }
}
