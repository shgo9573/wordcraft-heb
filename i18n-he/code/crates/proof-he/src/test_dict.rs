//! Hand-written synthetic Hebrew test data. No words, rules or tables were copied from a system
//! dictionary. This is a small fixture, not a redistributable Hebrew dictionary.

pub const AFF: &str = "SET UTF-8
FLAG UTF-8
TRY שלוםביתארץגנדברעירכמה
FORBIDDENWORD F
";

pub const DIC: &str = "13
שלום
בית
ספר
ילד
עיר
דבר
שאלון
ארץ
גן
עמ
שם
מים
זקשםזקשזק/F
";

pub fn install() {
    super::install_dictionary(AFF, DIC).unwrap();
}
