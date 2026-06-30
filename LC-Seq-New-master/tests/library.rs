use lcseq::library::{build_pedigree, NodeKind};
use petgraph::Direction;
use std::collections::HashMap;

fn s(x: &str) -> String {
    x.to_string()
}

fn unrestricted(bbs: &[&str], n: usize) -> Vec<Vec<String>> {
    let owned: Vec<String> = bbs.iter().map(|b| b.to_string()).collect();
    vec![owned; n]
}

#[test]
fn pedigree_3bbs_n3_full_shape() {
    let g = build_pedigree(&unrestricted(&["A", "B", "C"], 3), "AgxNull");

    // Tier sizes.
    let mut tier_counts = HashMap::<usize, usize>::new();
    for ix in g.node_indices() {
        *tier_counts.entry(g[ix].tier).or_insert(0) += 1;
    }
    assert_eq!(tier_counts[&0], 1);
    assert_eq!(tier_counts[&1], 3);
    assert_eq!(tier_counts[&2], 9); // ordered pairs from {A,B,C} with replacement = 3*3
    assert_eq!(tier_counts[&3], 27);

    // The root is the all-null positional truncate.
    let root = g
        .node_indices()
        .find(|&ix| g[ix].tier == 0)
        .expect("root exists");
    assert_eq!(
        g[root].members[0].positions,
        vec![s("AgxNull"), s("AgxNull"), s("AgxNull")]
    );
    assert_eq!(g[root].members[0].display(), "AgxNull-AgxNull-AgxNull");

    // Every tier-1 class has exactly the root as its parent.
    for ix in g.node_indices() {
        if g[ix].tier == 1 {
            let parents: Vec<_> = g.neighbors_directed(ix, Direction::Incoming).collect();
            assert_eq!(parents.len(), 1);
            assert_eq!(parents[0], root);
        }
    }

    // ABC (tier 3) reaches three distinct tier-2 parents: {A,B}, {A,C}, {B,C}.
    let abc = g
        .node_indices()
        .find(|&ix| matches!(&g[ix].kind, NodeKind::Compound(t) if t.positions == vec![s("A"), s("B"), s("C")]))
        .expect("ABC compound exists");
    let parent_classes: Vec<Vec<String>> = g
        .neighbors_directed(abc, Direction::Incoming)
        .map(|p| match &g[p].kind {
            NodeKind::Class(c) => c.bbs.clone(),
            _ => panic!("ABC parent should be a class"),
        })
        .collect();
    assert_eq!(parent_classes.len(), 3);
    assert!(parent_classes.contains(&vec![s("A"), s("B")]));
    assert!(parent_classes.contains(&vec![s("A"), s("C")]));
    assert!(parent_classes.contains(&vec![s("B"), s("C")]));

    // AAA (tier 3) reaches exactly one tier-2 parent: {A,A}.
    let aaa = g
        .node_indices()
        .find(|&ix| matches!(&g[ix].kind, NodeKind::Compound(t) if t.positions == vec![s("A"), s("A"), s("A")]))
        .expect("AAA compound exists");
    let aaa_parents: Vec<Vec<String>> = g
        .neighbors_directed(aaa, Direction::Incoming)
        .map(|p| match &g[p].kind {
            NodeKind::Class(c) => c.bbs.clone(),
            _ => panic!(),
        })
        .collect();
    assert_eq!(aaa_parents, vec![vec![s("A"), s("A")]]);
}

#[test]
fn class_node_ids_unique() {
    let g = build_pedigree(&unrestricted(&["A", "B", "C"], 3), "AgxNull");
    let mut ids = std::collections::HashSet::new();
    for ix in g.node_indices() {
        assert!(ids.insert(g[ix].id()), "duplicate id: {}", g[ix].id());
    }
}
