use crate::error::{Error, ErrorKind, Result};
use crate::policy::Workspace;
use crate::strict_json;
use rusqlite::{Connection, OptionalExtension, Transaction, params};
use std::path::Path;

pub(crate) struct LocalIdentity { principal: String }

fn denied() -> Error {
    Error::new(ErrorKind::AuthorityDenied, "local resource owner authorization is absent, revoked or differs from the current OS principal")
}

fn valid_sid(principal: &str) -> bool {
    let parts: Vec<_> = principal.split('-').collect();
    if !(4..=18).contains(&parts.len()) || parts[0] != "S" || parts[1] != "1" {
        return false;
    }
    let decimal = |part: &str| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit())
        && (part == "0" || !part.starts_with('0'));
    decimal(parts[2]) && parts[2].parse::<u64>().is_ok_and(|value| value <= 0xffff_ffff_ffff)
        && parts[3..].iter().all(|part| decimal(part) && part.parse::<u32>().is_ok())
}

#[cfg(any(windows, test))]
fn parse_whoami(bytes: &[u8]) -> Result<LocalIdentity> {
    if bytes.len() > 16384 { return Err(denied()); }
    let row = bytes.strip_suffix(b"\r\n").or_else(|| bytes.strip_suffix(b"\n")).unwrap_or(bytes);
    if row.first() != Some(&b'"') || row.iter().any(|byte| *byte < 32 || *byte == 127) {
        return Err(denied());
    }
    let mut offset = 1;
    let field_end = loop {
        match row.get(offset) {
            Some(b'"') if row.get(offset + 1) == Some(&b'"') => offset += 2,
            Some(b'"') => break offset,
            Some(_) => offset += 1,
            None => return Err(denied()),
        }
    };
    if field_end == 1 || row.get(field_end + 1..field_end + 3) != Some(b",\"".as_slice())
        || row.last() != Some(&b'"') || row.len() <= field_end + 4 {
        return Err(denied());
    }
    let principal = std::str::from_utf8(&row[field_end + 3..row.len() - 1]).map_err(|_| denied())?;
    if !valid_sid(principal) { return Err(denied()); }
    Ok(LocalIdentity { principal: principal.to_owned() })
}

#[cfg(windows)]
pub(crate) fn current() -> Result<LocalIdentity> {
    use std::os::windows::fs::MetadataExt;
    use std::os::windows::process::CommandExt;
    for path in [r"C:\Windows", r"C:\Windows\System32", r"C:\Windows\System32\whoami.exe"] {
        let metadata = std::fs::symlink_metadata(path).map_err(|_| denied())?;
        if metadata.file_attributes() & 0x400 != 0 { return Err(denied()); }
        if path.ends_with(".exe") && !metadata.is_file() { return Err(denied()); }
    }
    let output = std::process::Command::new(r"C:\Windows\System32\whoami.exe")
        .args(["/user", "/fo", "csv", "/nh"]).current_dir(r"C:\Windows\System32")
        .creation_flags(0x08000000)
        .output().map_err(|_| denied())?;
    if !output.status.success() || !output.stderr.is_empty() { return Err(denied()); }
    parse_whoami(&output.stdout)
}

#[cfg(not(windows))]
pub(crate) fn current() -> Result<LocalIdentity> {
    Err(Error::new(ErrorKind::HostUnknown, "trusted local resource identity is implemented only for Windows with the protected system whoami executable"))
}

pub(crate) fn initialize(transaction: &Transaction<'_>, workspace: &Workspace,
    scope: &str, identity: &LocalIdentity) -> Result<()> {
    let root_hash = strict_json::sha256(workspace.root().to_string_lossy().as_bytes());
    transaction.execute("INSERT INTO local_resource_acl(singleton,acl_version,owner_sid,scope,root_hash,enabled) VALUES(1,1,?1,?2,?3,1)",
        params![identity.principal,scope,root_hash])?;
    Ok(())
}

pub(crate) fn require(connection: &Connection, workspace: &Workspace, scope: &str) -> Result<()> {
    let identity = current()?;
    workspace.resolve(Path::new(".wuji4/state.sqlite"))?;
    let root_hash = strict_json::sha256(workspace.root().to_string_lossy().as_bytes());
    if scope != format!("project:{}", &root_hash[..24]) {
        return Err(Error::new(ErrorKind::ScopeDenied, "current resource workspace scope differs from its root"));
    }
    let stored: (String,String) = connection.query_row("SELECT scope,root_hash FROM workspace_meta WHERE singleton=1", [],
        |row| Ok((row.get(0)?,row.get(1)?)))?;
    if stored != (scope.to_owned(),root_hash.clone()) {
        return Err(Error::new(ErrorKind::ScopeDenied, "current resource workspace scope changed"));
    }
    let exists: bool = connection.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_resource_acl')", [], |row| row.get(0))?;
    if !exists { return Err(denied()); }
    let binding: Option<(String,String,String,i64)> = connection.query_row(
        "SELECT owner_sid,scope,root_hash,enabled FROM local_resource_acl WHERE singleton=1 AND acl_version=1", [],
        |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?))).optional().map_err(|_| denied())?;
    let (principal,bound_scope,bound_root,enabled) = binding.ok_or_else(denied)?;
    if !valid_sid(&principal) || principal != identity.principal || enabled != 1 { return Err(denied()); }
    if bound_scope != scope || bound_root != root_hash {
        return Err(Error::new(ErrorKind::ScopeDenied, "current resource owner binding belongs to another scope"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn t22_whoami_csv_accepts_only_one_valid_sid_without_trusting_username() {
        let identity = parse_whoami(b"\"arbitrary\\name\",\"S-1-5-21-1-2-3-1001\"\r\n").unwrap();
        assert_eq!(identity.principal,"S-1-5-21-1-2-3-1001");
        assert!(parse_whoami(b"\"escaped\"\"name\",\"S-1-5-18\"\n").is_ok());
        assert!(parse_whoami(b"\"\xff\xfe\",\"S-1-5-18\"\r\n").is_ok());
    }

    #[test]
    fn t22_whoami_csv_rejects_malformed_or_multiple_identities() {
        for bytes in [
            b"name,S-1-5-18".as_slice(), b"\"name\",\"administrator\"",
            b"\"name\",\"S-1-5-18\",\"extra\"", b"\"name\",\"S-1-5-18\"\n\"other\",\"S-1-5-19\"\n",
            b"\"name\",\"S-1-05-18\"", b"\"name\",\"S-1-5-4294967296\"",
            b"\"name\",\"S-1-281474976710656-18\"", b"\"name\",\"S-1-5\"", b"\"\",\"S-1-5-18\"",
        ] { assert_eq!(parse_whoami(bytes).err().unwrap().kind,ErrorKind::AuthorityDenied); }
    }
}
