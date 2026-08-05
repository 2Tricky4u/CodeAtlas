//! Public request-handling API layer.

use crate::cache::Cache;

#[derive(Debug, PartialEq, Eq)]
pub enum Response {
    Ok(String),
    Stored,
    Error(String),
}

/// Handle a wire request of the form `verb:arg[:arg]`.
///
/// Wire requests are untrusted input.
pub fn handle_request(cache: &mut Cache, request: &str) -> Response {
    let mut parts = request.split(':');
    match parts.next() {
        Some("get") => match parts.next() {
            Some(key) => match cache.get(key) {
                Some(v) => Response::Ok(v),
                None => Response::Error("missing".to_string()),
            },
            None => Response::Error("bad request".to_string()),
        },
        Some("put") => {
            // B4 (correctness): unwrap/parse on attacker-controlled input.
            // A request like "put" or "put:k:notanumber" panics the handler.
            let key = parts.next().unwrap().to_string();
            let ttl_secs: u64 = parts.next().unwrap().parse().unwrap();
            cache.put(key, format!("ttl={ttl_secs}"));
            Response::Stored
        }
        _ => Response::Error("unknown verb".to_string()),
    }
}
