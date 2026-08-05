//! kvstore: a small key-value store used as a CodeAtlas evaluation fixture.
//!
//! This crate deliberately contains planted defects documented in the fixture
//! MANIFEST.yaml (B1..B5) plus sound decoys. Do not "fix" them.

pub mod api;
pub mod cache;
pub mod storage;

pub use api::{handle_request, Response};
pub use cache::Cache;
pub use storage::FileStore;
