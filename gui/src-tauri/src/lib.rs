use std::collections::HashSet;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};

mod pet;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[cfg(windows)]
static INSTANCE_MUTEX_HANDLE: OnceLock<usize> = OnceLock::new();

#[cfg(windows)]
fn acquire_single_instance() -> bool {
	use std::ffi::c_void;
	use std::ptr::null_mut;

	#[link(name = "kernel32")]
	unsafe extern "system" {
		fn CreateMutexW(
			attributes: *mut c_void,
			initial_owner: i32,
			name: *const u16,
		) -> *mut c_void;
		fn GetLastError() -> u32;
		fn CloseHandle(handle: *mut c_void) -> i32;
	}

	const ERROR_ALREADY_EXISTS: u32 = 183;
	let name: Vec<u16> = "Local\\XEYO.Agent.SingleInstance\0".encode_utf16().collect();
	let handle = unsafe { CreateMutexW(null_mut(), 1, name.as_ptr()) };
	if handle.is_null() {
		return false;
	}
	if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
		unsafe {
			let _ = CloseHandle(handle);
		}
		return false;
	}

	// Keep the mutex handle open until process exit. Windows releases it with
	// the process, so a later launch can recover after a crash.
	let _ = INSTANCE_MUTEX_HANDLE.set(handle as usize);
	true
}

#[cfg(not(windows))]
fn acquire_single_instance() -> bool {
	true
}

struct PythonChild(Mutex<Option<Child>>);

fn python_root(app: &AppHandle) -> PathBuf {
	let repo_python = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../python");

	// 开发：<repo>/python；生产优先使用打包资源，源码仓库中的 release
	// 运行时回退到 <repo>/python（本地 release 未必包含 resources/python）。
	if cfg!(debug_assertions) {
		return repo_python;
	}

	if let Ok(resource_dir) = app.path().resource_dir() {
		let bundled_python = resource_dir.join("python");
		if bundled_python.exists() {
			return bundled_python;
		}
	}

	if repo_python.exists() {
		repo_python
	} else {
		PathBuf::from("python")
	}
}

/// T30：后端端口文件路径（与 python/server/portfile.py 同一真相：
/// <python_root>/../.xeyo/backend_port，可用 XEYO_PORT_FILE 覆盖）。
fn backend_port_file_path() -> Option<PathBuf> {
	if let Ok(override_path) = std::env::var("XEYO_PORT_FILE") {
		let p = PathBuf::from(override_path);
		if !p.as_os_str().is_empty() {
			return Some(p);
		}
	}
	let py_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../python");
	let base = if py_root.exists() {
		py_root
	} else {
		PathBuf::from("python")
	};
	Some(base.parent()?.join(".xeyo").join("backend_port"))
}

/// 极简 JSON 整数提取（避免引 serde）：找 `"key": N`。
fn extract_json_int(text: &str, key: &str) -> Option<i64> {
	let marker = format!("\"{key}\"");
	let idx = text.find(&marker)?;
	let rest = &text[idx + marker.len()..];
	let colon = rest.find(':')?;
	let tail = rest[colon + 1..].trim_start();
	let negative = tail.starts_with('-');
	let digits: String = tail
		.trim_start_matches('-')
		.chars()
		.take_while(|c| c.is_ascii_digit())
		.collect();
	if digits.is_empty() {
		return None;
	}
	let n: i64 = digits.parse().ok()?;
	Some(if negative { -n } else { n })
}

/// 读端口文件：JSON {port, pid, ...} 优先，兼容旧「纯数字」格式（旧格式无 pid）。
fn read_backend_port_file() -> Option<(u16, Option<u32>)> {
	let path = backend_port_file_path()?;
	let text = std::fs::read_to_string(path).ok()?;
	let trimmed = text.trim();
	if trimmed.is_empty() {
		return None;
	}
	if trimmed.starts_with('{') {
		let port = extract_json_int(trimmed, "port")?;
		if !(1..=65535).contains(&port) {
			return None;
		}
		let pid = extract_json_int(trimmed, "pid").filter(|p| *p > 0).map(|p| p as u32);
		Some((port as u16, pid))
	} else {
		trimmed.parse::<u16>().ok().map(|p| (p, None))
	}
}

