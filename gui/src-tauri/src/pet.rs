use std::sync::Mutex;

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

const PET_LABEL: &str = "pet";

pub struct PetState(pub Mutex<Option<Value>>);

fn pet_window(app: &AppHandle) -> Option<tauri::WebviewWindow> {
    app.get_webview_window(PET_LABEL)
}

fn ensure_pet_window(app: &AppHandle) -> tauri::WebviewWindow {
    if let Some(window) = pet_window(app) {
        return window;
    }
    WebviewWindowBuilder::new(app, PET_LABEL, WebviewUrl::App("pet.html".into()))
        .title("XEYO 桌宠")
        .inner_size(170.0, 190.0)
        .min_inner_size(170.0, 190.0)
        .resizable(false)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(false)
        .additional_browser_args("--enable-gpu --ignore-gpu-blocklist --force-gpu-rasterization --enable-zero-copy --enable-features=CanvasOopRasterization --disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection,CalculateNativeWinOcclusion")
        .build()
        .expect("failed to create pet window")
}

/// Create and show the desktop pet. Used by the launcher so the pet appears
/// without depending on a button click inside the chat UI.
pub fn spawn_pet(app: &AppHandle) -> Result<(), String> {
    let window = ensure_pet_window(app);
    // Place the pet near the main window, then clamp it to the current monitor.
    // A maximized main window can otherwise put the pet outside the right edge.
    if let Some(main) = app.get_webview_window("main") {
        if let Ok(pos) = main.outer_position() {
            let width = main.outer_size().map(|s| s.width as i32).unwrap_or(1180);
            let pet_size = window
                .outer_size()
                .unwrap_or(tauri::PhysicalSize::new(170, 190));
            let mut x = pos.x + width + 16;
            let mut y = pos.y + 40;
            if let Ok(Some(monitor)) = window.current_monitor() {
                let monitor_pos = monitor.position();
                let monitor_size = monitor.size();
                let min_x = monitor_pos.x;
                let min_y = monitor_pos.y;
                let max_x = min_x + monitor_size.width as i32 - pet_size.width as i32;
                let max_y = min_y + monitor_size.height as i32 - pet_size.height as i32;
                x = x.clamp(min_x, max_x.max(min_x));
                y = y.clamp(min_y, max_y.max(min_y));
            }
            let _ = window.set_position(tauri::PhysicalPosition::new(x, y));
        }
    }
    window.show().map_err(|e| e.to_string())?;
    let _ = window.set_focus();
    Ok(())
}

#[tauri::command]
pub fn pet_set_context(app: AppHandle, payload: Value) -> Result<(), String> {
    let state = app.state::<PetState>();
    *state.0.lock().map_err(|_| "pet state lock poisoned".to_string())? =
        Some(payload.clone());
    // Forward to the pet window (no-op if it is not open yet).
    let _ = app.emit_to(PET_LABEL, "xy:pet-context", payload);
    Ok(())
}

#[tauri::command]
pub fn pet_get_context(app: AppHandle) -> Result<Option<Value>, String> {
    let state = app.state::<PetState>();
    let guard = state
        .0
        .lock()
        .map_err(|_| "pet state lock poisoned".to_string())?;
    Ok(guard.clone())
}

#[tauri::command]
pub fn character_lift(app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    let window = ensure_pet_window(&app);
    if x.is_finite() && y.is_finite() {
        // Position is best-effort; a fractional/logical mismatch must not fail the lift.
        let _ = window.set_position(tauri::LogicalPosition::new(x, y));
    }
    window.show().map_err(|e| e.to_string())?;
    // Focus is best-effort on always-on-top / skip-taskbar windows.
    let _ = window.set_focus();
    Ok(())
}

#[tauri::command]
pub fn character_move(app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    if let Some(window) = pet_window(&app) {
        if x.is_finite() && y.is_finite() {
            window
                .set_position(tauri::LogicalPosition::new(x, y))
                .map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

#[tauri::command]
pub fn character_drop_on_island(app: AppHandle) -> Result<(), String> {
    if let Some(window) = pet_window(&app) {
        window.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn pet_close(app: AppHandle) -> Result<(), String> {
    if let Some(window) = pet_window(&app) {
        window.close().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn character_drop_elsewhere(_app: AppHandle) -> Result<(), String> {
    // Keep the pet on the desktop; nothing to do.
    Ok(())
}
