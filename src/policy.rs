use crate::error::{Error, ErrorKind, Result};
use std::fs;
use std::path::{Component, Path, PathBuf};


#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Role { Aji, Staff, Executor, Verifier }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Operation { Plan, Claim, Write, Verify, Close, Cancel, Register, Revise }

pub struct ActorContext {
    scope: String,
    role: Role,
}

impl ActorContext {
    pub(crate) fn trusted_local(scope: &str, role: Role) -> Self {
        Self { scope:scope.to_owned(),role }
    }

    pub(crate) fn id(&self) -> &'static str {
        match self.role {
            Role::Aji => "aji-local", Role::Staff => "staff-local",
            Role::Executor => "local-executor", Role::Verifier => "local-file-validator",
        }
    }

    pub(crate) fn require(&self, scope: &str, operation: Operation) -> Result<()> {
        let permitted = matches!((self.role,operation),
            (Role::Aji,Operation::Plan) | (Role::Aji,Operation::Cancel) | (Role::Aji,Operation::Register) | (Role::Aji,Operation::Revise) | (Role::Staff,Operation::Claim)
            | (Role::Executor,Operation::Write) | (Role::Executor,Operation::Close)
            | (Role::Verifier,Operation::Verify));
        if self.scope != scope { return Err(Error::new(ErrorKind::ScopeDenied,"actor context scope mismatch")); }
        if !permitted { return Err(Error::new(ErrorKind::AuthorityDenied,"role cannot perform this operation")); }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct Workspace {
    original: PathBuf,
    canonical: PathBuf,
}

impl Workspace {
    pub fn open(approved_root: &Path) -> Result<Self> {
        if !approved_root.is_absolute() || !approved_root.is_dir() {
            return Err(Error::new(ErrorKind::PathDenied, "approved workspace must be an existing absolute directory"));
        }
        let canonical = fs::canonicalize(approved_root)?;
        Ok(Self { original: approved_root.to_owned(), canonical })
    }

    pub fn root(&self) -> &Path {
        &self.canonical
    }

    pub fn resolve(&self, target: &Path) -> Result<PathBuf> {
        if fs::canonicalize(&self.original)? != self.canonical {
            return Err(Error::new(ErrorKind::PathDenied, "workspace root changed"));
        }
        if target.components().any(|component| matches!(component,Component::ParentDir)) {
            return Err(Error::new(ErrorKind::PathDenied,"parent traversal rejected before verbatim Windows path joining"));
        }
        let joined = if target.is_absolute() { target.to_owned() } else { self.canonical.join(target) };
        for component in joined.components() {
            match component {
                Component::ParentDir => return Err(Error::new(ErrorKind::PathDenied, "parent traversal rejected")),
                Component::Normal(name) => {
                    let text = name.to_str().ok_or_else(|| Error::new(ErrorKind::PathDenied, "non-Unicode path"))?;
                    let base = text.split('.').next().unwrap_or("").to_ascii_uppercase();
                    let numbered_device = base.len() == 4 && (base.starts_with("COM") || base.starts_with("LPT")) && base.as_bytes()[3].is_ascii_digit();
                    if text.contains(':') || text.ends_with('.') || text.ends_with(' ') || ["CON", "PRN", "AUX", "NUL"].contains(&base.as_str()) || numbered_device {
                        return Err(Error::new(ErrorKind::PathDenied, "unsafe path component"));
                    }
                }
                _ => {}
            }
        }
        let mut existing = joined.as_path();
        while !existing.exists() {
            existing = existing.parent().ok_or_else(|| Error::new(ErrorKind::PathDenied, "no existing parent"))?;
        }
        let actual_parent = fs::canonicalize(existing)?;
        if !actual_parent.starts_with(&self.canonical) {
            return Err(Error::new(ErrorKind::PathDenied, "resolved path outside workspace"));
        }
        if joined.exists() {
            let actual = fs::canonicalize(&joined)?;
            if !actual.starts_with(&self.canonical) { return Err(Error::new(ErrorKind::PathDenied, "link outside workspace")); }
            Ok(actual)
        } else {
            Ok(actual_parent.join(joined.strip_prefix(existing).map_err(|_| Error::new(ErrorKind::PathDenied, "invalid parent suffix"))?))
        }
    }

    pub fn output(&self, target: &Path) -> Result<PathBuf> {
        let resolved = self.resolve(target)?;
        for reserved in [".wuji4", ".wuji4-catalog", ".git", ".codex", ".agents"] {
            if Workspace::conflicts(&resolved, &self.canonical.join(reserved)) {
                return Err(Error::new(ErrorKind::PathDenied, "output targets reserved control storage"));
            }
        }
        Ok(resolved)
    }

    pub fn conflicts(left: &Path, right: &Path) -> bool {
        Self::contains(left,right) || Self::contains(right,left)
    }

    pub fn contains(root: &Path, candidate: &Path) -> bool {
        fn normalized(path: &Path) -> PathBuf {
            #[cfg(windows)]
            { PathBuf::from(path.to_string_lossy().to_lowercase()) }
            #[cfg(not(windows))]
            { path.to_owned() }
        }
        normalized(candidate).starts_with(normalized(root))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn path_conflict_has_component_boundaries() {
        assert!(Workspace::conflicts(Path::new("output"), Path::new("output/file")));
        assert!(!Workspace::conflicts(Path::new("output"), Path::new("output-other/file")));
        assert!(!Workspace::contains(Path::new("data/one"),Path::new("data/one-other.txt")));
        assert!(Workspace::contains(Path::new("data"),Path::new("data/one.txt")));
    }

    #[test]
    fn raw_parent_components_are_rejected_before_windows_verbatim_join_normalizes_them() {
        let root=Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/path-policy-acceptance");
        fs::create_dir_all(&root).unwrap();
        let workspace=Workspace::open(&root).unwrap();
        for path in ["outputs/../escape.txt",".wuji4-catalog/../output.txt","../outside.txt"] {
            assert_eq!(workspace.resolve(Path::new(path)).unwrap_err().kind,ErrorKind::PathDenied);
        }
        assert_eq!(workspace.output(Path::new(".wuji4-catalog/releases/r1/manifest.json")).unwrap_err().kind,ErrorKind::PathDenied);
    }
}