/// 后端实际端口：端口文件 > 8000。
fn backend_port() -> u16 {
	read_backend_port_file()
		.map(|(p, _)| p)
		.unwrap_or(8000)
}

/// 前端向壳查询后端实时端口（读端口文件），用于守护 respawn / 端口迁移后同步。
#[tauri::command]
fn get_backend_port() -> u16 {
	backend_port()
}

/// 进程是否存活（只探测，不下手杀）。
fn process_alive(pid: u32) -> bool {
	#[cfg(windows)]
	{
		let out = Command::new("tasklist")
			.args(["/FI", &format!("PID eq {pid}"), "/NH", "/FO", "CSV"])
			.creation_flags(CREATE_NO_WINDOW)
			.output();
		match out {
			Ok(o) if o.status.success() => {
				String::from_utf8_lossy(&o.stdout).contains(&pid.to_string())
			}
			_ => false,
		}
	}
	#[cfg(not(windows))]
	{
		Command::new("kill")
			.args(["-0", &pid.to_string()])
			.output()
			.map(|o| o.status.success())
			.unwrap_or(false)
	}
}

/// T30：僵尸端口文件清理——pid 不存在即删文件；活实例保留（健康检查决定复用）。
/// 不再「杀配置端口上的一切」：netstat 字符串匹配会误伤无关进程。
fn cleanup_stale_backend() {
	let Some((_, Some(pid))) = read_backend_port_file() else {
		return;
	};
	if process_alive(pid) {
		return;
	}
	if let Some(path) = backend_port_file_path() {
		let _ = std::fs::remove_file(path);
	}
}

fn kill_python_tree(child: &mut Child) {
	#[cfg(windows)]
	{
		let pid = child.id().to_string();
		let _ = Command::new("taskkill")
			.args(["/PID", &pid, "/T", "/F"])
			.creation_flags(CREATE_NO_WINDOW)
			.status();
	}
	#[cfg(not(windows))]
	{
		let _ = child.kill();
	}
	let _ = child.wait();
}

/// 按 pid 收后端进程树（守护重启时旧 pid 可能已无 Child 句柄，只能用 pid 杀）。
fn kill_pid_tree(pid: u32) {
	#[cfg(windows)]
	{
		let _ = Command::new("taskkill")
			.args(["/PID", &pid.to_string(), "/T", "/F"])
			.creation_flags(CREATE_NO_WINDOW)
			.status();
	}
	#[cfg(not(windows))]
	{
		let _ = Command::new("kill")
			.args(["-KILL", &pid.to_string()])
			.status();
	}
}

// 守护参数：探测间隔 / 冷启动宽限 / 持续不健康才强杀（秒）。
const SUPERVISE_INTERVAL_S: u64 = 10;
const SUPERVISE_STARTUP_GRACE_S: u64 = 20;
const SUPERVISE_KILL_AFTER_UNHEALTHY_S: u64 = 30;

// 共享「最近一次 spawn」时刻：setup 初始 spawn 与守护 respawn 都记录，
// 守护读它判断冷启动宽限，避免初始 spawn 不计入宽限而被误杀。
type SharedSpawnMark = Arc<Mutex<Option<Instant>>>;

fn record_spawn(mark: &SharedSpawnMark) {
	if let Ok(mut g) = mark.lock() {
		*g = Some(Instant::now());
	}
}

fn spawn_within_grace(mark: &SharedSpawnMark) -> bool {
	if let Ok(g) = mark.lock() {
		if let Some(t) = *g {
			if t.elapsed() < Duration::from_secs(SUPERVISE_STARTUP_GRACE_S) {
				return true;
			}
		}
	}
	false
}

