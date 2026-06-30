use crate::library::truncate::{Truncate, TruncateClass};
use petgraph::graph::{DiGraph, NodeIndex};
use std::collections::{HashMap, HashSet};

/// What a node in the pedigree represents.
#[derive(Debug, Clone)]
pub enum NodeKind {
    /// Tier 0..=N-1: equivalence class keyed by the non-null BB sequence in N→C order.
    /// Padding-invariant, order-sensitive.
    Class(TruncateClass),
    /// Tier N: a single positional full compound (no null positions).
    Compound(Truncate),
}

#[derive(Debug, Clone)]
pub struct PedigreeNode {
    pub kind: NodeKind,
    pub tier: usize,
    /// Positional truncates this node represents.
    /// For `Class` nodes: every realizable positional placement that strips to the
    /// class's ordered BB sequence (i.e. the same BBs in the same order, varying only
    /// in where the null padding lives). These are the chromatogram replicates.
    /// For `Compound` nodes: the single positional truncate itself.
    pub members: Vec<Truncate>,
}

impl PedigreeNode {
    /// Stable canonical id, namespaced by tier and kind so class and compound ids never collide.
    /// Uses `_` as the separator (DOT-safe) so node ids drop straight into graphviz.
    pub fn id(&self) -> String {
        match &self.kind {
            NodeKind::Class(c) if c.is_root() => format!("C{}", c.tier()),
            NodeKind::Class(c) => format!("C{}_{}", c.tier(), c.bbs.join("_")),
            NodeKind::Compound(t) => format!("F{}_{}", t.n(), t.positions.join("_")),
        }
    }

    /// Human-readable label (for figures).
    pub fn label(&self) -> String {
        match &self.kind {
            NodeKind::Class(c) if c.is_root() => "ROOT".to_string(),
            NodeKind::Class(c) => c.bbs.join("+"),
            NodeKind::Compound(t) => t.display(),
        }
    }
}

/// Edges go parent → child (root toward leaves).
pub type Pedigree = DiGraph<PedigreeNode, ()>;

/// Build the full pedigree DAG for a position-restricted library.
///
/// `bbs_per_position` lists the set of BBs physically allowed at each position, in
/// N→C order. Matches real DELs where different positions admit different BBs. For an
/// unrestricted library, pass the same set N times.
///
/// The pedigree is built by:
/// 1. Cartesian product over `(allowed_at_position_i ∪ {null_token})` for i=0..N
///    — this is exactly the set of physically realizable positional truncates.
/// 2. Each truncate's tier = number of non-null positions.
/// 3. Tier 0..=N-1 truncates are grouped by their non-null BB sequence in N→C order
///    → one `Class` node per sequence, with members = the realizable positional
///    placements (same BBs in the same order, varying only in null padding location).
///    Sequences with no realizable placement under the position constraints are absent.
/// 4. Tier-N truncates each become one `Compound` node (single member).
///
/// Edges go from each parent class to each child class/compound (parent = drop one
/// non-null position, take the resulting ordered subsequence).
pub fn build_pedigree(bbs_per_position: &[Vec<String>], null_token: &str) -> Pedigree {
    let n = bbs_per_position.len();
    let mut g: Pedigree = DiGraph::new();
    let mut class_idx: HashMap<TruncateClass, NodeIndex> = HashMap::new();

    // Always have a root node (the all-null truncate).
    let root_class = TruncateClass::root();
    let root_members = vec![Truncate::new(vec![null_token.to_string(); n])];
    let root_ix = g.add_node(PedigreeNode {
        kind: NodeKind::Class(root_class.clone()),
        tier: 0,
        members: root_members,
    });
    class_idx.insert(root_class, root_ix);

    if n == 0 {
        return g;
    }

    // Realizable per-position alphabet: each position's BBs ∪ {null_token}.
    let alphabet: Vec<Vec<String>> = bbs_per_position
        .iter()
        .map(|bbs| {
            let mut v = bbs.clone();
            v.push(null_token.to_string());
            v
        })
        .collect();

    // Group all realizable positional truncates by (tier, multiset).
    // For tier == n: collect compound truncates (each becomes its own node).
    let mut by_class: HashMap<(usize, TruncateClass), Vec<Truncate>> = HashMap::new();
    let mut compounds: Vec<Truncate> = Vec::new();
    for positions in cartesian_product(&alphabet) {
        let trunc = Truncate::new(positions);
        let tier = trunc.tier(null_token);
        if tier == n {
            compounds.push(trunc);
        } else {
            let class = TruncateClass::new(trunc.class_key(null_token));
            by_class.entry((tier, class)).or_default().push(trunc);
        }
    }

    // Insert class nodes (tier 1..=N-1). Sort for deterministic NodeIndex assignment.
    let mut keys: Vec<(usize, TruncateClass)> =
        by_class.keys().filter(|(t, _)| *t > 0).cloned().collect();
    keys.sort();
    for (tier, class) in keys {
        let members = by_class.remove(&(tier, class.clone())).unwrap();
        let ix = g.add_node(PedigreeNode {
            kind: NodeKind::Class(class.clone()),
            tier,
            members,
        });
        class_idx.insert(class, ix);
    }

    // Wire class → class edges by parent multiset.
    let snapshot: Vec<(TruncateClass, NodeIndex)> = class_idx
        .iter()
        .filter(|(c, _)| !c.is_root())
        .map(|(c, &ix)| (c.clone(), ix))
        .collect();
    for (class, ix) in snapshot {
        for parent in class.parents() {
            if let Some(&pix) = class_idx.get(&parent) {
                g.add_edge(pix, ix, ());
            }
        }
    }

    // Tier-N compound nodes + their parent edges. Parent = drop one position from the
    // positional truncate, then strip remaining nulls preserving N→C order.
    for trunc in compounds {
        let positional = trunc.positions.clone();
        let ix = g.add_node(PedigreeNode {
            kind: NodeKind::Compound(trunc.clone()),
            tier: n,
            members: vec![trunc],
        });
        let mut parent_keys: HashSet<Vec<String>> = HashSet::new();
        for i in 0..n {
            let bbs: Vec<String> = positional
                .iter()
                .enumerate()
                .filter(|(j, _)| *j != i)
                .map(|(_, s)| s.clone())
                .filter(|s| s != null_token)
                .collect();
            parent_keys.insert(bbs);
        }
        for pk in parent_keys {
            let parent_class = TruncateClass { bbs: pk };
            if let Some(&pix) = class_idx.get(&parent_class) {
                g.add_edge(pix, ix, ());
            }
        }
    }

    g
}

