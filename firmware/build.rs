use std::hash::DefaultHasher;
use std::hash::Hash;
use std::hash::Hasher;
use std::path::Path;
use std::path::PathBuf;

use chrono::DateTime;
use chrono::Utc;

fn main() {
    generate_wifi_credentials();
    generate_build_epoch();
    generate_firmware_id();
    linker_be_nice();
    println!("cargo:rustc-link-arg=-Tdefmt.x");
    // make sure linkall.x is the last linker script (otherwise might cause problems with flip-link)
    println!("cargo:rustc-link-arg=-Tlinkall.x");
}

fn linker_be_nice() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        let kind = &args[1];
        let what = &args[2];

        match kind.as_str() {
            "undefined-symbol" => match what.as_str() {
                what if what.starts_with("_defmt_") => {
                    eprintln!();
                    eprintln!(
                        "💡 `defmt` not found - make sure `defmt.x` is added as a linker script and you have included `use defmt_rtt as _;`"
                    );
                    eprintln!();
                }
                "_stack_start" => {
                    eprintln!();
                    eprintln!("💡 Is the linker script `linkall.x` missing?");
                    eprintln!();
                }
                what if what.starts_with("esp_rtos_") => {
                    eprintln!();
                    eprintln!(
                        "💡 `esp-radio` has no scheduler enabled. Make sure you have initialized `esp-rtos` or provided an external scheduler."
                    );
                    eprintln!();
                }
                "embedded_test_linker_file_not_added_to_rustflags" => {
                    eprintln!();
                    eprintln!(
                        "💡 `embedded-test` not found - make sure `embedded-test.x` is added as a linker script for tests"
                    );
                    eprintln!();
                }
                "free"
                | "malloc"
                | "calloc"
                | "get_free_internal_heap_size"
                | "malloc_internal"
                | "realloc_internal"
                | "calloc_internal"
                | "free_internal" => {
                    eprintln!();
                    eprintln!(
                        "💡 Did you forget the `esp-alloc` dependency or didn't enable the `compat` feature on it?"
                    );
                    eprintln!();
                }
                _ => (),
            },
            // we don't have anything helpful for "missing-lib" yet
            _ => {
                std::process::exit(1);
            }
        }

        std::process::exit(0);
    }

    println!(
        "cargo:rustc-link-arg=-Wl,--error-handling-script={}",
        std::env::current_exe().unwrap().display()
    );
}

fn generate_wifi_credentials() {
    let path =
        PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap()).join("wifi_credentials.txt");
    println!("cargo:rerun-if-changed={}", path.display());

    let text = std::fs::read_to_string(&path).unwrap_or_else(|_| {
        panic!(
            "{} not found - copy wifi_credentials.default.txt to it and fill it in",
            path.display()
        )
    });

    let mut entries = String::new();
    let mut count = 0;
    for (n, raw) in text.lines().enumerate() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let (ssid, password) = line
            .split_once(':')
            .unwrap_or_else(|| panic!("{}:{}: expected SSID:PASSWORD", path.display(), n + 1));
        assert!(
            !ssid.is_empty() && ssid.len() <= 32,
            "{}:{}: SSID must be 1-32 bytes",
            path.display(),
            n + 1
        );
        assert!(
            password.len() <= 64,
            "{}:{}: password must be <= 64 bytes",
            path.display(),
            n + 1
        );
        // {:?} on a &str emits a correctly-escaped Rust string literal.
        entries.push_str(&format!("    ({ssid:?}, {password:?}),\n"));
        count += 1;
    }
    assert!(count > 0, "{} contains no credentials", path.display());

    let out = PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("wifi_credentials.rs");
    std::fs::write(
        out,
        format!("pub static WIFI_CREDENTIALS: &[(&str, &str)] = &[\n{entries}];\n"),
    )
    .unwrap();
}

fn generate_build_epoch() {
    use std::time::{SystemTime, UNIX_EPOCH};

    println!("cargo:rerun-if-env-changed=SOURCE_DATE_EPOCH");

    let secs: u64 = match std::env::var("SOURCE_DATE_EPOCH") {
        Ok(v) => v.parse().expect("SOURCE_DATE_EPOCH must be an integer"),
        Err(_) => SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("build clock is before the unix epoch")
            .as_secs(),
    };

    assert!(
        secs > 1_735_689_600,
        "build clock reads before 2025-01-01; the NTP era pivot would be wrong"
    );

    let out = PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("build_epoch.rs");
    std::fs::write(out, format!("pub const BUILD_EPOCH_SECS: u64 = {secs};\n")).unwrap();

    let stamp = DateTime::<Utc>::from_timestamp(secs as i64, 0).expect("build epoch out of range");
    println!(
        "cargo:rustc-env=NIXIE_BUILD_DATE={}",
        stamp.format("%Y-%m-%d")
    );
    println!(
        "cargo:rustc-env=NIXIE_BUILD_TIME={}",
        stamp.format("%H:%M:%S")
    );
    println!(
        "cargo:rustc-env=NIXIE_BUILD_TIMESTAMP={}",
        stamp.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
    );
}

fn generate_firmware_id() {
    fn collect_files(path: &Path, files: &mut Vec<PathBuf>) {
        if path.is_dir() {
            for entry in std::fs::read_dir(path).unwrap() {
                collect_files(&entry.unwrap().path(), files);
            }
        } else {
            files.push(path.to_path_buf());
        }
    }

    let root = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());
    let inputs = [
        root.join("src"),
        root.join("../wire/src"),
        root.join("../wire/Cargo.toml"),
        root.join("Cargo.toml"),
        root.join("Cargo.lock"),
        root.join("build.rs"),
        root.join(".cargo/config.toml"),
        root.join("rust-toolchain.toml"),
    ];

    let mut files = Vec::new();
    for input in &inputs {
        assert!(input.exists(), "{} missing", input.display());
        println!("cargo:rerun-if-changed={}", input.display());
        collect_files(input, &mut files);
    }
    files.sort();

    let repo = root.parent().unwrap();
    let mut hasher = DefaultHasher::new();
    for path in &files {
        let rel_path = path
            .strip_prefix(repo)
            .unwrap()
            .to_string_lossy()
            .replace("\\", "/");
        rel_path.hash(&mut hasher);
        std::fs::read(path).unwrap().hash(&mut hasher);
    }
    println!("cargo:rerun-if-env-changed=DEFMT_LOG");
    std::env::var("DEFMT_LOG")
        .unwrap_or_default()
        .hash(&mut hasher);
    std::env::var("PROFILE").unwrap().hash(&mut hasher);

    let id = format!(
        "{}+{:016x}",
        std::env::var("CARGO_PKG_VERSION").unwrap(),
        hasher.finish()
    );
    assert!(
        id.len() <= 31,
        "firmware id `{id}` does not fit the 32-byte descriptor field"
    );
    println!("cargo:rustc-env=NIXIE_FIRMWARE_ID={id}");
}