/// G125：解释器可用性探测——文件存在不等于能跑。
///
/// 历史事故（MSI 装完连不上后端）：`resources/python/.venv` 曾由 `virtualenv`
/// 产出，是**薄壳**——`Scripts/python.exe` 只是 ~270KB 的 launcher，真正的
/// `python3xx.dll` 与标准库留在构建机的 base 解释器里（pyvenv.cfg 的 `home=`
/// 指向 `C:\Users\<someone>\...`）。发布包装到没装该版本 Python 的机器上时，
/// 文件俱在但启动即失败，`is_file()` 完全挡不住，`spawn_python` 只把错误写进
/// stderr，GUI 无任何提示，用户只能看到"无法连接后端"。
///
/// 这里用一次真实 import 探测把"存在但不可用"的解释器筛掉。
fn python_exe_usable(exe: &Path) -> bool {
	if !exe.is_file() {
		return false;
	}
	let mut cmd = Command::new(exe);
	cmd.args(["-c", "import sys; sys.stdout.write(sys.version_info[:2].__str__())"])
		.stdout(Stdio::piped())
		.stderr(Stdio::null())
		.stdin(Stdio::null());
	#[cfg(windows)]
	{
		cmd.creation_flags(CREATE_NO_WINDOW);
	}
	match cmd.output() {
		Ok(out) => out.status.success(),
		Err(_) => false,
	}
}

fn resolve_python_exe(root: &Path) -> Result<PathBuf, String> {
	if let Ok(override_py) = std::env::var("XEYO_PYTHON") {
		let trimmed = override_py.trim();
		if !trimmed.is_empty() {
			let p = PathBuf::from(trimmed);
			if python_exe_usable(&p) {
				return Ok(p);
			}
			return Err(format!(
				"XEYO_PYTHON 指定的解释器无法运行: {}",
				p.display()
			));
		}
	}
	#[cfg(windows)]
	let venv = root.join(".venv").join("Scripts").join("python.exe");
	#[cfg(not(windows))]
	let venv = root.join(".venv").join("bin").join("python");
	if venv.is_file() {
		if python_exe_usable(&venv) {
			return Ok(venv);
		}
		// 产物残缺：明确报错，不要静默换解释器——换掉会让用户用错环境跑后端。
		return Err(format!(
			"内嵌 Python 不可用（可能是薄壳 venv，缺少 python3xx.dll / 标准库）: {}",
			venv.display()
		));
	}
	#[cfg(windows)]
	{
		let probe = Command::new("py")
			.args(["-3.11", "-c", "import sys; print(sys.executable)"])
			.stdout(Stdio::piped())
			.stderr(Stdio::null())
			.stdin(Stdio::null())
			.creation_flags(CREATE_NO_WINDOW)
			.output();
		if let Ok(out) = probe {
			if out.status.success() {
				let p = String::from_utf8_lossy(&out.stdout).trim().to_string();
				if !p.is_empty() {
					let candidate = PathBuf::from(p);
					if python_exe_usable(&candidate) {
						return Ok(candidate);
					}
				}
			}
		}
		let fallback = PathBuf::from("python");
		if python_exe_usable(&fallback) {
			return Ok(fallback);
		}
		Err(format!(
			"未找到可用的 Python 解释器：{} 缺失或不可用，且系统未安装 Python 3.11",
			venv.display()
		))
	}
	#[cfg(not(windows))]
	{
		let fallback = PathBuf::from("python3");
		if python_exe_usable(&fallback) {
			return Ok(fallback);
		}
		Err(format!(
			"未找到可用的 Python 解释器：{} 缺失或不可用",
			venv.display()
		))
	}
}

/// 最近一次后端启动失败的原因：GUI 可查询并展示，用户不必去翻 stderr。
/// （历史事故：spawn 失败只 eprintln，界面只说"无法连接后端"，用户完全不知道
/// 是内嵌 Python 坏了，只能猜是端口/网络问题。）
static BACKEND_SPAWN_ERROR: OnceLock<Mutex<Option<String>>> = OnceLock::new();

fn spawn_error_slot() -> &'static Mutex<Option<String>> {
	BACKEND_SPAWN_ERROR.get_or_init(|| Mutex::new(None))
}

fn record_spawn_error(msg: &str) {
	if let Ok(mut g) = spawn_error_slot().lock() {
		*g = Some(msg.to_string());
	}
	eprintln!("[xeyo] backend spawn failed: {msg}");
}

#[tauri::command]
fn get_backend_error() -> Option<String> {
	spawn_error_slot().lock().ok().and_then(|g| g.clone())
}