/// Cartesian product over per-position string alphabets.
fn cartesian_product(alphabet: &[Vec<String>]) -> Vec<Vec<String>> {
    let mut out = Vec::new();
    let mut buf = Vec::with_capacity(alphabet.len());
    walk_cartesian(alphabet, 0, &mut buf, &mut out);
    out
}

fn walk_cartesian(
    alphabet: &[Vec<String>],
    pos: usize,
    buf: &mut Vec<String>,
    out: &mut Vec<Vec<String>>,
) {
    if pos == alphabet.len() {
        out.push(buf.clone());
        return;
    }
    for x in &alphabet[pos] {
        buf.push(x.clone());
        walk_cartesian(alphabet, pos + 1, buf, out);
        buf.pop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use petgraph::Direction;

    /// Test convenience: an unrestricted library where every position admits all `bbs`.
    fn unrestricted(bbs: &[&str], n: usize) -> Vec<Vec<String>> {
        let owned: Vec<String> = bbs.iter().map(|b| b.to_string()).collect();
        vec![owned; n]
    }

    #[test]
    fn tier_sizes_3bbs_n3() {
        // Classes are subsequences in N→C order (padding-invariant, order-sensitive).
        // Tier 0: 1 root.
        // Tier 1: 3 single-BB classes ([A], [B], [C]).
        // Tier 2: 3*3 = 9 ordered pairs ([A,A], [A,B], ..., [C,C]).
        // Tier 3: 3^3 = 27 positional compounds.
        let g = build_pedigree(&unrestricted(&["A", "B", "C"], 3), "-");
        let mut counts = vec![0usize; 4];
        for ix in g.node_indices() {
            counts[g[ix].tier] += 1;
        }
        assert_eq!(counts, vec![1, 3, 9, 27]);
    }

    #[test]
    fn root_has_no_incoming_edges() {
        let g = build_pedigree(&unrestricted(&["A", "B"], 2), "-");
        let root = g.node_indices().find(|&ix| g[ix].tier == 0).unwrap();
        assert_eq!(g.neighbors_directed(root, Direction::Incoming).count(), 0);
    }

    #[test]
    fn full_compound_parent_count_matches_distinct_drops() {
        let g = build_pedigree(&unrestricted(&["A", "B", "C"], 3), "-");
        for ix in g.node_indices() {
            if let NodeKind::Compound(t) = &g[ix].kind {
                let mut keys: HashSet<Vec<String>> = HashSet::new();
                for i in 0..t.n() {
                    let mut bbs = t.positions.clone();
                    bbs.remove(i);
                    // Strip nulls but preserve N→C order — same semantics as class_key.
                    bbs.retain(|s| s != "-");
                    keys.insert(bbs);
                }
                let actual = g.neighbors_directed(ix, Direction::Incoming).count();
                assert_eq!(
                    actual,
                    keys.len(),
                    "compound {} expected {} parents got {}",
                    t.display(),
                    keys.len(),
                    actual
                );
            }
        }
    }

    #[test]
    fn class_member_counts_3bbs_n3() {
        // Class members = realizable positional placements with the same ordered
        // BB sequence. Padding-position invariance ⇒ for tier k in N=3, members =
        // C(3, k) (choose which positions are non-null; the order is fixed by class).
        let g = build_pedigree(&unrestricted(&["A", "B", "C"], 3), "-");
        for ix in g.node_indices() {
            if let NodeKind::Class(c) = &g[ix].kind {
                let expected = match c.tier() {
                    0 => 1,
                    1 => 3, // [X]: choose which of 3 positions holds X
                    2 => 3, // [X,Y]: choose 2 of 3 positions, order is fixed by class
                    _ => unreachable!(),
                };
                assert_eq!(
                    g[ix].members.len(),
                    expected,
                    "class {:?} expected {} members got {}",
                    c,
                    expected,
                    g[ix].members.len()
                );
            }
        }
    }

    #[test]
    fn total_node_count_2bbs_n2() {
        // Tier 0: 1, Tier 1: 2, Tier 2: 2^2 = 4. Total = 7.
        let g = build_pedigree(&unrestricted(&["A", "B"], 2), "-");
        assert_eq!(g.node_count(), 7);
    }

    #[test]
    fn n0_yields_root_only() {
        let g = build_pedigree(&unrestricted(&["A"], 0), "-");
        assert_eq!(g.node_count(), 1);
        assert_eq!(g.edge_count(), 0);
    }

    #[test]
    fn class_member_class_keys_match_node_class() {
        let g = build_pedigree(&unrestricted(&["A", "B", "C"], 3), "-");
        for ix in g.node_indices() {
            if let NodeKind::Class(c) = &g[ix].kind {
                for m in &g[ix].members {
                    assert_eq!(&m.class_key("-"), &c.bbs);
                }
            }
        }
    }
}
