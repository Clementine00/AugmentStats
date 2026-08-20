-- Win rate and pick count per augment.
-- To restrict to a single patch, uncomment the WHERE line below (e.g. '16.15').
SELECT
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
-- WHERE g.patch = '16.15'
GROUP BY a.augment_id
ORDER BY picks DESC, win_rate_pct DESC;
