#!/usr/bin/env node
// Ground truth for one eval run, read from the reader at run time (the game date moves as the owner
// plays, so constants go stale). No model calls.
//
//   node evals/facts.mjs --out <run dir>       writes <run dir>/facts.json
//
// Uses the same reader environment as the run (PI_FM_MCP_LAUNCHER, FM_READER_CHECKOUT, FMCP_CACHE_DIR).
// Checks in questions.json name a fact as {{key}} inside a pattern; score.mjs substitutes it. Each
// value is a regular-expression fragment (names escaped) or a plain number.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { connectReader } from './reader-client.mjs';

const esc = s => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const surname = name => String(name).trim().split(/\s+/).at(-1);
const alt = names => [...new Set(names.filter(Boolean).map(esc))].join('|');
// Club names as people write them: "Brighton & Hove Albion" -> "Brighton".
const clubWord = name => String(name).replace(/^(AFC|FC)\s+/, '').split(/\s+/)[0];

/** Money as people write it: 123,456,789 -> "123m" / "123.5m" / "£123" patterns. */
function millionsRe(value) {
  if (value == null || !Number.isFinite(Number(value)) || Math.abs(value) < 1e6) return null;
  const m = Math.abs(Number(value)) / 1e6;
  const forms = new Set([m.toFixed(0), m.toFixed(1), Math.floor(m).toString()]);
  return `(?:${[...forms].map(f => esc(f)).join('|')})\\s*(?:m\\b|M\\b|million)`;
}