#[tauri::command]
fn clear_backend_error() {
	if let Ok(mut g) = spawn_error_slot().lock() {
		*g = None;
	}
}

fn spawn_python(app: &AppHandle) -> Result<Child, String> {
	let root = python_root(app);
	if !root.exists() {
		let msg = format!("python root not found: {}", root.display());
		record_spawn_error(&msg);
		return Err(msg);
	}

	cleanup_stale_backend();

	let py = match resolve_python_exe(&root) {
		Ok(p) => p,
		Err(e) => {
			record_spawn_error(&e);
			return Err(e);
		}
	};
	let mut cmd = Command::new(&py);
	cmd.args(["-u", "-m", "server"])
		.current_dir(&root)
		.env("PYTHONUNBUFFERED", "1")
		.env("PYTHONIOENCODING", "utf-8")
		.env("XEYO_HTTP_HOST", "127.0.0.1")
		.env("XEYO_HTTP_PORT", "8000")
		.env_remove("XEYO_CWD")
		.env(
			"XEYO_REWIND_ENABLED",
			std::env::var("XEYO_REWIND_ENABLED").unwrap_or_else(|_| "1".into()),
		)
		// 开发默认开 C2 灰度；可用环境变量 XEYO_C2_GATE=0 关掉
		.env(
			"XEYO_C2_GATE",
			std::env::var("XEYO_C2_GATE").unwrap_or_else(|_| "1".into()),
		)
		.stdout(Stdio::piped())
		.stderr(Stdio::piped());

	#[cfg(windows)]
	{
		cmd.creation_flags(CREATE_NO_WINDOW);
	}

	let mut child = cmd.spawn().map_err(|e| {
		let msg = format!("spawn python failed ({}): {e}", py.display());
		record_spawn_error(&msg);
		msg
	})?;

	if let Some(stdout) = child.stdout.take() {
		thread::spawn(move || {
			let mut reader = BufReader::new(stdout);
			let mut buf = String::new();
			while reader.read_line(&mut buf).unwrap_or(0) > 0 {
				buf.clear();
			}
		});
	}
	if let Some(stderr) = child.stderr.take() {
		thread::spawn(move || {
			let reader = BufReader::new(stderr);
			for line in reader.lines().flatten() {
				let lower = line.to_ascii_lowercase();
				if lower.contains("error") || lower.contains("traceback") {
					eprintln!("[python:err] {line}");
				}
			}
		});
	}

	Ok(child)
}

fn wait_health(timeout: Duration) -> bool {
	let start = Instant::now();
	while start.elapsed() < timeout {
		// G124: 只信"端口文件登记的 pid 仍存活"时的 200——本机任意进程占住端口
		// 回 200 不再能接管 GUI 流量(端口文件 pid 会随后端死亡失效)。
		let recorded_pid = read_backend_port_file().and_then(|(_port, pid)| pid);
		let port = backend_port();
		if let Some(pid) = recorded_pid {
			if !process_alive(pid) {
				thread::sleep(Duration::from_millis(400));
				continue;
			}
		} else {
			// 旧格式端口文件无 pid：不认健康，避免被陌生人 200 骗。
			thread::sleep(Duration::from_millis(400));
			continue;
		}
		if let Ok(resp) = ureq_get(&format!("http://127.0.0.1:{port}/health")) {
			if resp {
				return true;
			}
		}
		thread::sleep(Duration::from_millis(400));
	}
	false
}

#[tauri::command]
fn save_text_file(path: String, text: String) -> Result<(), String> {
	let destination = PathBuf::from(path.trim());
	if destination.as_os_str().is_empty() {
		return Err("保存路径不能为空".to_string());
	}
	std::fs::write(&destination, text.as_bytes())
		.map_err(|err| format!("保存文件失败（{}）：{err}", destination.display()))
}

