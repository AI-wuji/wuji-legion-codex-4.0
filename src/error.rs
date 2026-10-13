use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorKind {
    Shape,
    Reference,
    HashMismatch,
    ScopeDenied,
    AuthorityDenied,
    PathDenied,
    OwnerConflict,
    RevisionConflict,
    DependencyCycle,
    DependencyNotAccepted,
    LeaseExpired,
    ClockUntrusted,
    EventConflict,
    BudgetExhausted,
    HostUnknown,
    StaleReceipt,
    SelfReview,
    ValidationStale,
    CompositionConflict,
    RequiredWeakened,
    UnknownSubmission,
    MigrationUnsupported,
    Storage,
    Io,
}

#[derive(Debug)]
pub struct Error {
    pub kind: ErrorKind,
    pub detail: String,
}

impl Error {
    pub fn new(kind: ErrorKind, detail: impl Into<String>) -> Self {
        Self { kind, detail: detail.into() }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:?}: {}", self.kind, self.detail)
    }
}

impl std::error::Error for Error {}

impl From<rusqlite::Error> for Error {
    fn from(error: rusqlite::Error) -> Self {
        Self::new(ErrorKind::Storage, error.to_string())
    }
}

impl From<std::io::Error> for Error {
    fn from(error: std::io::Error) -> Self {
        Self::new(ErrorKind::Io, error.to_string())
    }
}

impl From<serde_json::Error> for Error {
    fn from(error: serde_json::Error) -> Self {
        Self::new(ErrorKind::Shape, error.to_string())
    }
}

pub type Result<T> = std::result::Result<T, Error>;