const SQL = {
  managed: 'SELECT team_idx, club_idx FROM _managed',
  squad: 'SELECT name FROM player_view WHERE team_idx = (SELECT team_idx FROM _managed)',
  next5: `SELECT f.date, c.name, ht.name, at.name, f.home_team_idx FROM fixture f
          JOIN competition_view c ON c.idx = f.competition_idx JOIN team ht ON ht.idx = f.home_team_idx JOIN team at ON at.idx = f.away_team_idx
          WHERE (SELECT team_idx FROM _managed) IN (f.home_team_idx, f.away_team_idx)
            AND f.date >= (SELECT game_date FROM _snapshot) AND f.home_goals IS NULL ORDER BY f.date LIMIT 5`,
  lastPl: `SELECT f.date, ht.name, at.name, f.home_goals, f.away_goals FROM fixture f
           JOIN team ht ON ht.idx = f.home_team_idx JOIN team at ON at.idx = f.away_team_idx
           WHERE (SELECT team_idx FROM _managed) IN (f.home_team_idx, f.away_team_idx)
             AND f.competition_idx = (SELECT idx FROM competition_view WHERE name = 'Premier League') AND f.home_goals IS NOT NULL
             AND f.date <= (SELECT game_date FROM _snapshot) ORDER BY f.date DESC LIMIT 1`,
  table: `SELECT s.position, s.team_idx, t.name, s.points FROM standing_view s JOIN team t ON t.idx = s.team_idx
          WHERE s.competition_idx = (SELECT idx FROM competition_view WHERE name = 'Premier League') ORDER BY s.position`,
  scorers: `SELECT p.name, s.goals FROM player_season_stats s JOIN competition_view c ON c.idx = s.competition_idx
            JOIN player_view p ON p.idx = s.person_idx
            WHERE c.name = 'Premier League' AND s.season = (SELECT MAX(season) FROM player_season_stats WHERE team_idx = (SELECT team_idx FROM _managed))
            ORDER BY s.goals DESC LIMIT 5`,
  arsenal: `SELECT balance, transfer_budget FROM club_view WHERE name = 'Arsenal' AND player_gender = 'Male'`,
  manutd: `SELECT balance, transfer_budget FROM club_view WHERE name = 'Manchester United' AND player_gender = 'Male'`,
  expiring: `SELECT p.name FROM contract_view c JOIN player_view p ON p.idx = c.person_idx
             WHERE c.club_idx = (SELECT club_idx FROM _managed) AND p.team_idx = (SELECT team_idx FROM _managed) AND c.role = 'main'
               AND date(c.expires_date) BETWEEN (SELECT game_date FROM _snapshot) AND date((SELECT game_date FROM _snapshot), '+12 months')`,
  eichhorn: `SELECT current_ability_stars_min, current_ability_stars_max, potential_ability_stars_min, potential_ability_stars_max
             FROM m_player_view WHERE name LIKE '%Kennet Eichhorn%' LIMIT 1`,
  // Version 4: the round-2 reader surface.
  // One row per player of the managed side in the loaded match (max_rows 100 would cut the term rows).
  rating: `SELECT p.name, r.person_idx, MIN(r.stored_rating), MAX(r.minutes)
           FROM match_rating_component r JOIN player_view p ON p.idx = r.person_idx
           WHERE r.team_idx = (SELECT team_idx FROM _managed) GROUP BY r.person_idx ORDER BY 3`,
  ratingTerms: `SELECT label, term, contribution FROM match_rating_component WHERE person_idx = ? ORDER BY ABS(contribution) DESC`,
  promises: `SELECT p.name, pr.title, pr.deadline FROM promise pr JOIN player_view p ON p.idx = pr.player_idx WHERE pr.list = 'active'`,
  leaders: `SELECT p.name FROM squad_hierarchy h JOIN player_view p ON p.idx = h.person_idx
            WHERE h.team_idx = (SELECT team_idx FROM _managed) AND h.tier = 'team_leader'`,
  isolated: `SELECT p.name FROM social_group g JOIN player_view p ON p.idx = g.person_idx
             WHERE g.team_idx = (SELECT team_idx FROM _managed) AND g.group_name = 'other'`,
  career: `SELECT s.year, t.name FROM person_season_statistics s JOIN team t ON t.idx = s.team_idx
           WHERE s.person_idx = (SELECT idx FROM player_view WHERE name = 'Anthony Gordon' AND team_idx = (SELECT team_idx FROM _managed))
             AND s.scope_name = 'Overall (Club)' AND s.appearances > 0 ORDER BY s.year`,
  agent: `SELECT interest, fee_min, fee_max, wage_min, wage_max, contract_end FROM m_agent_demand
          WHERE person_idx = (SELECT idx FROM m_player_view WHERE name = 'Lucas Bergvall') LIMIT 1`,
  finance: `SELECT direction, category, amount FROM club_finance_breakdown WHERE period = 'this_season' AND amount > 0 ORDER BY direction, amount DESC`,
  unregistered: `SELECT p.name FROM player_view p
                 LEFT JOIN competition_registration r ON r.person_idx = p.idx AND r.team_idx = p.team_idx
                   AND r.competition_idx = (SELECT idx FROM competition_view WHERE name = 'UEFA Champions League')
                 WHERE p.team_idx = (SELECT team_idx FROM _managed) AND COALESCE(r.registered, 0) = 0`,
  improvers: `WITH h AS (SELECT person_idx, month, (SELECT SUM(value) FROM json_each(attributes)) / 5.0 AS total FROM player_attribute_history
                WHERE person_idx IN (SELECT idx FROM player_view WHERE club_idx = (SELECT club_idx FROM _managed) AND age <= 23)),
              cur AS (SELECT person_idx, total FROM h WHERE month = (SELECT MAX(month) FROM h)),
              past AS (SELECT person_idx, total FROM h WHERE month = strftime('%Y-%m', (SELECT game_date FROM _snapshot), '-6 months'))
              SELECT p.name, p.team_idx = (SELECT team_idx FROM _managed), cur.total - past.total AS gain
              FROM cur JOIN past USING (person_idx) JOIN player_view p ON p.idx = cur.person_idx ORDER BY gain DESC`,
  winners: `SELECT h.season, t.name FROM competition_history h JOIN team t ON t.idx = h.first_team_idx
            WHERE h.competition_idx = (SELECT idx FROM competition_view WHERE name = 'Premier League') ORDER BY h.entry LIMIT 5`,
  earners: `SELECT name, wage FROM m_player_view WHERE club_idx IN (SELECT idx FROM m_club_view WHERE name = 'Arsenal')
            ORDER BY wage DESC LIMIT 5`,
  gyokeres: `SELECT wage, contract_expires FROM m_player_view WHERE name = 'Viktor Gyökeres' LIMIT 1`,
  saka: `SELECT wage, contract_expires FROM m_player_view WHERE name = 'Bukayo Saka' LIMIT 1`,
};

