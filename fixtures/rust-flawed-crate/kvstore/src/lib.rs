//! kvstore: a small bounded key-value store with an in-memory cache in front of
//! a file-backed store.

pub mod api;
pub mod cache;
pub mod storage;

pub use api::{handle_request, Response};
pub use cache::Cache;
pub use storage::FileStore;
