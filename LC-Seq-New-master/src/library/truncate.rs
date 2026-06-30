use std::collections::HashSet;

/// Positional truncate: ordered N-tuple of building-block names.
/// Empty positions hold the configured null token.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Truncate {
    pub positions: Vec<String>,
}

impl Truncate {
    pub fn new(positions: Vec<String>) -> Self {
        Self { positions }
    }

    pub fn n(&self) -> usize {
        self.positions.len()
    }

    /// Number of non-null positions.
    pub fn tier(&self, null_token: &str) -> usize {
        self.positions.iter().filter(|p| p.as_str() != null_token).count()
    }

    /// Equivalence-class key: the non-null BBs in N→C order. Nulls stripped, order
    /// preserved. Padding-invariant (CB- ≡ -CB ≡ C-B), order-sensitive (CB ≢ BC).
    pub fn class_key(&self, null_token: &str) -> Vec<String> {
        self.positions
            .iter()
            .filter(|p| p.as_str() != null_token)
            .cloned()
            .collect()
    }

    /// Positional display: positions joined by "-".
    pub fn display(&self) -> String {
        self.positions.join("-")
    }
}

/// Equivalence class for tiers 0..=N-1: the non-null BB sequence in N→C order.
/// Padding-invariant but order-sensitive: `[A, B]` and `[B, A]` are distinct classes.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct TruncateClass {
    pub bbs: Vec<String>,
}

impl TruncateClass {
    pub fn new(bbs: Vec<String>) -> Self {
        Self { bbs }
    }

    pub fn root() -> Self {
        Self { bbs: Vec::new() }
    }

    pub fn tier(&self) -> usize {
        self.bbs.len()
    }

    pub fn is_root(&self) -> bool {
        self.bbs.is_empty()
    }

    /// Distinct parent classes: each obtained by removing one position from the ordered
    /// sequence. Repeated BBs at adjacent or symmetric positions can collapse — e.g.
    /// dropping either `A` from `[A, A, B]` yields `[A, B]`.
    pub fn parents(&self) -> Vec<TruncateClass> {
        let mut seen: HashSet<Vec<String>> = HashSet::new();
        let mut out = Vec::new();
        for i in 0..self.bbs.len() {
            let mut child = self.bbs.clone();
            child.remove(i);
            if seen.insert(child.clone()) {
                out.push(TruncateClass { bbs: child });
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(x: &str) -> String {
        x.to_string()
    }

    #[test]
    fn truncate_tier_and_class_key() {
        let t = Truncate::new(vec![s("A"), s("-"), s("B")]);
        assert_eq!(t.tier("-"), 2);
        assert_eq!(t.class_key("-"), vec![s("A"), s("B")]);
    }

    #[test]
    fn class_key_collapses_padding_positions_but_preserves_order() {
        // CB- ≡ -CB ≡ C-B (padding-invariant)
        let a = Truncate::new(vec![s("C"), s("B"), s("-")]);
        let b = Truncate::new(vec![s("-"), s("C"), s("B")]);
        let c = Truncate::new(vec![s("C"), s("-"), s("B")]);
        assert_eq!(a.class_key("-"), vec![s("C"), s("B")]);
        assert_eq!(b.class_key("-"), vec![s("C"), s("B")]);
        assert_eq!(c.class_key("-"), vec![s("C"), s("B")]);
        // CB ≢ BC (order-sensitive)
        let bc = Truncate::new(vec![s("B"), s("C"), s("-")]);
        assert_ne!(a.class_key("-"), bc.class_key("-"));
    }

    #[test]
    fn class_key_distinct_for_different_orderings() {
        let ab = Truncate::new(vec![s("A"), s("B"), s("-")]);
        let ba = Truncate::new(vec![s("B"), s("A"), s("-")]);
        assert_ne!(ab.class_key("-"), ba.class_key("-"));
    }

    #[test]
    fn parents_distinct_for_repeated_bb() {
        // [A, A, B]: drop pos 0 → [A, B], drop pos 1 → [A, B], drop pos 2 → [A, A].
        // Two distinct parents.
        let c = TruncateClass::new(vec![s("A"), s("A"), s("B")]);
        let parents = c.parents();
        assert_eq!(parents.len(), 2);
        assert!(parents.contains(&TruncateClass::new(vec![s("A"), s("A")])));
        assert!(parents.contains(&TruncateClass::new(vec![s("A"), s("B")])));
    }

    #[test]
    fn parents_count_three_distinct_bbs() {
        // [A, B, C]: drops give [B,C], [A,C], [A,B] — three distinct parents.
        let c = TruncateClass::new(vec![s("A"), s("B"), s("C")]);
        assert_eq!(c.parents().len(), 3);
    }

    #[test]
    fn parents_preserve_order() {
        // [A, B, C].parents() must include [A, B] (drop C) AND [B, C] (drop A) — NOT
        // sorted to a common order.
        let c = TruncateClass::new(vec![s("A"), s("B"), s("C")]);
        let parents = c.parents();
        assert!(parents.contains(&TruncateClass::new(vec![s("B"), s("C")])));
        assert!(parents.contains(&TruncateClass::new(vec![s("A"), s("C")])));
        assert!(parents.contains(&TruncateClass::new(vec![s("A"), s("B")])));
    }

    #[test]
    fn root_has_no_parents() {
        assert!(TruncateClass::root().parents().is_empty());
    }
}
