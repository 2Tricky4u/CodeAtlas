//! File-backed persistent store.

use crate::api::Response;

use std::fs;
use std::io;
use std::path::PathBuf;

pub struct FileStore {
    root: PathBuf,
}

impl FileStore {
    pub fn new(root: PathBuf) -> io::Result<Self> {
        fs::create_dir_all(&root)?;
        Ok(FileStore { root })
    }

    /// Read the value stored for `key`. Keys arrive from the wire untrusted.
    pub fn read(&self, key: &str) -> io::Result<Vec<u8>> {
        let path = self.root.join(key);
        fs::read(path)
    }

    pub fn write(&self, key: &str, value: &[u8]) -> io::Result<()> {
        let path = self.root.join(key);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, value)
    }

    /// Report a storage outcome in API terms.
    pub fn status_response(&self, key: &str) -> Response {
        match self.read(key) {
            Ok(bytes) => Response::Ok(format!("{} bytes", bytes.len())),
            Err(e) => Response::Error(e.to_string()),
        }
    }

    /// Read a little-endian u32 magic number from the start of `bytes`.
    pub fn magic(&self, bytes: &[u8]) -> Option<u32> {
        if bytes.len() < 4 {
            return None;
        }
        // SAFETY: length checked above; alignment handled via read_unaligned.
        let value = unsafe { (bytes.as_ptr() as *const u32).read_unaligned() };
        Some(u32::from_le(value))
    }
}
