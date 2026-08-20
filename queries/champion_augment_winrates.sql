-- Win rate per (champion, augment) pair.
-- To restrict to a single patch, uncomment the WHERE line below (e.g. '16.15').
SELECT
    c.name AS champion,
    a.name AS augment,
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
JOIN champions c
    ON c.champion_id = p.champion_id
-- WHERE g.patch = '16.15'
GROUP BY p.champion_id, a.augment_id
HAVING picks >= 2
ORDER BY c.name, win_rate_pct DESC;