/// 在系统资源管理器中定位文件/目录（Windows explorer /select，macOS open -R）。
#[tauri::command]
fn reveal_in_folder(path: String) -> Result<(), String> {
	let target = PathBuf::from(path.trim());
	if target.as_os_str().is_empty() {
		return Err("路径不能为空".to_string());
	}
	#[cfg(target_os = "windows")]
	{
		use std::os::windows::process::CommandExt;
		const CREATE_NO_WINDOW: u32 = 0x0800_0000;
		// explorer 需要 /select,"path" 形式；路径含空格时必须带引号
		let path_str = target.to_string_lossy();
		let select_arg = format!("/select,\"{path_str}\"");
		std::process::Command::new("explorer")
			.raw_arg(&select_arg)
			.creation_flags(CREATE_NO_WINDOW)
			.spawn()
			.map_err(|err| format!("无法在资源管理器中显示：{err}"))?;
		return Ok(());
	}
	#[cfg(target_os = "macos")]
	{
		std::process::Command::new("open")
			.arg("-R")
			.arg(&target)
			.spawn()
			.map_err(|err| format!("无法在 Finder 中显示：{err}"))?;
		return Ok(());
	}
	#[cfg(not(any(target_os = "windows", target_os = "macos")))]
	{
		let dir = if target.is_dir() {
			target.clone()
		} else {
			target
				.parent()
				.map(PathBuf::from)
				.unwrap_or_else(|| PathBuf::from("."))
		};
		std::process::Command::new("xdg-open")
			.arg(&dir)
			.spawn()
			.map_err(|err| format!("无法打开文件管理器：{err}"))?;
		Ok(())
	}
}

fn abs_path(path: &str) -> Result<PathBuf, String> {
	let trimmed = path.trim();
	if trimmed.is_empty() {
		return Err("路径不能为空".to_string());
	}
	let dest = PathBuf::from(trimmed);
	if !dest.is_absolute() {
		return Err("路径必须是绝对路径".to_string());
	}
	Ok(dest)
}

fn run_git(args: &[&str]) -> Result<(), String> {
	let mut cmd = Command::new("git");
	cmd.args(args).stdout(Stdio::piped()).stderr(Stdio::piped());
	#[cfg(windows)]
	{
		cmd.creation_flags(CREATE_NO_WINDOW);
	}
	let output = cmd
		.output()
		.map_err(|err| format!("无法运行 git：{err}"))?;
	if output.status.success() {
		return Ok(());
	}
	let stderr = String::from_utf8_lossy(&output.stderr);
	let stdout = String::from_utf8_lossy(&output.stdout);
	let detail = stderr.trim();
	let fallback = stdout.trim();
	if !detail.is_empty() {
		Err(detail.to_string())
	} else if !fallback.is_empty() {
		Err(fallback.to_string())
	} else {
		Err("git 命令失败".to_string())
	}
}

#[tauri::command]
fn create_directory(path: String) -> Result<(), String> {
	let dest = abs_path(&path)?;
	if dest.exists() {
		return Err(format!("文件夹已存在（{}）", dest.display()));
	}
	std::fs::create_dir_all(&dest)
		.map_err(|err| format!("创建文件夹失败（{}）：{err}", dest.display()))
}

#[tauri::command]
fn git_init(path: String) -> Result<(), String> {
	let dest = abs_path(&path)?;
	let dest_str = dest.to_str().ok_or("路径无效")?;
	run_git(&["-C", dest_str, "init"])
}

#[tauri::command]
async fn git_clone(url: String, dest: String) -> Result<(), String> {
	let url = url.trim().to_string();
	if url.is_empty() {
		return Err("仓库地址不能为空".to_string());
	}
	let dest = abs_path(&dest)?;
	let dest_str = dest.to_str().ok_or("路径无效")?.to_string();
	tauri::async_runtime::spawn_blocking(move || {
		run_git(&["clone", "--", url.as_str(), dest_str.as_str()])
	})
	.await
	.map_err(|err| format!("克隆任务失败：{err}"))?
}

fn skip_dir_name(name: &str) -> bool {
	matches!(
		name,
		"node_modules" | "dist" | "target" | "__pycache__" | ".venv" | "venv" | ".git"
	)
}

