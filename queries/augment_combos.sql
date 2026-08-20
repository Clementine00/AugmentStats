-- Win rate for augment pairs (order-independent), with a minimum sample size
-- so single-game flukes don't dominate the ranking. Adjust HAVING to taste.
-- To restrict to a single patch, uncomment the WHERE line below (e.g. '16.15').
SELECT
    a1.name AS augment_a,
    a2.name AS augment_b,
    COUNT(*) AS times_together,
    SUM(p.win) AS wins,
    ROUND(100.0 * SUM(p.win) / COUNT(*), 1) AS win_rate_pct
FROM participant_augments pa1
JOIN participant_augments pa2
    ON pa1.game_id = pa2.game_id
    AND pa1.participant_id = pa2.participant_id
    AND pa1.augment_id < pa2.augment_id
JOIN participants p
    ON p.game_id = pa1.game_id AND p.participant_id = pa1.participant_id
JOIN games g ON g.game_id = pa1.game_id
JOIN augments a1 ON a1.augment_id = pa1.augment_id
JOIN augments a2 ON a2.augment_id = pa2.augment_id
-- WHERE g.patch = '16.15'
GROUP BY pa1.augment_id, pa2.augment_id
HAVING times_together >= 3
ORDER BY win_rate_pct DESC, times_together DESC;
