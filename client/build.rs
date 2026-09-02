use std::path::PathBuf;

fn main() {
    println!("cargo:rerun-if-env-changed=NIXIE_ELF");
    let elf = std::env::var("NIXIE_ELF")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap())
                .join("../firmware/target/xtensa-esp32s3-none-elf/release/nixie-clock")
        });
    let elf = elf.canonicalize().unwrap_or_else(|e| {
        panic!(
            "firmware ELF not found at {} ({e}); build the firmware first or set NIXIE_ELF",
            elf.display()
        )
    });
    println!("cargo:rerun-if-changed={}", elf.display());
    println!("cargo:rustc-env=NIXIE_ELF_PATH={}", elf.display());
}