/** A weekly wage as people write it: 306,798 -> "307K", "306,798", "£307k", "15.95M per annum". */
function wageRe(value) {
  if (value == null || !Number.isFinite(Number(value))) return null;
  const v = Number(value);
  const k = Math.round(v / 1000);
  const forms = new Set([`${k}\\s*[Kk]`, `${k},\\d{3}`, esc(v.toLocaleString('en-GB')), `${esc((v * 52 / 1e6).toFixed(2))}\\s*(?:m|M|million)`, `${esc((v * 52 / 1e6).toFixed(1))}\\s*(?:m|M|million)`]);
  return [...forms].join('|');
}
/** A date as people write it: 2031-06-30 -> "2031", "June 2031", "30 June 2031", "30/06/2031". */
const yearRe = date => (date ? `\\b${String(date).slice(0, 4)}\\b` : null);
/** Label words a paraphrase keeps: "Goals conceded while on the pitch" -> conceded|pitch. */
const labelWords = labels => alt([...new Set(labels.flatMap(l => String(l).toLowerCase().match(/[a-z]{5,}/g) ?? []))]
  .filter(w => !['while', 'model', 'rating', 'player', 'fewer', 'there', 'their'].includes(w)));

async function rows(reader, key, view = 'full') {
  const r = await reader.call('fm_db_query', { sql: SQL[key], view, max_rows: 100 });
  return r.rows ?? [];
}

