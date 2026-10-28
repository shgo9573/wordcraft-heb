//! Hebrew grammar checks, with Hebrew messages: a word written twice, a double space, a space
//! before punctuation, a missing space after it, and spaces around the maqaf (־), which joins
//! Hebrew words with no space on either side (`בית־ספר`).
//!
//! Hebrew has no capitals, so there is no sentence-capital rule and no `a`/`an`. Nothing about
//! niqqud, agreement or word order is guessed: only what is certain on the page.

use crate::{Issue, IssueKind, ProofLang, words};

fn issue(start: usize, end: usize, message: String, suggestions: Vec<String>) -> Issue {
    Issue { start, end, kind: IssueKind::Grammar, message, suggestions, lang: ProofLang::He }
}

/// The maqaf: a hyphen that joins Hebrew words without spaces.
const MAQAF: char = '\u{05BE}';

pub fn check(text: &str) -> Vec<Issue> {
    let mut issues = Vec::new();
    repeated_words(text, &words(text), &mut issues);
    spaces(text, &mut issues);
    maqaf(text, &mut issues);
    issues.sort_by_key(|i| (i.start, i.end));
    issues
}

fn repeated_words(text: &str, ws: &[(usize, usize)], v: &mut Vec<Issue>) {
    for pair in ws.windows(2) {
        let [(a0, b0), (a1, b1)] = pair else { continue };
        let (Some(w0), Some(w1), Some(gap)) = (text.get(*a0..*b0), text.get(*a1..*b1), text.get(*b0..*a1)) else { continue };
        if !gap.is_empty() && gap.chars().all(char::is_whitespace) && w0.chars().all(char::is_alphabetic) && w0 == w1 {
            v.push(issue(*a0, *b1, format!("מילה כפולה: „{w1}“"), vec![w0.to_string()]));
        }
    }
}

fn spaces(text: &str, v: &mut Vec<Issue>) {
    for (i, c) in text.char_indices() {
        match c {
            ' ' => {
                let rest = text.get(i + 1..).unwrap_or("");
                let mut it = rest.chars();
                let Some(p) = it.next() else { continue };
                let after = it.next();
                // A ratio keeps its spaces (`2 : 1`), and ` .5` is a number.
                let ratio = p == ':'
                    && text.get(..i).and_then(|before| before.chars().next_back()).is_some_and(|c| c.is_ascii_digit())
                    && after == Some(' ')
                    && it.next().is_some_and(|c| c.is_ascii_digit());
                let flag = !ratio
                    && match p {
                        ',' | ';' => true,
                        '.' => !matches!(after, Some('.')) && !after.is_some_and(|a| a.is_ascii_digit()),
                        ':' | '!' | '?' => after.is_none_or(|a| a.is_whitespace() || matches!(a, '"' | '”' | '\'' | '’' | '!' | '?')),
                        _ => false,
                    };
                if flag {
                    v.push(issue(i, i + 1 + p.len_utf8(), "רווח לפני סימן פיסוק".into(), vec![p.to_string()]));
                }
            }
            // A punctuation mark glued to the next word: `שלום,מה`.
            ',' | ';' | ':' | '.' | '!' | '?' => {
                let next = text.get(i + c.len_utf8()..).and_then(|t| t.chars().next());
                let glued = next.is_some_and(|n| is_hebrew(n));
                // `1,000` and `3.5` are numbers; `...` is an ellipsis.
                let previous = text.get(..i).and_then(|t| t.chars().next_back());
                let number = previous.is_some_and(|p| p.is_ascii_digit()) && next.is_some_and(|n| n.is_ascii_digit());
                let ellipsis = next == Some('.') || next == Some(',');
                if glued && !number && !ellipsis {
                    v.push(issue(i, i + c.len_utf8() + next.map_or(0, char::len_utf8), "חסר רווח אחרי סימן פיסוק".into(), Vec::new()));
                }
            }
            _ => {}
        }
    }
    for (i, _) in text.match_indices("  ") {
        if i > 0 && text.get(..i).is_some_and(|t| t.ends_with(' ')) {
            continue;
        }
        v.push(issue(i, i + 2, "רווח כפול".into(), vec![" ".into()]));
    }
}

/// The maqaf joins two words: no space before it and none after it (`בית־ספר`).
fn maqaf(text: &str, v: &mut Vec<Issue>) {
    for (i, c) in text.char_indices() {
        if c != MAQAF {
            continue;
        }
        let before = text.get(..i).and_then(|t| t.chars().next_back());
        if before.is_some_and(char::is_whitespace) {
            let start = text.get(..i).and_then(|t| t.char_indices().next_back()).filter(|(_, c)| c.is_whitespace()).map_or(i, |(j, _)| j);
            v.push(issue(start, i, "רווח לפני מקף".into(), vec![MAQAF.to_string()]));
        }
        let after = text.get(i + c.len_utf8()..).and_then(|t| t.chars().next());
        if after.is_some_and(char::is_whitespace) {
            let end = i + c.len_utf8() + after.map_or(0, char::len_utf8);
            v.push(issue(i, end, "רווח אחרי מקף".into(), vec![MAQAF.to_string()]));
        }
    }
}

/// Is `c` a Hebrew letter? The grammar checks only need the block's letters.
fn is_hebrew(c: char) -> bool {
    matches!(c, '\u{05D0}'..='\u{05EA}')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repeated_words_and_spaces_have_hebrew_messages() {
        let text = "שלום שלום ,  בית.";
        let issues = check(text);
        assert_eq!(issues.len(), 3, "{issues:?}");
        assert_eq!(issues[0].message, "מילה כפולה: „שלום“");
        assert_eq!(issues[0].suggestions, ["שלום"]);
        assert!(issues.iter().any(|i| i.message == "רווח לפני סימן פיסוק" && &text[i.start..i.end] == " ,"));
        assert!(issues.iter().any(|i| i.message == "רווח כפול"));
        assert!(issues.iter().all(|i| i.lang == ProofLang::He && i.kind == IssueKind::Grammar));
        for clean in ["שלום, עולם.", "בית־ספר", "המחיר 1,000 שקלים", "ומה איתך?", "סוף…"] {
            assert!(check(clean).is_empty(), "{clean}: {:?}", check(clean));
        }
    }

    #[test]
    fn a_glued_punctuation_mark_and_a_spaced_maqaf_are_reported() {
        let text = "שלום,מה נשמע ובית ־ ספר";
        let issues = check(text);
        assert!(issues.iter().any(|i| i.message == "חסר רווח אחרי סימן פיסוק" && &text[i.start..i.end] == ",מ"), "{issues:?}");
        assert!(issues.iter().any(|i| i.message == "רווח לפני מקף"), "{issues:?}");
    }
}
