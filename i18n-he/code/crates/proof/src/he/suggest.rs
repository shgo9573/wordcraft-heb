//! Hebrew suggestions, best first: the dictionary's own words, never a guess.
//!
//! 1. **The final letter**: `שלומ` → `שלום`, `ארצ` → `ארץ` — the commonest Hebrew typing slip,
//!    since five letters change shape at the end of a word.
//! 2. **A particle in front of the word**: `מבײת` → `מבית`. Hebrew attaches ו, ב, ל, מ, ש, ה and
//!    כ (up to three of them) to the front of a word, and the dictionary holds the word without
//!    them, so each leading particle is taken off, the rest corrected, and the particle put back.
//! 3. **One or two edits away**, counted over the stems of the installed dictionary, keeping the
//!    first letter when a stem shares it (Hebrew typos rarely change the opening letter), then
//!    over every stem of the right length when nothing shares it.
//!
//! Everything is read from the installed `he_IL` dictionary: with none installed there are no
//! suggestions (and no spelling marks).

use crate::affix::AffixDict;

/// Longest word suggestions are looked for, in letters.
const MAX_LETTERS: usize = 40;
/// Stems examined in one search before it gives up (a Hebrew dictionary has ~100k).
const MAX_STEMS: usize = 400_000;

/// Suggestions for `word` in Hebrew, best first, at most `max`.
pub(crate) fn suggest(word: &str, max: usize) -> Vec<String> {
    let d = super::dictionary();
    suggest_with(&d, word, max)
}

/// [`suggest`] against a given dictionary (tests, and a dictionary the user picked).
pub(crate) fn suggest_with(d: &AffixDict, word: &str, max: usize) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let w = super::strip_points(word);
    let w = w.trim_matches(|c: char| !c.is_alphanumeric() && c != '\'' && c != '"');
    let letters: Vec<char> = w.chars().collect();
    if letters.is_empty() || letters.len() > MAX_LETTERS || d.is_empty() || super::known(d, w) {
        return out;
    }
    // The whole word as typed, then the same word with one, two or three leading particles taken
    // off and put back on each correction. The longest particle comes last, so a real word's own
    // letters are tried before they are read as particles.
    let parts = letters.iter().copied().take_while(|c| super::PREFIXES.contains(c)).count().min(3).min(letters.len().saturating_sub(1));
    for n in 0..=parts {
        let prefix: String = letters[..n].iter().collect();
        let rest: String = letters[n..].iter().collect();
        for cand in corrections(d, &rest) {
            let word = format!("{prefix}{cand}");
            if word != w && !out.contains(&word) {
                out.push(word);
                if out.len() >= max {
                    return out;
                }
            }
        }
    }
    out
}

/// The dictionary's corrections of one word, best first: its final letter (`שלומ` → `שלום`),
/// then the stems one or two edits away.
fn corrections(d: &AffixDict, word: &str) -> Vec<String> {
    let letters: Vec<char> = word.chars().collect();
    if letters.len() < 2 {
        return Vec::new();
    }
    let mut out: Vec<String> = Vec::new();
    if let Some(fixed) = super::with_final_form(word) {
        if d.check(&fixed) {
            out.push(fixed);
        }
    }
    if d.check(word) {
        // Already a word: nothing to correct, and the caller puts the particle back on it.
        return out;
    }
    let first: String = letters[..1].iter().collect();
    let mut stems: Vec<&str> = d.stems_with_prefix(&first).take(MAX_STEMS).collect();
    if stems.is_empty() {
        let n = letters.len();
        stems = d
            .stems()
            .filter(|s| {
                let len = s.chars().count();
                len + 2 >= n && len <= n + 2
            })
            .take(MAX_STEMS)
            .collect();
    }
    let mut scored: Vec<(usize, String)> = Vec::new();
    for stem in stems {
        let len = stem.chars().count();
        if len + 2 < letters.len() || len > letters.len() + 2 {
            continue;
        }
        let dist = crate::damerau(&letters, stem);
        if dist <= 2 {
            scored.push((dist, stem.to_string()));
        }
    }
    scored.sort_by(|a, b| (a.0, a.1.len().abs_diff(word.len())).cmp(&(b.0, b.1.len().abs_diff(word.len()))).then(a.1.cmp(&b.1)));
    for (_, stem) in scored {
        if !out.contains(&stem) {
            out.push(stem);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_final_letter_comes_first() {
        super::super::test_dict::install();
        assert_eq!(suggest("שלומ", 4).first().map(String::as_str), Some("שלום"));
        assert_eq!(suggest("ארצ", 4).first().map(String::as_str), Some("ארץ"));
    }

    #[test]
    fn an_edit_away_finds_the_dictionary_word() {
        super::super::test_dict::install();
        for (wrong, right) in [("שאלום", "שלום"), ("ביית", "בית"), ("ספשר", "ספר")] {
            let got = suggest(wrong, 8);
            assert!(got.contains(&right.to_string()), "{wrong}: {got:?}");
        }
    }

    #[test]
    fn a_particle_in_front_survives_the_correction() {
        super::super::test_dict::install();
        let got = suggest("מביח", 8);
        assert!(got.contains(&"מבית".to_string()), "{got:?}");
        assert!(suggest("והספר", 8).is_empty(), "a correct word with two particles needs no suggestion");
    }

    #[test]
    fn nothing_is_suggested_without_a_dictionary() {
        let empty = AffixDict::default();
        assert!(suggest_with(&empty, "שאלום", 8).is_empty());
    }
}