export async function collectFacts(reader) {
  const facts = { collected_at: new Date().toISOString(), errors: {} };
  const attempt = async (key, fn) => { try { await fn(); } catch (error) { facts.errors[key] = String(error.message).slice(0, 300); } };
  await attempt('save', async () => {
    const save = await reader.call('fm_get_save', {});
    facts.game_date = save.save?.current_date;
    facts.club = save.save?.coaches?.[0]?.club?.name;
  });
  await attempt('squad', async () => {
    const names = (await rows(reader, 'squad')).map(r => r[0]);
    facts.squad_size = names.length;
    facts.squad_re = alt(names.map(surname));
  });
  await attempt('next5', async () => {
    const managed = (await rows(reader, 'managed'))[0];
    const next = await rows(reader, 'next5');
    facts.next5 = next.map(([date, comp, home, away, homeIdx]) => ({ date, comp, opponent: homeIdx === managed[0] ? away : home }));
    facts.next5_re = alt(facts.next5.map(f => clubWord(f.opponent)));
    facts.next_opponent_re = facts.next5[0] ? esc(clubWord(facts.next5[0].opponent)) : null;
    facts.next5_has_ucl = facts.next5.some(f => /Champions League/.test(f.comp));
  });
  await attempt('lastPl', async () => {
    const [date, home, away, hg, ag] = (await rows(reader, 'lastPl'))[0] ?? [];
    if (date) {
      facts.last_pl = { date, home, away, score: `${hg}-${ag}` };
      facts.last_pl_score_re = `\\b${hg}\\s*[-–]\\s*${ag}\\b|\\b${ag}\\s*[-–]\\s*${hg}\\b`;
      facts.last_pl_opponent_re = esc(clubWord(home === facts.club ? away : home));
    }
  });
  await attempt('table', async () => {
    const table = await rows(reader, 'table');
    const managed = (await rows(reader, 'managed'))[0];
    const mine = table.find(r => r[1] === managed[0]);
    facts.league_position = mine?.[0] ?? null;
    facts.league_points = mine?.[3] ?? null;
  });
  await attempt('scorers', async () => {
    const top = await rows(reader, 'scorers');
    facts.top_scorers = top.map(([name, goals]) => ({ name, goals }));
    facts.top_scorers_re = alt(top.slice(0, 3).map(r => surname(r[0])));
  });
  await attempt('arsenal', async () => {
    const [balance, budget] = (await rows(reader, 'arsenal'))[0] ?? [];
    facts.arsenal_money_re = [millionsRe(balance), millionsRe(budget)].filter(Boolean).join('|') || null;
  });
  await attempt('manutd', async () => {
    const [balance, budget] = (await rows(reader, 'manutd'))[0] ?? [];
    facts.manutd_money_re = [millionsRe(balance), millionsRe(budget)].filter(Boolean).join('|') || null;
  });
  await attempt('expiring', async () => {
    const names = (await rows(reader, 'expiring')).map(r => r[0]);
    facts.expiring = names;
    facts.expiring_re = names.length ? alt(names.map(surname)) : 'none|no (?:player|contract|one)|nobody';
  });
  await attempt('eichhorn', async () => {
    const r = (await rows(reader, 'eichhorn', 'manager'))[0];
    if (r && r.every(v => v != null)) {
      const range = (lo, hi) => (lo === hi ? esc(lo) : `${esc(lo)}\\s*(?:-|–|to)\\s*${esc(hi)}`);
      facts.eichhorn_stars = r;
      facts.eichhorn_stars_re = `${range(r[0], r[1])}|${range(r[2], r[3])}`;
    }
  });
  await attempt('rating', async () => {
    // The match loaded in the game: the two lowest-rated players of the managed side who played
    // 30 minutes or more, and the terms that moved the lowest rating most.
    const ranked = (await rows(reader, 'rating')).map(([name, idx, stored, minutes]) => ({ name, idx, stored, minutes }))
      .filter(p => p.minutes == null || p.minutes >= 30).sort((a, b) => a.stored - b.stored);
    if (ranked.length) {
      const low = ranked[0];
      const r = await reader.call('fm_db_query', { sql: SQL.ratingTerms, params: [low.idx], max_rows: 40 });
      const top = (r.rows ?? []).filter(([label, term]) => !/base|rounding/i.test(`${term} ${label}`)).slice(0, 3)
        .map(([label, , contribution]) => ({ label, contribution }));
      facts.rating_low = { name: low.name, rating: low.stored, terms: top };
      facts.rating_low_names_re = alt(ranked.slice(0, 2).map(p => surname(p.name)));
      facts.rating_low_value_re = `\\b(?:${[...new Set([low.stored.toFixed(2), low.stored.toFixed(1)])].map(esc).join('|')})(?!\\d)`;
      facts.rating_terms_re = labelWords(top.map(t => t.label)) || null;
    }
  });
  await attempt('promises', async () => {
    const r = await rows(reader, 'promises');
    facts.promises = r.map(([name, title, deadline]) => ({ name, title, deadline }));
    facts.promise_count = r.length;
    facts.promise_re = r.length ? alt(r.map(x => surname(x[0]))) : 'no (?:active )?promises|none';
  });
  await attempt('dressing', async () => {
    const leaders = (await rows(reader, 'leaders')).map(r => r[0]);
    const isolated = (await rows(reader, 'isolated')).map(r => r[0]);
    facts.leaders = leaders;
    facts.leaders_re = leaders.length ? alt(leaders.map(surname)) : null;
    facts.isolated = isolated;
    facts.isolated_re = isolated.length ? alt(isolated.map(surname)) : null;
  });
  await attempt('career', async () => {
    const r = await rows(reader, 'career');
    facts.career_seasons = r.length;
    facts.career_clubs_re = r.length ? alt([...new Set(r.map(x => clubWord(x[1])))]) : null;
  });
  await attempt('agent', async () => {
    const [interest, feeMin, feeMax, wageMin, wageMax, end] = (await rows(reader, 'agent', 'manager'))[0] ?? [];
    facts.agent = { interest, feeMin, feeMax, wageMin, wageMax, end };
    facts.agent_fee_re = [millionsRe(feeMin), millionsRe(feeMax)].filter(Boolean).join('|') || null;
    facts.agent_wage_re = [wageRe(wageMin), wageRe(wageMax)].filter(Boolean).join('|') || null;
  });
  await attempt('finance', async () => {
    const r = await rows(reader, 'finance');
    const top = dir => r.filter(x => x[0] === dir).slice(0, 2).map(x => x[1]);
    facts.finance_top = { income: top('income'), expenditure: top('expenditure') };
    // Paraphrases keep the first word ("Players sold", "Transfers", "Player wages").
    const first = names => alt(names.map(n => String(n).split(/\s+/)[0].replace(/s$/, '')));
    facts.finance_income_re = first(top('income'));
    facts.finance_expenditure_re = first(top('expenditure'));
  });
  await attempt('unregistered', async () => {
    const names = (await rows(reader, 'unregistered')).map(r => r[0]);
    facts.unregistered = names;
    facts.unregistered_re = names.length ? alt(names.map(surname)) : 'every|all (?:\\d+ )?(?:first-team )?players (?:are )?registered';
    facts.unregistered_min = Math.min(names.length, 2) || 1;
  });
  await attempt('improvers', async () => {
    const r = await rows(reader, 'improvers');
    const club = r.slice(0, 5).map(x => x[0]);
    const first = r.filter(x => x[1] === 1).slice(0, 3).map(x => x[0]);
    facts.improvers = { club, first_team: first };
    facts.improvers_re = alt([...club, ...first].map(surname));
  });
  await attempt('winners', async () => {
    const r = await rows(reader, 'winners');
    facts.winners = r.map(([season, name]) => ({ season, name }));
    facts.winners_re = alt([...new Set(r.map(x => clubWord(x[1])))]);
    facts.winners_distinct = new Set(r.map(x => x[1])).size;
  });
  await attempt('earners', async () => {
    const r = await rows(reader, 'earners', 'manager');
    facts.earners = r.map(([name, wage]) => ({ name, wage }));
    facts.earners_re = alt(r.slice(0, 3).map(x => surname(x[0])));
    facts.earners_wage_re = r[0] ? wageRe(r[0][1]) : null;
  });
  for (const key of ['gyokeres', 'saka']) {
    await attempt(key, async () => {
      const [wage, expires] = (await rows(reader, key, 'manager'))[0] ?? [];
      facts[key] = { wage, expires };
      facts[`${key}_wage_re`] = wageRe(wage);
      facts[`${key}_expiry_re`] = yearRe(expires);
    });
  }
  await attempt('board', async () => {
    const board = await reader.call('fm_get_board_confidence', {});
    const overall = board?.overall ?? board?.confidence ?? board;
    let grade = overall?.grade ?? overall?.overall_grade ?? board?.overall_grade;
    if (grade && typeof grade === 'object') grade = grade.letter ?? grade.grade ?? null;
    facts.board_grade = grade ?? null;
    if (typeof grade === 'string') facts.board_grade_re = `\\b${esc(grade)}(?![+\\-\\w])`;
    const sentence = overall?.sentence ?? overall?.text ?? board?.overall_sentence;
    if (typeof sentence === 'string') facts.board_sentence = sentence;
  });
  await attempt('inbox', async () => {
    const inbox = await reader.call('fm_get_inbox', { limit: 8, unread_only: true });
    const items = inbox?.result ?? inbox?.items ?? inbox?.messages ?? (Array.isArray(inbox) ? inbox : []);
    facts.inbox_subjects = items.map(i => i.subject).filter(Boolean);
    const words = facts.inbox_subjects.flatMap(s => s.match(/\b[A-Z][a-z]{3,}\b/g) ?? []).filter(w => !/^(The|From|With|About|Your|Newcastle|United)$/.test(w));
    facts.inbox_words_re = words.length ? alt(words.slice(0, 12)) : null;
  });
  return facts;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const out = process.argv[process.argv.indexOf('--out') + 1];
  if (!process.argv.includes('--out') || !out) { console.error('usage: facts.mjs --out <run dir>'); process.exit(2); }
  if (!process.env.FMCP_CACHE_DIR) { console.error('Set FMCP_CACHE_DIR (an eval cache, never the owner\'s).'); process.exit(2); }
  const reader = await connectReader();
  try {
    const facts = await collectFacts(reader);
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, 'facts.json'), JSON.stringify(facts, null, 2));
    console.log(JSON.stringify(facts, null, 1));
  } finally { await reader.close(); }
}
