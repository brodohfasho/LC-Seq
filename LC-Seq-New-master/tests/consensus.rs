use lcseq::evaluate::{consensus, Chromatogram};
use lcseq::peaks::Peak;

fn pk(rt: f64) -> Peak {
    Peak { rt, intensity: 100.0, area: 1000.0, prominence: 80.0, p_value: 1e-6 }
}

/// Build a triangular chromatogram on a uniform 1.0-spaced grid centred on `mu` with
/// a small baseline (so the multi-replicate NB peak model has a defined Var(Y)).
fn chrom(grid: &[f64], mu: f64, amp: f64) -> Chromatogram {
    const BASELINE: f64 = 3.0;
    let intensity: Vec<f64> = grid
        .iter()
        .map(|&t| {
            let d = (t - mu).abs();
            BASELINE
                + if d < 1e-9 {
                    amp
                } else if d < 1.01 {
                    amp * 0.5
                } else {
                    0.0
                }
        })
        .collect();
    (grid.to_vec(), intensity)
}

#[test]
fn five_replicate_strict_majority() {
    // n=5, majority = 3. Three peaks cluster around 115 (within ±15), two distant.
    let grid: Vec<f64> = (0..1001).map(|i| i as f64).collect();
    let chroms = vec![
        chrom(&grid, 100.0, 100.0),
        chrom(&grid, 115.0, 100.0),
        chrom(&grid, 130.0, 100.0),
        chrom(&grid, 500.0, 100.0),
        chrom(&grid, 600.0, 100.0),
    ];
    let peaks = vec![
        vec![pk(100.0)],
        vec![pk(115.0)],
        vec![pk(130.0)],
        vec![pk(500.0)],
        vec![pk(600.0)],
    ];
    let r = consensus(&chroms, &peaks, 50.0, 30.0, 1e-3);
    assert!(r.passed);
    let crt = r.score_test_rt.unwrap();
    assert!(crt >= 100.0 && crt <= 130.0, "score_test_rt {} not in [100, 130]", crt);
}

#[test]
fn least_retained_past_threshold_window() {
    // Each replicate has multiple NB-significant peaks but a single chromatogram
    // apex around 85. bayesian_refined_picks is computed from the raw chromatogram
    // (rt of max intensity within ±FWHM of bayesian_pick), so each rep manifests
    // the chosen answer at its actual apex (~85).
    let grid: Vec<f64> = (0..201).map(|i| i as f64).collect();
    let chroms = vec![
        chrom(&grid, 85.0, 100.0),
        chrom(&grid, 85.0, 100.0),
        chrom(&grid, 85.0, 100.0),
    ];
    let peaks = vec![
        vec![pk(20.0), pk(80.0), pk(150.0)],
        vec![pk(30.0), pk(85.0), pk(160.0)],
        vec![pk(25.0), pk(90.0), pk(170.0)],
    ];
    let r = consensus(&chroms, &peaks, 50.0, 10.0, 1e-3);
    assert!(r.passed);
    // Each rep's chromatogram apex is at rt=85 → all three refined picks land there.
    assert_eq!(r.bayesian_refined_picks, vec![Some(85.0), Some(85.0), Some(85.0)]);
    // All three reps have an NB-significant peak in the FWHM window (80, 85, 90
    // all within ±FWHM of ~85), so all three are in the supporting set.
    assert_eq!(r.bayesian_supporting_replicates, vec![0, 1, 2]);
}