fn scan_git_repos(root: &Path, depth: u32, out: &mut Vec<String>, seen: &mut HashSet<String>) {
	const MAX: usize = 40;
	if out.len() >= MAX || depth > 2 {
		return;
	}
	if root.join(".git").exists() {
		if let Some(s) = root.to_str() {
			if seen.insert(s.to_string()) {
				out.push(s.to_string());
			}
		}
		return;
	}
	if depth == 2 {
		return;
	}
	let entries = match std::fs::read_dir(root) {
		Ok(e) => e,
		Err(_) => return,
	};
	for entry in entries.flatten() {
		if out.len() >= MAX {
			return;
		}
		let path = entry.path();
		if !path.is_dir() {
			continue;
		}
		let name = entry.file_name();
		let name = name.to_string_lossy();
		if skip_dir_name(&name) {
			continue;
		}
		scan_git_repos(&path, depth + 1, out, seen);
	}
}

#[tauri::command]
fn list_git_repos(roots: Vec<String>) -> Result<Vec<String>, String> {
	let mut out = Vec::new();
	let mut seen = HashSet::new();
	for root in roots {
		let Ok(path) = abs_path(&root) else {
			continue;
		};
		scan_git_repos(&path, 0, &mut out, &mut seen);
	}
	Ok(out)
}

