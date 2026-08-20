-- Win rate and pick count per augment, broken down by patch, so you can track
-- how an augment performs across balance changes. Sorted by patch (newest not
-- guaranteed last -- string sort), then by pick count within each patch.
SELECT
    g.patch,
    a.name,
    a.rarity,
    COUNT(*) AS picks,
    SUM(p.win) AS wins,
    ROUND(100.0 * SUM(p.win) / COUNT(*), 1) AS win_rate_pct
FROM participant_augments pa
JOIN participants p
    ON p.game_id = pa.game_id AND p.participant_id = pa.participant_id
JOIN games g
    ON g.game_id = pa.game_id
JOIN augments a
    ON a.augment_id = pa.augment_id
GROUP BY g.patch, a.augment_id
ORDER BY g.patch, picks DESC, win_rate_pct DESC;
