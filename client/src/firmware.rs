use defmt_decoder::Locations;
use defmt_decoder::Table;

#[repr(C, align(8))]
struct Aligned<T: ?Sized>(T);

static ALIGNED: &Aligned<[u8]> = &Aligned(*include_bytes!(env!("NIXIE_ELF_PATH")));
pub static ELF: &[u8] = &ALIGNED.0;

#[derive(Debug)]
pub struct Descriptor {
    pub id: String,
    pub built: String,
}

const MAGIC: [u8; 4] = 0xABCD_5432u32.to_le_bytes();

pub fn descriptor() -> Option<Descriptor> {
    let d = ELF
        .windows(256)
        .find(|w| w[..4] == MAGIC && cstr(&w[48..80]) == Some("nixie-clock"))?;
    Some(Descriptor {
        id: cstr(&d[16..48])?.to_owned(),
        built: format!("{}T{}Z", cstr(&d[96..112])?, cstr(&d[80..96])?),
    })
}

fn cstr(field: &[u8]) -> Option<&str> {
    let end = field.iter().position(|&b| b == 0).unwrap_or(field.len());
    std::str::from_utf8(&field[..end]).ok()
}

pub fn table() -> Result<(Table, Locations), String> {
    let table = Table::parse(ELF)
        .map_err(|e| e.to_string())?
        .ok_or("embedded ELF has no .defmt section")?;
    let locations = table.get_locations(ELF).map_err(|e| e.to_string())?;
    Ok((table, locations))
}