fn ureq_get(url: &str) -> Result<bool, ()> {
	// 仅用标准库的轻量 HTTP GET（TcpStream）；不引入 reqwest。
	use std::io::{Read, Write};
	use std::net::TcpStream;

	let authority = url
		.strip_prefix("http://")
		.ok_or(())?
		.split('/')
		.next()
		.ok_or(())?
		.to_string();

	let mut stream = TcpStream::connect_timeout(
		&authority.parse().map_err(|_| ())?,
		Duration::from_millis(500),
	)
	.map_err(|_| ())?;
	stream
		.set_read_timeout(Some(Duration::from_millis(800)))
		.ok();
	let req = format!("GET /health HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\n\r\n");
	stream.write_all(req.as_bytes()).map_err(|_| ())?;
	let mut buf = String::new();
	stream.read_to_string(&mut buf).ok();
	Ok(buf.contains("200") || buf.contains("\"ok\""))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
	if !acquire_single_instance() {
		return;
	}

	tauri::Builder::default()

		.plugin(tauri_plugin_shell::init())
		.plugin(tauri_plugin_dialog::init())
		.manage(PythonChild(Mutex::new(None)))
		.manage(pet::PetState(Mutex::new(None)))
		.invoke_handler(tauri::generate_handler![
			pet::pet_set_context,
			pet::pet_get_context,
			pet::character_lift,
			pet::character_move,
				pet::character_drop_on_island,
				pet::pet_close,
					pet::character_drop_elsewhere,
				save_text_file,
				reveal_in_folder,
				create_directory,
				git_init,
				git_clone,
				list_git_repos,
				get_backend_port,
				get_backend_error,
				clear_backend_error
			])
.setup(|app| {
				// 透明窗口不支持 DWM 阴影（layered 窗口），不再强制开渲染阴影，
				// 否则会覆盖 tauri.conf.json 的 shadow:false，导致 WebView 用不透明底色。
					// XeyoPet is docked in the main sidebar by default. The native
					// window is created lazily when the user long-presses to extract it.

			// 幂等启动后端：若 :8000 已有健康后端（例如由 XEYO.bat 先启动），
			// 就不再拉起第二个 `-m server`，避免双后端抢 8000 端口导致 GUI 间歇性“重启”。
			let spawn_mark = Arc::new(Mutex::new(None::<Instant>));
			if !wait_health(Duration::from_secs(3)) {
				match spawn_python(app.handle()) {
					Ok(child) => {
						*app.state::<PythonChild>().0.lock().unwrap() = Some(child);
						record_spawn(&spawn_mark);
						if !wait_health(Duration::from_secs(25)) {
							record_spawn_error(
								"后端进程已启动但健康检查超时（25s 内 /health 未就绪）",
							);
						} else {
							clear_backend_error();
						}
					}
					Err(err) => {
						// spawn_python 内部已记录到 BACKEND_SPAWN_ERROR
						eprintln!("failed to start python backend: {err}");
					}
				}
			}

			// Fallback: the frontend shows the main window after its first
			// frame; if that never happens (e.g. JS error), reveal it here so
			// the window cannot stay invisible forever.
			let handle = app.handle().clone();
			tauri::async_runtime::spawn(async move {
				thread::sleep(Duration::from_secs(4));
				if let Some(window) = handle.get_webview_window("main") {
					if !window.is_visible().unwrap_or(true) {
						let _ = window.show();
					}
				}
			});

			// 守护后端：setup 只 spawn 一次，之后靠本线程周期探测。后端长跑崩溃/挂起
			// 则杀树并重新拉起，否则 GUI 永远连不上、只能人工重开（本 Bug 根因）。
			{
				let app_handle = app.handle().clone();
				let spawn_mark = spawn_mark.clone();
				thread::spawn(move || {
					let mut consecutive_unhealthy: u32 = 0;
					loop {
						thread::sleep(Duration::from_secs(SUPERVISE_INTERVAL_S));
						let port = backend_port();
						let healthy = wait_health(Duration::from_secs(2));
						if healthy {
							consecutive_unhealthy = 0;
							continue;
						}
						consecutive_unhealthy += 1;
						// 刚 spawn 过（< 冷启动宽限）说明是冷启动期，别急着再杀。
						// setup 初始 spawn 与守护 respawn 都计入宽限（共享 spawn_mark）。
						if spawn_within_grace(&spawn_mark) {
							continue;
						}
						// 默认 3 次（30s）不健康才动；给后端留恢复窗口，避免抖动误杀。
						let kill_after = (SUPERVISE_KILL_AFTER_UNHEALTHY_S / SUPERVISE_INTERVAL_S) as u32;
						if consecutive_unhealthy < kill_after {
							continue;
						}
						// 旧进程按 pid 收树（可能已无 Child 句柄）。
						if let Some((_, pid)) = read_backend_port_file() {
							if let Some(p) = pid {
								kill_pid_tree(p);
							}
						}
						cleanup_stale_backend();
						// 复用已有 Child（若被 Tauri 持有）优先，避免孤儿进程叠加。
						let child = match app_handle.state::<PythonChild>().0.lock() {
							Ok(mut guard) => guard.take(),
							Err(_) => None,
						};
						if let Some(mut c) = child {
							kill_python_tree(&mut c);
						}
						match spawn_python(&app_handle) {
							Ok(child) => {
								if let Ok(mut guard) = app_handle.state::<PythonChild>().0.lock() {
									*guard = Some(child);
								}
								// 不阻塞等健康：record 宽限后立即进入下一轮循环，
								// 由后续 10s 探测确认；避免 25s 阻塞抢占守护调度。
								record_spawn(&spawn_mark);
								consecutive_unhealthy = 0;
								eprintln!(
									"[xeyo:supervisor] backend respawned on :{port} (awaiting health)"
								);
							}
							Err(err) => eprintln!("[xeyo:supervisor] respawn failed: {err}"),
						}
					}
				});
			}

				Ok(())
			})
			.on_window_event(|window, event| {
				if window.label() == "main" && matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
					if let Some(pet) = window.app_handle().get_webview_window("pet") {
						let _ = pet.close();
					}
				}
			})
			.build(tauri::generate_context!())
		.expect("error while building XEYO")
					.run(|app_handle, event| {
				match event {
					// The pet is an independent window, so closing the main window does
					// not automatically terminate it. Close it at the main close request.
RunEvent::WindowEvent {
							label,
							event: tauri::WindowEvent::CloseRequested { .. },
							..
						} if label == "main" => {
							if let Some(pet) = app_handle.get_webview_window("pet") {
								let _ = pet.close();
							}
						}
						RunEvent::ExitRequested { .. } | RunEvent::Exit => {
							if let Some(pet) = app_handle.get_webview_window("pet") {
								let _ = pet.close();
							}
						if let Some(state) = app_handle.try_state::<PythonChild>() {
							if let Ok(mut guard) = state.0.lock() {
								if let Some(mut child) = guard.take() {
									kill_python_tree(&mut child);
								}
							}
						}
						// T30：子进程已被 kill_python_tree 收树；这里只清僵尸端口文件。
						cleanup_stale_backend();
					}
					_ => {}
				}
			});

}
