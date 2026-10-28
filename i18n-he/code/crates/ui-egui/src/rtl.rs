//! Right-to-left interface layout: a Hebrew (or Arabic) interface mirrors what egui draws itself,
//! and the parts of the app that place their own widgets — the ribbon above all.
//!
//! egui's own chrome — menus and submenus, combo boxes, collapsing headers, scroll bars, window
//! title buttons — mirrors from `Style::right_to_left`, which
//! [`WordApp::install_ui_fonts`](crate::WordApp) sets from the interface language. Its `horizontal*`
//! helpers follow the *row* they are drawn in, so a row this module turns around carries its
//! buttons, its stacks and its menus around with it.
//!
//! The ribbon places its own widgets, so it asks here: its row runs right to left (the first group
//! starts at the right edge, `widgets::group_titled` measures each group by the row's right edge
//! and draws its controls right to left, `ribbon_fit` shrinks the leftmost groups first), and the
//! tab strip keeps File at the right with Share, Editing and Comments at the left.
//!
//! Two things stay as they are in a Hebrew interface, and for a reason:
//!
//! * The document itself is right to left as text (bidi), but its pages, rulers and scroll bars are
//!   laid out by the engine, not here.
//! * The ribbon's edge chevrons are not drawn, because a scroll area counts its offset from the
//!   left of its content while a mirrored row grows leftwards, so a chevron press would scroll the
//!   wrong way; `ribbon_fit` folds groups until the row fits instead.
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

/// A size a child can be laid out in: a right-to-left row can be offered an unbounded one (the
/// space to its left has no end at the edge of the window), and a row laid out `∞` wide from the
/// right edge starts at `-∞`, whose rect is `NaN` and stops the frame. The screen is the bound:
/// a row never needs to be wider than that to place its widgets.
fn bounded(ui: &Ui, size: egui::Vec2) -> egui::Vec2 {
    let screen = ui.ctx().screen_rect().size();
    let finite = |v: f32, fallback: f32| if v.is_finite() && v >= 0.0 { v } else { fallback };
    egui::vec2(finite(size.x, screen.x), finite(size.y, screen.y))
}

/// [`Ui::horizontal`], right to left when the interface is.
pub fn horizontal<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        // The size `Ui::horizontal` reserves: the room left in the row, one control line tall.
        let size = egui::vec2(ui.available_size_before_wrap().x, ui.spacing().interact_size.y);
        ui.allocate_ui_with_layout(bounded(ui, size), Layout::right_to_left(Align::Center), add)
    } else {
        ui.horizontal(add)
    }
}

/// [`Ui::horizontal_centered`], right to left when the interface is.
pub fn horizontal_centered<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        let size = bounded(ui, ui.available_size_before_wrap());
        let layout = Layout::right_to_left(Align::Center).with_cross_align(Align::Center);
        ui.allocate_ui_with_layout(size, layout, add)
    } else {
        ui.horizontal_centered(add)
    }
}

/// [`Ui::horizontal_top`], right to left when the interface is: the ribbon's row of groups, and
/// the row of controls in a folded group's drop-down.
pub fn horizontal_top<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        let size = bounded(ui, ui.available_size_before_wrap());
        let layout = Layout::right_to_left(Align::Center).with_cross_align(Align::Min);
        ui.allocate_ui_with_layout(size, layout, add)
    } else {
        ui.horizontal_top(add)
    }
}

/// [`Ui::horizontal_wrapped`], right to left when the interface is.
pub fn horizontal_wrapped<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        let size = bounded(ui, egui::vec2(ui.available_size_before_wrap().x, ui.spacing().interact_size.y));
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

/// A column that hugs the trailing edge of its row when the interface is right to left
/// ([`Ui::vertical`], whose `Align::Min` is the left edge in either direction).
///
/// A control stack inside a mirrored row needs this: to the left of a right-to-left row's cursor
/// there is no bound, so a left-aligned column there would place its buttons off the window.
pub fn vertical_top<R>(ui: &mut Ui, add: impl FnOnce(&mut Ui) -> R) -> InnerResponse<R> {
    if is_rtl(ui) {
        ui.with_layout(Layout::top_down(Align::Max), add)
    } else {
        ui.vertical(add)
    }
}

/// [`Layout::left_to_right`], right to left when the interface is: for a layout handed to
/// `allocate_ui_with_layout` or a child `Ui` rather than made by [`with_layout`].
///
/// A row whose widths the code around it measures must be measured by the edge it starts at
/// (`widgets::group_titled` measures a group to the row's right edge in a Hebrew row).
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
