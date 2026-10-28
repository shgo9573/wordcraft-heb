//! Right-to-left interface layout: a Hebrew (or Arabic) interface mirrors what egui draws itself,
//! and the few rows WordCraft draws where a mirror is safe.
//!
//! egui's own chrome — menus and submenus, combo boxes, collapsing headers, scroll bars, window
//! title buttons — mirrors from `Style::right_to_left`, which
//! [`WordApp::install_ui_fonts`](crate::WordApp) sets from the interface language. Two surfaces of
//! the app mirror with the helpers here: the status bar's row of labels and a dialog's button row
//! (buttons belong at the trailing edge, which in Hebrew is the left one).
//!
//! **What stays left to right, and why:** the ribbon. It places its groups itself — `ribbon_fit`
//! measures every group, plans how it shrinks into the window and where the scroll offset is, and
//! all of that is written for a row that grows to the right. Opening the groups right to left piled
//! them on top of each other at the left edge of the window (reported against a Windows build), so
//! the ribbon keeps Word's left-to-right order in a Hebrew interface too, while its labels, the
//! tab strip, the menus, the dialogs and the document itself are Hebrew. Same for the mini toolbar and the gallery rows that size
//! themselves the same way. Fixing the ribbon properly means teaching `ribbon_fit` a mirrored row:
//! a project of its own, not a flag.
//!
//! Every function takes the same arguments as the `Ui` method of its name, so a surface turns
//! around by renaming the call. Left to right, they are the method itself: an English interface
//! lays out exactly as it did.

use egui::{Align, InnerResponse, Layout, Ui};

/// Is the interface laid out right to left? Set from the interface language
/// ([`Lang::is_rtl`](crate::i18n::Lang::is_rtl)) in `install_ui_fonts`.
pub fn is_rtl(ui: &Ui) -> bool {
    ui.style().right_to_left
}

/// [`Ui::horizontal`], right to left when the interface is.
pub fn horizontal<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        // The size `Ui::horizontal` reserves: the room left in the row, one control line tall.
        let size = egui::vec2(ui.available_size_before_wrap().x, ui.spacing().interact_size.y);
        ui.allocate_ui_with_layout(size, Layout::right_to_left(Align::Center), add)
    } else {
        ui.horizontal(add)
    }
}

/// [`Ui::horizontal_centered`], right to left when the interface is.
pub fn horizontal_centered<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        let size = ui.available_size_before_wrap();
        let layout = Layout::right_to_left(Align::Center).with_cross_align(Align::Center);
        ui.allocate_ui_with_layout(size, layout, add)
    } else {
        ui.horizontal_centered(add)
    }
}

/// [`Ui::horizontal_top`], right to left when the interface is.
///
/// No surface uses this now: the ribbon did, and a Hebrew ribbon piled its groups on top of each
/// other (see the module note). A surface that measures its own children the way `ribbon_fit` does
/// must be taught the mirrored row before it takes this.
pub fn horizontal_top<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        let size = ui.available_size_before_wrap();
        let layout = Layout::right_to_left(Align::Center).with_cross_align(Align::Min);
        ui.allocate_ui_with_layout(size, layout, add)
    } else {
        ui.horizontal_top(add)
    }
}

/// [`Ui::horizontal_wrapped`], right to left when the interface is.
pub fn horizontal_wrapped<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        let size = egui::vec2(ui.available_size_before_wrap().x, ui.spacing().interact_size.y);
        let layout = Layout::right_to_left(Align::Center).with_main_wrap(true);
        ui.allocate_ui_with_layout(size, layout, add)
    } else {
        ui.horizontal_wrapped(add)
    }
}

/// [`Ui::with_layout`], mirrored when the interface is right to left: a horizontal layout
/// (`Layout::left_to_right`, `Layout::right_to_left`) swaps its direction, so callers say where
/// a row's content belongs in an English interface and get the mirror image in a Hebrew one.
pub fn with_layout<R>(ui: &mut Ui, layout: Layout, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    // Only the main direction turns around: wrapping, main and cross alignment stay the caller's.
    let main_dir = match (is_rtl(ui), layout.main_dir()) {
        (true, egui::Direction::LeftToRight) => egui::Direction::RightToLeft,
        (true, egui::Direction::RightToLeft) => egui::Direction::LeftToRight,
        _ => layout.main_dir(),
    };
    ui.with_layout(Layout { main_dir, ..layout }, add)
}

/// [`Layout::left_to_right`], right to left when the interface is: for a layout handed to
/// `allocate_ui_with_layout` or a child `Ui` rather than made by [`with_layout`].
///
/// Like [`horizontal_top`], unused while the ribbon is left to right: a row whose widths the code
/// around it measures (`ui.cursor().min.x - start.x`) must not be mirrored.
pub fn left_to_right(ui: &Ui, valign: Align) -> Layout {
    if is_rtl(ui) { Layout::right_to_left(valign) } else { Layout::left_to_right(valign) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_english_interface_lays_out_exactly_as_before() {
        let ctx = egui::Context::default();
        let mut rtl = None;
        let mut seen = Vec::new();
        let _ = ctx
            .run_ui(Default::default(), |ui| {
                horizontal(ui, |ui| {
                    ui.label("a");
                    ui.label("b");
                    seen.push("a".to_string());
                });
                rtl = Some(is_rtl(ui));
            })
            .drop_without_applying_deltas();
        assert_eq!(rtl, Some(false));
        assert_eq!(seen, ["a"]);
    }

    #[test]
    fn a_hebrew_interface_puts_the_first_widget_at_the_right() {
        let ctx = egui::Context::default();
        ctx.all_styles_mut(|s| s.set_right_to_left(true));
        let mut xs = (0.0f32, 0.0f32);
        let _ = ctx
            .run_ui(Default::default(), |ui| {
                horizontal(ui, |ui| {
                    let a = ui.label("a").rect.left();
                    let b = ui.label("b").rect.left();
                    xs = (a, b);
                });
            })
            .drop_without_applying_deltas();
        assert!(xs.0 > xs.1, "the first widget sits right of the second: {xs:?}");
    }

    #[test]
    fn with_layout_mirrors_a_row_and_leaves_a_column_alone() {
        let ctx = egui::Context::default();
        let mut dirs = Vec::new();
        let _ = ctx
            .run_ui(Default::default(), |ui| {
                let row = with_layout(ui, Layout::left_to_right(Align::Center), |ui| (ui.layout().main_dir(), ui.layout().cross_align()));
                let column = with_layout(ui, Layout::top_down(Align::Min), |ui| (ui.layout().main_dir(), ui.layout().cross_align()));
                dirs = vec![row.inner, column.inner];
            })
            .drop_without_applying_deltas();
        assert_eq!(dirs[0], (egui::Direction::LeftToRight, Align::Center), "no style, no mirror");
        assert_eq!(dirs[1], (egui::Direction::TopDown, Align::Min));
        ctx.all_styles_mut(|s| s.set_right_to_left(true));
        let mut mirrored = Vec::new();
        let _ = ctx
            .run_ui(Default::default(), |ui| {
                let row = with_layout(ui, Layout::left_to_right(Align::Center), |ui| ui.layout().main_dir());
                let other = with_layout(ui, Layout::right_to_left(Align::Max), |ui| ui.layout().main_dir());
                let column = with_layout(ui, Layout::top_down(Align::Min), |ui| ui.layout().main_dir());
                mirrored = vec![row.inner, other.inner, column.inner];
            })
            .drop_without_applying_deltas();
        assert_eq!(mirrored, [egui::Direction::RightToLeft, egui::Direction::LeftToRight, egui::Direction::TopDown]);
    }
}
