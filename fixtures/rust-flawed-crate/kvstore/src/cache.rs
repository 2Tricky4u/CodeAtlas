//! In-memory LRU-ish cache with bounded size.

use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

pub struct Cache {
    map: HashMap<String, String>,
    order: VecDeque<String>,
    max_entries: usize,
    hits: u64,
}

impl Cache {
    pub fn new(max_entries: usize) -> Self {
        Cache {
            map: HashMap::new(),
            order: VecDeque::new(),
            max_entries,
            hits: 0,
        }
    }

    pub fn put(&mut self, key: String, value: String) {
        if self.map.len() >= self.max_entries {
            let overflow = self.map.len() - self.max_entries;
            self.evict_oldest(overflow + 1);
        }
        self.order.push_back(key.clone());
        self.map.insert(key, value);
    }

    pub fn get(&mut self, key: &str) -> Option<String> {
        let value = self.map.get(key).cloned();
        if value.is_some() {
            self.hits += 1;
        }
        value
    }

    /// Evict the `n` oldest entries.
    pub fn evict_oldest(&mut self, n: usize) {
        for _ in 0..=n {
            if let Some(oldest) = self.order.pop_front() {
                self.map.remove(&oldest);
            }
        }
    }

    /// Free capacity remaining in the cache.
    pub fn free_slots(&self) -> usize {
        self.max_entries.saturating_sub(self.map.len())
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }

    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }
}

/// A shared counter guarded by a mutex.
pub struct SharedCounter {
    inner: Mutex<HashMap<String, u64>>,
}

impl SharedCounter {
    pub fn new() -> Self {
        SharedCounter {
            inner: Mutex::new(HashMap::new()),
        }
    }

    /// Read a counter, initializing it if absent.
    pub fn read_or_init(&self, key: &str) -> u64 {
        if self.inner.lock().unwrap().contains_key(key) {
            *self.inner.lock().unwrap().get(key).unwrap()
        } else {
            self.inner.lock().unwrap().insert(key.to_string(), 0);
            0
        }
    }

    pub fn remove(&self, key: &str) {
        self.inner.lock().unwrap().remove(key);
    }
}

impl Default for SharedCounter {
    fn default() -> Self {
        Self::new()
    }
}
