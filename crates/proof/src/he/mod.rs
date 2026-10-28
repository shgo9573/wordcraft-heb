//! Hebrew proofing (עברית): spelling against the installed Hunspell `he_IL` dictionary (never
//! bundled — no Hebrew word list is redistributed here), suggestions that know Hebrew's final
//! letters and prefixes, and grammar checks with Hebrew messages.
//!
//! Hebrew is written without niqqud in most documents, and its words carry particles as prefixes:
//! `ובבית` is `ו` + `ב` + `בית`, `מהספר` is `מ` + `ה` + `ספר`. A dictionary lookup alone flags
//! every one of those, so a word is also correct when stripping one to three leading particles
//! ([`PREFIXES`]) leaves a dictionary word — the way Hspell and Word's Hebrew speller read Hebrew.
//! Niqqud and cantillation ([`strip_points`]) are ignored: `בַּיִת` is `בית`.
//!
//! Five letters change shape at the end of a word (כ→ך, מ→ם, נ→ן, פ→ף, צ→ץ). A word that ends
//! with the ordinary form is a misspelling, and the suggestion is the word with the final form —
//! with the dictionary's own word behind it, never a guess: `שלומ` → `שלום`.
//!
//! Without an installed `he_IL` dictionary Hebrew has no spelling marks (as Word without the
//! language's proofing tools), but the grammar checks ([`grammar`]) still run.

pub mod grammar;
pub(crate) mod suggest;
#[cfg(test)]
pub(crate) mod test_dict;

use std::sync::{Arc, RwLock};

use crate::affix::AffixDict;

pub use suggest::suggest;

/// The Hebrew dictionary and whether it came from [`install_dictionary`] rather than a file on
/// disk.
static DICT: RwLock<DictState> = RwLock::new(DictState { dict: None, in_memory: false });

struct DictState {
    dict: Option<Arc<AffixDict>>,
    in_memory: bool,
}

/// File names of a Hebrew Hunspell dictionary (`hunspell-he`, `hspell`'s Hunspell build, the
/// dictionaries macOS and LibreOffice ship).
const NAMES: &[&str] = &["he_IL", "he-IL", "he"];

/// The particles Hebrew attaches to the front of a word: ו (and), ב (in), ל (to), מ (from),
/// ש (that), ה (the), כ (as). Up to three can stack (`ושב`, `כשא`, `מלב`).
const PREFIXES: [char; 7] = ['ו', 'ב', 'ל', 'מ', 'ש', 'ה', 'כ'];

/// The final form of a letter that changes shape at the end of a word.
fn final_form(c: char) -> Option<char> {
    Some(match c {
        'כ' => 'ך',
        'מ' => 'ם',
        'נ' => 'ן',
        'פ' => 'ף',
        'צ' => 'ץ',
        _ => return None,
    })
}

/// The same letter in its ordinary (not final) form.
fn regular_form(c: char) -> Option<char> {
    Some(match c {
        'ך' => 'כ',
        'ם' => 'מ',
        'ן' => 'נ',
        'ף' => 'פ',
        'ץ' => 'צ',
        _ => return None,
    })
}

/// Is `c` a Hebrew letter (the Hebrew block's letters, with or without points)?
pub fn is_hebrew_letter(c: char) -> bool {
    matches!(c, '\u{05D0}'..='\u{05EA}' | '\u{FB1D}'..='\u{FB4E}')
}

/// Is `c` a niqqud (vowel point), a cantillation mark or another combining mark of the Hebrew
/// block? Hebrew spelling ignores them.
fn is_point(c: char) -> bool {
    matches!(c, '\u{0591}'..='\u{05C7}' | '\u{FB1E}' | '\u{FB1F}')
}

/// `word` without its niqqud and cantillation: `בַּיִת` → `בית`. Words with none are borrowed.
pub fn strip_points(word: &str) -> std::borrow::Cow<'_, str> {
    if word.chars().any(is_point) {
        std::borrow::Cow::Owned(word.chars().filter(|c| !is_point(*c)).collect())
    } else {
        std::borrow::Cow::Borrowed(word)
    }
}

/// The Hebrew dictionary: the installed Hunspell `he_IL` (read on first use), one given with
/// [`install_dictionary`], or an empty one when none is available (spelling is off then; see
/// [`has_dictionary`]).
pub fn dictionary() -> Arc<AffixDict> {
    if let Some(d) = DICT.read().unwrap_or_else(std::sync::PoisonError::into_inner).dict.as_ref() {
        return d.clone();
    }
    let loaded = Arc::new(load_installed());
    let mut slot = DICT.write().unwrap_or_else(std::sync::PoisonError::into_inner);
    slot.dict.get_or_insert(loaded).clone()
}

