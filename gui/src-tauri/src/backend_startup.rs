use super::startup_gate::StartupGate;
use super::*;

#[derive(Default)]
pub struct StartupControl {
    gate: StartupGate,
    ready: Mutex<Option<Result<(), String>>>,
}

#[tauri::command]
pub fn backend_startup_ready(state: tauri::State<'_, Arc<StartupControl>>) -> Result<bool, String> {
    match state.ready.lock().unwrap().as_ref() {
        None => Ok(false),
        Some(Ok(())) => Ok(true),
        Some(Err(error)) => Err(error.clone()),
    }
}

fn spawn_and_register(app: &AppHandle, mark: &SharedSpawnMark) -> bool {
    match spawn_python(app) {
        Ok(child) => {
            *app.state::<PythonChild>().0.lock().unwrap() = Some(child);
            record_spawn(mark);
            true
        }
        Err(error) => {
            eprintln!("[xeyo] backend spawn failed: {error}");
            false
        }
    }
}

/// One worker owns bootstrap and supervision. setup returns without HTTP waits.
pub fn start(app: &AppHandle) {
    let control = Arc::new(StartupControl::default());
    app.manage(control.clone());
    let app = app.clone();
    thread::spawn(move || {
        let mark = Arc::new(Mutex::new(None::<Instant>));
        // No recorded live process means there is nothing to wait three seconds for.
        let existing = read_backend_port_file()
            .and_then(|(_, pid)| pid)
            .is_some_and(process_alive);
        let mut healthy = existing && wait_health(Duration::from_secs(3));
        if !healthy
            && control
                .gate
                .run(|| spawn_and_register(&app, &mark))
                .unwrap_or(false)
        {
            healthy = wait_health(Duration::from_secs(25));
            if !healthy {
                record_spawn_error("后端进程已启动但健康检查超时（25s 内 /health 未就绪）");
            }
        }
        if control.gate.is_stopped() {
            return;
        }
        if healthy {
            clear_backend_error();
        }
        *control.ready.lock().unwrap() = Some(if healthy {
            Ok(())
        } else {
            Err(get_backend_error().unwrap_or_else(|| "服务未能启动".to_string()))
        });
        let mut consecutive_unhealthy = 0;
        loop {
            thread::sleep(Duration::from_secs(SUPERVISE_INTERVAL_S));
            if control.gate.is_stopped() {
                return;
            }
            if wait_health(Duration::from_secs(2)) {
                consecutive_unhealthy = 0;
                clear_backend_error();
                *control.ready.lock().unwrap() = Some(Ok(()));
                continue;
            }
            consecutive_unhealthy += 1;
            if spawn_within_grace(&mark)
                || consecutive_unhealthy < SUPERVISE_KILL_AFTER_UNHEALTHY_S / SUPERVISE_INTERVAL_S
            {
                continue;
            }
            let spawned = control
                .gate
                .run(|| {
                    if let Some((_, Some(pid))) = read_backend_port_file() {
                        kill_pid_tree(pid);
                    }
                    cleanup_stale_backend();
                    if let Some(mut child) = app.state::<PythonChild>().0.lock().unwrap().take() {
                        kill_python_tree(&mut child);
                    }
                    spawn_and_register(&app, &mark)
                })
                .unwrap_or(false);
            if spawned {
                consecutive_unhealthy = 0;
                *control.ready.lock().unwrap() = None;
                eprintln!(
                    "[xeyo:supervisor] backend respawned on :{} (awaiting health)",
                    backend_port()
                );
            }
        }
    });
}

pub fn stop(app: &AppHandle) {
    let cleanup = || {
        if let Some(state) = app.try_state::<PythonChild>() {
            if let Some(mut child) = state.0.lock().unwrap().take() {
                kill_python_tree(&mut child);
            }
        }
        cleanup_stale_backend();
    };
    if let Some(control) = app.try_state::<Arc<StartupControl>>() {
        control.gate.stop(cleanup);
    } else {
        cleanup();
    }
}
