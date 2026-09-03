use eframe::AppCreator;
use eframe::NativeOptions;
use egui::ViewportBuilder;

use crate::app::App;

mod app;
mod firmware;
mod net;
mod theme;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let app_name = "nixie_client";
    let native_options = NativeOptions {
        viewport: ViewportBuilder::default()
            .with_title("Nixie Clock")
            .with_inner_size([1100.0, 700.0])
            .with_min_inner_size([800.0, 600.0]),
        persist_window: true,
        ..Default::default()
    };
    let app_creator: AppCreator<'_> = Box::new(|cc| Ok(Box::new(App::new(cc))));
    eframe::run_native(app_name, native_options, app_creator)?;
    Ok(())
}
