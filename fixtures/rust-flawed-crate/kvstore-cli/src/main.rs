//! Minimal CLI exercising the kvstore API.

use kvstore::{handle_request, Cache};

fn main() {
    let mut cache = Cache::new(64);
    let args: Vec<String> = std::env::args().skip(1).collect();
    for request in &args {
        let response = handle_request(&mut cache, request);
        println!("{response:?}");
    }
}
