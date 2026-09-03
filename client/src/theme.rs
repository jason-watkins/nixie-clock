use egui::Color32;
use egui::Context;
use egui::Theme;

use crate::app::Settings;

pub fn apply(context: &Context, settings: &Settings) {
    for theme in [Theme::Dark, Theme::Light] {
        context.style_mut_of(theme, |style| {
            style.visuals.override_text_color = Some(text_color(theme, settings));
        });
    }
}

fn text_color(theme: Theme, settings: &Settings) -> Color32 {
    match (theme, settings.high_contrast_text) {
        (Theme::Dark, true) => Color32::from_gray(230),
        (Theme::Dark, false) => Color32::from_gray(210),
        (Theme::Light, true) => Color32::from_gray(20),
        (Theme::Light, false) => Color32::from_gray(40),
    }
}
