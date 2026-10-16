use std::sync::Mutex;

/// Serialize child creation/registration with shutdown, never the health wait.
#[derive(Default)]
pub struct StartupGate(Mutex<bool>);

impl StartupGate {
    pub fn run<T>(&self, action: impl FnOnce() -> T) -> Option<T> {
        let stopped = self.0.lock().unwrap();
        if *stopped {
            None
        } else {
            Some(action())
        }
    }
    pub fn stop(&self, cleanup: impl FnOnce()) {
        let mut stopped = self.0.lock().unwrap();
        *stopped = true;
        cleanup();
    }
    pub fn is_stopped(&self) -> bool {
        *self.0.lock().unwrap()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{mpsc, Arc};
    use std::thread;

    #[test]
    fn shutdown_prevents_late_spawn() {
        let gate = StartupGate::default();
        gate.stop(|| {});
        assert_eq!(gate.run(|| 1), None);
    }

    #[test]
    fn racing_shutdown_cleans_registered_child() {
        let gate = Arc::new(StartupGate::default());
        let child = Arc::new(Mutex::new(false));
        let (entered, wait_entered) = mpsc::channel();
        let (release, wait_release) = mpsc::channel();
        let worker_gate = gate.clone();
        let worker_child = child.clone();
        let worker = thread::spawn(move || {
            worker_gate.run(|| {
                entered.send(()).unwrap();
                wait_release.recv().unwrap();
                *worker_child.lock().unwrap() = true;
            })
        });
        wait_entered.recv().unwrap();
        let stop_gate = gate.clone();
        let stop_child = child.clone();
        let stopper = thread::spawn(move || stop_gate.stop(|| *stop_child.lock().unwrap() = false));
        release.send(()).unwrap();
        worker.join().unwrap();
        stopper.join().unwrap();
        assert!(!*child.lock().unwrap());
        assert!(gate.is_stopped());
    }
}