fn load_installed() -> AffixDict {
    let Some((aff, dic)) = crate::hunspell::find(NAMES) else {
        crate::hunspell::clear_load_error(NAMES[0]);
        log::info!("Hebrew spelling: no Hunspell he_IL dictionary installed");
        return AffixDict::default();
    };
    crate::hunspell::note_load(NAMES[0], &dic, crate::hunspell::load(&aff, &dic)).unwrap_or_else(|e| {
        log::warn!("Hebrew spelling: {e}");
        AffixDict::default()
    })
}

/// Use this Hebrew dictionary from now on (Hunspell `.aff` and `.dic` text, decoded to UTF-8),
/// for example one the user picked. On error the current dictionary stays.
pub fn install_dictionary(aff: &str, dic: &str) -> Result<(), String> {
    let d = AffixDict::from_hunspell(aff, dic, &[])?;
    let mut slot = DICT.write().unwrap_or_else(std::sync::PoisonError::into_inner);
    slot.dict = Some(Arc::new(d));
    slot.in_memory = true;
    Ok(())
}

/// Forget the loaded dictionary, so the next check looks for an installed one again.
pub fn reload_dictionary() {
    let mut slot = DICT.write().unwrap_or_else(std::sync::PoisonError::into_inner);
    slot.dict = None;
    slot.in_memory = false;
}

/// The `.dic` file of the installed Hebrew dictionary (File › Options › Proofing shows it);
/// `None` when there is none.
pub fn installed_path() -> Option<std::path::PathBuf> {
    if DICT.read().unwrap_or_else(std::sync::PoisonError::into_inner).in_memory {
        return None;
    }
    crate::hunspell::find(NAMES).map(|(_, dic)| dic)
}

/// Is a Hebrew dictionary available (spelling is checked)?
pub fn has_dictionary() -> bool {
    !dictionary().is_empty()
}

/// Is `word` spelled correctly in Hebrew?
pub fn is_correct(word: &str) -> bool {
    is_correct_with(&dictionary(), word)
}

/// [`is_correct`] with the File › Options › Proofing choices: with Ignore words in UPPERCASE off
/// (no Hebrew letter has a case, so this only affects Latin words inside Hebrew text) and Ignore
/// words that contain numbers off, such words are checked here too.
pub fn is_correct_with_options(word: &str, opts: &crate::Options) -> bool {
    check(&dictionary(), word, opts)
}

/// [`is_correct`] against a given dictionary (an empty one accepts everything).
pub fn is_correct_with(d: &AffixDict, word: &str) -> bool {
    check(d, word, &crate::Options::default())
}

/// [`is_correct_with_options`] against a given dictionary.
fn check(d: &AffixDict, word: &str, opts: &crate::Options) -> bool {
    if d.is_empty() {
        return true; // no Hebrew dictionary installed: no spelling marks
    }
    let w = word.trim_matches(|c: char| !c.is_alphanumeric() && c != '\'' && c != '"');
    let n = w.chars().count();
    if n <= 1 || (opts.ignore_numbers && w.chars().any(|c| c.is_ascii_digit())) || !w.chars().any(char::is_alphabetic) {
        return true;
    }
    if opts.ignore_uppercase && w.chars().all(|c| !c.is_lowercase()) && w.chars().any(|c| c.is_ascii_alphabetic()) {
        return true;
    }
    // A word with no Hebrew letter is not Hebrew (a Latin name, a number, another script): the
    // dictionary says nothing about it.
    if !w.chars().any(is_hebrew_letter) {
        return true;
    }
    if w.chars().any(|c| c == '-' || c == '\u{05BE}') {
        return w.split(['-', '\u{05BE}']).all(|part| part.chars().count() <= 1 || known(d, part));
    }
    known(d, w)
}

/// Is one word (no maqaf, no hyphen) in the dictionary, the user dictionary, or a prefixed form
/// of one (`ובבית`, `מהספר`)?
fn known(d: &AffixDict, w: &str) -> bool {
    let w = strip_points(w);
    let w = w.trim_matches(['\'', '"', '׳', '״']);
    if w.is_empty() {
        return true;
    }
    if d.check(w) || crate::in_user_dictionary(w) {
        return true;
    }
    let chars: Vec<char> = w.chars().collect();
    for n in 1..=3.min(chars.len().saturating_sub(1)) {
        if !chars[..n].iter().all(|c| PREFIXES.contains(c)) {
            break;
        }
        let rest: String = chars[n..].iter().collect();
        if d.check(&rest) || crate::in_user_dictionary(&rest) {
            return true;
        }
    }
    // A word ending in the ordinary form of a letter that has a final form is still checked as
    // written: the misspelling is reported, with the final-form word as its suggestion
    // ([`suggest`]). A dictionary that spells the word without the final form (an abbreviation
    // like `עמ`) is honoured above.
    false
}

