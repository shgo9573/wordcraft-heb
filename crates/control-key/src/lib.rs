//! The control channel's key file, one rule for the app (which writes it) and the MCP bridge
//! (which reads it): `<settings>/control-key.<instance>`. See `docs/control-protocol.md`, Keys.

use std::path::{Path, PathBuf};

/// A file next to the executable that makes its folder the profile folder: the portable build
/// ships one (`packaging/windows/package.ps1`), so a copy of the app carries its settings, user
/// dictionary, fonts and recovery copies on a stick or in a synced folder.
pub const PORTABLE_MARKER: &str = "portable.txt";

/// Where a portable copy keeps its profile: `<exe folder>/WordCraft-data`, beside the app rather
/// than in `%APPDATA%`. Deleting this folder resets the app without touching the executable.
pub const PORTABLE_DATA: &str = "WordCraft-data";

/// The app's settings folder (preferences, logs, key files): macOS
/// `~/Library/Application Support/WordCraft`, Windows `%APPDATA%\WordCraft`, otherwise
/// `$XDG_CONFIG_HOME/wordcraft` or `~/.config/wordcraft`.
/// `WORDCRAFT_PROFILE_DIR` overrides the entire folder for isolated runs, and a portable copy
/// keeps its own beside the executable ([`portable_dir`]).
pub fn settings_dir() -> Option<PathBuf> {
    if let Some(path) = std::env::var_os("WORDCRAFT_PROFILE_DIR").filter(|p| !p.is_empty()) {
        return Some(PathBuf::from(path));
    }
    if let Some(dir) = std::env::current_exe().ok().as_deref().and_then(portable_dir) {
        return Some(dir);
    }
    if cfg!(target_os = "macos") {
        std::env::var_os("HOME").map(|h| PathBuf::from(h).join("Library/Application Support/WordCraft"))
    } else if cfg!(windows) {
        std::env::var_os("APPDATA").map(|a| PathBuf::from(a).join("WordCraft"))
    } else {
        std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
            .map(|c| c.join("wordcraft"))
    }
}

/// The profile folder of a portable copy: `<exe folder>/WordCraft-data` when `<exe folder>` holds
/// [`PORTABLE_MARKER`], `None` otherwise. `exe` is the path of the running executable (a parameter
/// so the rule is testable).
///
/// A folder that cannot be written to — the zip unpacked into `Program Files`, a read-only share,
/// a CD — gives `None` too: settings that cannot be saved are worse than settings saved in the
/// usual place.
pub fn portable_dir(exe: &Path) -> Option<PathBuf> {
    let dir = exe.parent()?;
    if !dir.join(PORTABLE_MARKER).is_file() {
        return None;
    }
    let data = dir.join(PORTABLE_DATA);
    std::fs::create_dir_all(&data).ok()?;
    let probe = data.join(".write-test");
    std::fs::write(&probe, b"ok").ok()?;
    let _ = std::fs::remove_file(&probe);
    Some(data)
}

/// The `instance-id=` value of a `/.flatpak-info` file, only when it is `[A-Za-z0-9_-]+` (it
/// becomes part of a file name).
pub fn parse_instance_id(info: &str) -> Option<String> {
    let v = info.lines().find_map(|l| l.strip_prefix("instance-id="))?.trim();
    (!v.is_empty() && v.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')).then(|| v.to_string())
}

/// The Flatpak instance id, or `None` outside Flatpak.
pub fn instance_id() -> Option<String> {
    parse_instance_id(&std::fs::read_to_string("/.flatpak-info").ok()?)
}

/// `<settings>/control-key.<instance>`, with `<instance>` the Flatpak instance id or
/// `local-<port>`.
pub fn key_path(settings: &Path, port: u16) -> PathBuf {
    key_path_for(settings, instance_id().as_deref(), port)
}

fn key_path_for(settings: &Path, instance: Option<&str>, port: u16) -> PathBuf {
    match instance {
        Some(id) => settings.join(format!("control-key.{id}")),
        None => settings.join(format!("control-key.local-{port}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn instance_id_only_safe_values() {
        assert_eq!(parse_instance_id("[Instance]\ninstance-id=abc_123-X\n").as_deref(), Some("abc_123-X"));
        assert_eq!(parse_instance_id("instance-id= 42 \n").as_deref(), Some("42"));
        // It ends up in a file name.
        assert_eq!(parse_instance_id("instance-id=../etc\n"), None);
        assert_eq!(parse_instance_id("instance-id=a/b\n"), None);
        assert_eq!(parse_instance_id("instance-id=a b\n"), None);
        assert_eq!(parse_instance_id("instance-id=..\n"), None);
        assert_eq!(parse_instance_id("instance-id=\n"), None);
        assert_eq!(parse_instance_id("app=ai.storyteller.wordcraft\n"), None);
    }

    #[test]
    fn key_file_per_instance() {
        let dir = Path::new("/settings/wordcraft");
        assert_eq!(key_path_for(dir, Some("1234"), 7981), dir.join("control-key.1234"));
        assert_eq!(key_path_for(dir, None, 7981), dir.join("control-key.local-7981"));
        assert_eq!(key_path_for(dir, None, 7982), dir.join("control-key.local-7982"));
        if instance_id().is_none() {
            assert_eq!(key_path(dir, 7981), dir.join("control-key.local-7981"));
        }
    }

    #[test]
    fn settings_dir_is_the_apps_folder() {
        if let Some(d) = settings_dir() {
            let name = d.file_name().and_then(|n| n.to_str()).unwrap_or("");
            assert!(name == "wordcraft" || name == "WordCraft", "{}", d.display());
        }
    }

    /// A temp folder standing in for the folder a portable copy sits in.
    fn temp_app_folder(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("wordcraft-portable-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn a_portable_copy_keeps_its_profile_beside_the_exe() {
        let dir = temp_app_folder("marked");
        let exe = dir.join("wordcraft.exe");
        std::fs::write(&exe, b"").unwrap();
        // No marker: the usual profile folder, wherever the app happens to be.
        assert_eq!(portable_dir(&exe), None);
        assert!(!dir.join(PORTABLE_DATA).exists(), "and nothing is created beside it");
        std::fs::write(dir.join(PORTABLE_MARKER), b"portable").unwrap();
        let data = portable_dir(&exe).expect("the marker makes the folder portable");
        assert_eq!(data, dir.join(PORTABLE_DATA));
        assert!(data.is_dir(), "and the profile folder exists");
        assert!(!data.join(".write-test").exists(), "the write test leaves nothing behind");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