/// The word `w` with its final letter in the final form, when it ends in the ordinary form of a
/// letter that has one (`שלומ` → `שלום`, `ארצ` → `ארץ`).
fn with_final_form(w: &str) -> Option<String> {
    let mut chars: Vec<char> = w.chars().collect();
    let last = chars.last().copied()?;
    let final_letter = final_form(last)?;
    *chars.last_mut()? = final_letter;
    Some(chars.into_iter().collect())
}

/// The word `w` with its last letter in the ordinary form, when a dictionary word has it that way
/// (`עמ` written `עם`).
#[cfg(test)]
fn with_regular_form(w: &str) -> Option<String> {
    let mut chars: Vec<char> = w.chars().collect();
    let last = chars.last().copied()?;
    let regular = regular_form(last)?;
    *chars.last_mut()? = regular;
    Some(chars.into_iter().collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dictionary_lookup_accepts_hebrew_file_names() {
        let dir = std::env::temp_dir().join(format!("wordcraft-he-aliases-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        for name in ["he_IL", "he-IL", "he"] {
            std::fs::write(dir.join(format!("{name}.aff")), test_dict::AFF).unwrap();
            std::fs::write(dir.join(format!("{name}.dic")), test_dict::DIC).unwrap();
            let (aff, dic) = crate::hunspell::find_in(&dir, NAMES).unwrap();
            let d = crate::hunspell::load(&aff, &dic).unwrap();
            assert!(is_correct_with(&d, "שלום"), "{name}");
            std::fs::remove_file(aff).unwrap();
            std::fs::remove_file(dic).unwrap();
        }
        std::fs::remove_dir(dir).unwrap();
    }

    #[test]
    fn hebrew_words_prefixes_points_and_final_forms() {
        test_dict::install();
        assert!(has_dictionary());
        // As written.
        for w in ["שלום", "בית", "ספר", "ילד", "עיר", "דבר"] {
            assert!(is_correct(w), "{w}");
        }
        // Particles: one, two and three of them.
        for w in ["ובית", "מהספר", "ושלום", "וכשדבר", "לעיר", "הילד"] {
            assert!(is_correct(w), "{w}");
        }
        // Niqqud and cantillation are ignored.
        for w in ["בַּיִת", "שָׁלוֹם", "סֵפֶר"] {
            assert!(is_correct(w), "{w}");
        }
        // Words the fixture doesn't have are reported, with or without points.
        for w in ["שאלום", "ביית", "בַּיִית"] {
            assert!(!is_correct(w), "{w}");
        }
    }

    #[test]
    fn a_word_ending_in_an_ordinary_form_is_suggested_its_final_form() {
        test_dict::install();
        for (wrong, right) in [("שלומ", "שלום"), ("ארצ", "ארץ"), ("גנ", "גן")] {
            assert!(!is_correct(wrong), "{wrong}");
            assert_eq!(suggest(wrong, 4).first().map(String::as_str), Some(right), "{wrong}");
        }
        assert_eq!(with_final_form("שלומ").as_deref(), Some("שלום"));
        assert_eq!(with_final_form("שלום"), None, "already final");
        assert_eq!(with_regular_form("עם").as_deref(), Some("עמ"));
        assert_eq!(strip_points("בַּיִת"), "בית");
        assert_eq!(strip_points("בית"), "בית");
    }

    #[test]
    fn missing_dictionary_and_ignored_inputs_are_quiet() {
        let empty = AffixDict::default();
        assert!(is_correct_with(&empty, "שאלום"));
        let d = AffixDict::from_hunspell(test_dict::AFF, test_dict::DIC, &[]).unwrap();
        for w in ["", "א", "2026", "שלום2", "WordCraft", "日本語"] {
            assert!(is_correct_with(&d, w), "{w}");
        }
    }

    #[test]
    fn hebrew_dispatch_messages_options_and_mixed_spans() {
        test_dict::install();
        assert!(crate::has_dictionary(Some("he-IL")));
        assert!(crate::is_correct_for("שלום", Some("heb")));
        let text = "שלום שאלום";
        let issues = crate::check_text(text, &[(0..text.len(), crate::ProofLang::He)]);
        assert_eq!(issues.len(), 1, "{issues:?}");
        assert_eq!(&text[issues[0].start..issues[0].end], "שאלום");
        assert_eq!(issues[0].message, "ייתכן שגיאת כתיב");
        assert_eq!(issues[0].lang, crate::ProofLang::He);
        assert!(crate::suggest_in("שאלום", 8, crate::ProofLang::He).contains(&"שלום".to_string()));
    }

    #[test]
    fn the_user_dictionary_applies() {
        test_dict::install();
        assert!(!is_correct("זקשםשאלום"));
        crate::add_word("זקשםשאלום");
        assert!(is_correct("זקשםשאלום"));
    }
}
