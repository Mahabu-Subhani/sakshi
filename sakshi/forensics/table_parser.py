# FILE: sakshi/forensics/table_parser.py
# Written by Gemini 4 Argon (round 2 of the v1.0 design debate). Reviewed, fixed and integrated by Claude.
# Claude's review fixes are marked "REVIEW FIX".
"""Constraint-guided bank-statement table parser.

Column roles are not trusted from layout alone: every plausible hypothesis
(debit|credit|balance, credit|debit|balance, amount + Dr/Cr marker, signed
amount) is scored against the running-balance equation and the best one wins.
OCR self-healing follows the RE-READ, NEVER REWRITE rule: a cell changes only
if an independent second read of its pixels produces a value that makes this
row's and the next row's balance equations hold.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

import numpy as np

try:
    from ..models import Line, Page, Word
except (ImportError, ValueError):
    @dataclass
    class Word:
        text: str
        bbox: tuple
        conf: float = 1.0
        line_id: int = 0
        font: str = ''
        size: float = 0.0
        source: str = 'ocr'

    @dataclass
    class Line:
        id: int
        words: list
        bbox: tuple

    @dataclass
    class Page:
        index: int
        image_path: str
        width: int
        height: int
        words: list = field(default_factory=list)
        lines: list = field(default_factory=list)

MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12
}

HEADER_SYNONYMS = {
    'date': ['txn date', 'tran date', 'value date', 'transaction date', 'date'],
    'narration': ['narration', 'description', 'particulars', 'details', 'remarks'],
    'ref': ['chq/ref no', 'cheque no', 'ref no', 'chq no', 'reference', 'utr'],
    'drcr': ['dr/cr', 'cr/dr', 'type', 'dr / cr'],
    'debit': ['withdrawal', 'withdrawals', 'debit', 'dr amount', 'dr.', 'dr'],
    'credit': ['deposit', 'deposits', 'credit', 'cr amount', 'cr.', 'cr'],
    'amount': ['amount', 'txn amount', 'tran amount'],
    'balance': ['closing balance', 'running balance', 'balance', 'bal'],
}

NUMERIC_ROLES = {'debit', 'credit', 'amount', 'balance'}

DATE_NUM_RE = re.compile(r'^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$')
DATE_ISO_RE = re.compile(r'^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$')
DATE_MON_RE = re.compile(r'^(\d{1,2})[/\-.]([A-Za-z]{3,4})[/\-.](\d{2,4})$')
DAY_RE = re.compile(r'^(\d{1,2})$')
MON_RE = re.compile(r'^([A-Za-z]{3,4})[,.\-]?$')
YEAR_RE = re.compile(r'^(\d{2,4})$')

AMT_CLEAN_RE = re.compile(
    r'^(?:Rs\.?|INR|₹)?\s*([+-])?\s*(?:Rs\.?|INR|₹)?\s*'
    r'([0-9][0-9,]*(?:\.\d{1,2})?)'
    r'\s*(?:/-|-)?\s*(?:\(?(Dr|Cr|DR|CR)\.?\)?)?$',
    re.IGNORECASE
)
DRCR_TOKEN_RE = re.compile(r'^\(?(Dr|Cr|DR|CR)\.?\)?$', re.IGNORECASE)


def _union_bbox(bboxes):
    return (min(b[0] for b in bboxes), min(b[1] for b in bboxes),
            max(b[2] for b in bboxes), max(b[3] for b in bboxes))


def _x_center(bbox) -> float:
    return 0.5 * (bbox[0] + bbox[2])


def _fix_year(y: int) -> int:
    return 2000 + y if y < 100 else y


def _make_iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return datetime(_fix_year(y), m, d).strftime('%Y-%m-%d')
    except ValueError:
        return None


def _try_parse_date_tokens(words) -> Optional[tuple[dict, int]]:
    if not words:
        return None
    w0 = words[0].text.strip().rstrip(',')
    m = DATE_ISO_RE.match(w0)
    if m:
        iso = _make_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            return ({'raw': words[0].text, 'iso': iso, 'bbox': words[0].bbox, 'conf': float(words[0].conf)}, 1)
    m = DATE_NUM_RE.match(w0)
    if m:
        iso = _make_iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if iso:
            return ({'raw': words[0].text, 'iso': iso, 'bbox': words[0].bbox, 'conf': float(words[0].conf)}, 1)
    m = DATE_MON_RE.match(w0)
    if m and m.group(2).lower() in MONTHS:
        iso = _make_iso(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        if iso:
            return ({'raw': words[0].text, 'iso': iso, 'bbox': words[0].bbox, 'conf': float(words[0].conf)}, 1)
    if len(words) >= 3:
        d_m = DAY_RE.match(words[0].text.strip())
        m_m = MON_RE.match(words[1].text.strip())
        y_m = YEAR_RE.match(words[2].text.strip().rstrip(','))
        if d_m and m_m and y_m and m_m.group(1).lower() in MONTHS:
            iso = _make_iso(int(y_m.group(1)), MONTHS[m_m.group(1).lower()], int(d_m.group(1)))
            if iso:
                toks = words[:3]
                return ({'raw': ' '.join(w.text for w in toks), 'iso': iso,
                         'bbox': _union_bbox([w.bbox for w in toks]),
                         'conf': float(min(w.conf for w in toks))}, 3)
    return None


def _detect_headers(pages) -> Optional[dict]:
    for page in pages:
        for line in page.lines:
            if not line.words:
                continue
            n = len(line.words)
            used = [False] * n
            found = {}
            role_order = ['drcr', 'date', 'narration', 'ref', 'debit', 'credit', 'amount', 'balance']
            for role in role_order:
                syns = sorted(HEADER_SYNONYMS[role], key=len, reverse=True)
                for syn in syns:
                    syn_toks = syn.split()
                    k = len(syn_toks)
                    matched = False
                    for i in range(n - k + 1):
                        if any(used[i:i + k]):
                            continue
                        window = [re.sub(r'[^a-z0-9/]', '', w.text.lower()) for w in line.words[i:i + k]]
                        target = [re.sub(r'[^a-z0-9/]', '', t.lower()) for t in syn_toks]
                        if window == target:
                            for j in range(i, i + k):
                                used[j] = True
                            b = _union_bbox([w.bbox for w in line.words[i:i + k]])
                            found[role] = (b[0], b[2])
                            matched = True
                            break
                    if matched:
                        break
            has_date_or_narr = ('date' in found) or ('narration' in found)
            has_num = any(r in found for r in NUMERIC_ROLES)
            if len(found) >= 3 and has_date_or_narr and has_num:
                sorted_roles = sorted(found.items(), key=lambda kv: 0.5 * (kv[1][0] + kv[1][1]))
                bands = {}
                for idx, (role, (x0, x1)) in enumerate(sorted_roles):
                    left = 0.0 if idx == 0 else 0.5 * (sorted_roles[idx - 1][1][1] + x0)
                    right = float(page.width or 10000) if idx == len(sorted_roles) - 1 else 0.5 * (x1 + sorted_roles[idx + 1][1][0])
                    bands[role] = (left, right)
                return bands
    return None


def _role_for_x(x: float, bands) -> Optional[str]:
    if not bands:
        return None
    for role, (x0, x1) in bands.items():
        if x0 <= x <= x1:
            return role
    return None


def _parse_amount_str(text: str, in_num_band: bool):
    s = text.strip()
    m = AMT_CLEAN_RE.match(s)
    if not m:
        return None
    sign, num_part, drcr = m.group(1), m.group(2), m.group(3)
    has_comma = ',' in num_part
    has_two_dec = bool(re.search(r'\.\d{2}$', num_part))
    if not in_num_band and not (has_comma or has_two_dec):
        return None
    clean_digits = num_part.replace(',', '')
    if not has_comma and '.' not in num_part and len(clean_digits) >= 9:
        return None  # long digit runs are references (UPI/IMPS/cheque), not money
    try:
        val = float(clean_digits)
    except ValueError:
        return None
    return val, sign, (drcr.upper() if drcr else None)


def _classify_special_kind(text: str, has_date: bool) -> Optional[str]:
    low = text.lower()
    if re.search(r'\b(opening\s+balance|op\.?\s*bal)\b', low):
        return 'opening'
    if re.search(r'(\bb\s*/\s*f\b|\bbrought\s+forward\b)', low):
        return 'brought_forward'
    if re.search(r'(\bc\s*/\s*f\b|\bcarried\s+forward\b)', low):
        return 'carried_forward'
    if not has_date and re.search(r'\b(total|closing\s+balance|grand\s+total)\b', low):
        return 'total'
    return None


def _is_header_line(line, bands) -> bool:
    low_words = [re.sub(r'[^a-z/]', '', w.text.lower()) for w in line.words]
    hits = 0
    for syns in HEADER_SYNONYMS.values():
        if any(s in ' '.join(low_words) for s in syns):
            hits += 1
    return hits >= 3 and _try_parse_date_tokens(line.words) is None


def _extract_line_tokens(line, bands):
    words = list(line.words)
    date_info = None
    idx = 0
    if words:
        first_role = _role_for_x(_x_center(words[0].bbox), bands)
        if first_role in (None, 'date', 'narration'):
            res = _try_parse_date_tokens(words)
            if res:
                date_info, idx = res
    amt_tokens, desc_words, drcr_markers = [], [], []
    i = idx
    while i < len(words):
        w = words[i]
        xc = _x_center(w.bbox)
        role = _role_for_x(xc, bands)
        if role == 'date' and date_info is None:
            res = _try_parse_date_tokens(words[i:])
            if res:
                date_info, consumed = res
                i += consumed
                continue
        m_drcr = DRCR_TOKEN_RE.match(w.text.strip())
        if m_drcr and role in ('drcr', 'amount', 'debit', 'credit', 'balance'):
            drcr_markers.append((m_drcr.group(1).upper(), w))
            i += 1
            continue
        in_num = role in NUMERIC_ROLES
        parsed = _parse_amount_str(w.text, in_num) if role != 'narration' else None
        if parsed is not None:
            val, sign, drcr = parsed
            tok_words = [w]
            if drcr is None and i + 1 < len(words):
                nxt = DRCR_TOKEN_RE.match(words[i + 1].text.strip())
                if nxt:
                    drcr = nxt.group(1).upper()
                    tok_words.append(words[i + 1])
                    i += 1
            ub = _union_bbox([tw.bbox for tw in tok_words])
            amt_tokens.append({'raw': ' '.join(tw.text for tw in tok_words), 'value': val, 'sign': sign,
                               'drcr': drcr, 'role': role, 'bbox': ub,
                               'conf': float(min(tw.conf for tw in tok_words)), 'x': _x_center(ub)})
        else:
            desc_words.append(w)
        i += 1
    return date_info, desc_words, amt_tokens, drcr_markers


def _make_cell(tok: dict) -> dict:
    return {'raw': tok['raw'], 'value': float(tok['value']), 'bbox': tok['bbox'], 'conf': float(tok['conf'])}


def _assign_cells_for_hypothesis(raw_row: dict, hyp: str, bands):
    amts = sorted(raw_row['amts'], key=lambda a: a['x'])
    kind = raw_row['kind']
    if not amts:
        return None, None, None
    if kind in ('opening', 'brought_forward', 'carried_forward'):
        return None, None, _make_cell(amts[-1])

    bal_tok = None
    other_toks = []
    for a in amts:
        if a['role'] == 'balance':
            bal_tok = a
        else:
            other_toks.append(a)
    if bal_tok is None and amts:
        bal_tok = amts[-1]
        other_toks = amts[:-1]

    bal_cell = _make_cell(bal_tok) if bal_tok else None
    if bal_cell is not None and bal_tok.get('drcr') == 'DR' and hyp != 'amount_drcr_balance':
        bal_cell['value'] = -bal_cell['value']  # REVIEW FIX: a balance marked Dr is an overdraft
    if not other_toks:
        return None, None, bal_cell

    deb_cell = cred_cell = None
    if hyp in ('debit_credit_balance', 'credit_debit_balance'):
        first_is_debit = (hyp == 'debit_credit_balance')
        if len(other_toks) >= 2:
            t0, t1 = other_toks[0], other_toks[1]
            if first_is_debit:
                deb_cell, cred_cell = _make_cell(t0), _make_cell(t1)
            else:
                cred_cell, deb_cell = _make_cell(t0), _make_cell(t1)
        else:
            t = other_toks[0]
            if t['role'] in ('debit', 'credit'):
                # REVIEW FIX: the original condition dropped single credit tokens under every hypothesis.
                # Header-labelled tokens follow their label; the swapped hypothesis tests mislabelled headers.
                as_debit = (t['role'] == 'debit') == first_is_debit
                if as_debit:
                    deb_cell = _make_cell(t)
                else:
                    cred_cell = _make_cell(t)
            elif bands and ('debit' in bands and 'credit' in bands):
                d_mid = 0.5 * sum(bands['debit'])
                c_mid = 0.5 * sum(bands['credit'])
                if abs(t['x'] - d_mid) <= abs(t['x'] - c_mid):
                    deb_cell = _make_cell(t) if first_is_debit else None
                    cred_cell = None if first_is_debit else _make_cell(t)
                else:
                    cred_cell = _make_cell(t) if first_is_debit else None
                    deb_cell = None if first_is_debit else _make_cell(t)
            else:
                if first_is_debit:
                    deb_cell = _make_cell(t)
                else:
                    cred_cell = _make_cell(t)
    elif hyp == 'amount_drcr_balance':
        t = other_toks[0]
        marker = t['drcr'] or (raw_row['drcr'][0][0] if raw_row['drcr'] else None)
        if marker == 'CR':
            cred_cell = _make_cell(t)
        else:
            deb_cell = _make_cell(t)
    elif hyp == 'signed_amount_balance':
        t = other_toks[0]
        if t['sign'] == '-':
            deb_cell = _make_cell(t)
        else:
            cred_cell = _make_cell(t)
    return deb_cell, cred_cell, bal_cell


def _evaluate_fit(rows):
    prev_bal = None
    checks = passed = 0
    for r in rows:
        if r['kind'] in ('opening', 'brought_forward') and r['balance'] is not None:
            prev_bal = r['balance']['value']
            continue
        if r['kind'] != 'txn' or r['balance'] is None:
            continue
        cur_bal = r['balance']['value']
        if prev_bal is not None and (r['debit'] is not None or r['credit'] is not None):
            d = r['debit']['value'] if r['debit'] else 0.0
            c = r['credit']['value'] if r['credit'] else 0.0
            checks += 1
            if abs((prev_bal - d + c) - cur_bal) <= 0.51:
                passed += 1
        prev_bal = cur_bal
    return (passed / checks if checks > 0 else 0.0), passed, checks


def parse_statement(pages, reocr: Optional[Callable] = None) -> dict:
    notes = []
    bands = _detect_headers(pages)
    if bands is None:
        notes.append('No explicit header line detected; using geometric fallback.')

    raw_rows = []
    seen_txn = False
    for page in pages:
        for line in page.lines:
            if not line.words or _is_header_line(line, bands):
                continue
            full_text = ' '.join(w.text for w in line.words).strip()
            if re.search(r'\bpage\s+\d+(\s+of\s+\d+)?\b|synthetic specimen|computer generated', full_text, re.I) \
                    and not _try_parse_date_tokens(line.words):
                continue  # REVIEW FIX: page footers and banners are not narration continuations
            date_info, desc_words, amt_tokens, drcr_markers = _extract_line_tokens(line, bands)
            sp_kind = _classify_special_kind(full_text, date_info is not None)
            if sp_kind == 'opening' and seen_txn and date_info is None:
                sp_kind = 'total'  # REVIEW FIX: an 'Opening Balance:' line in a closing summary is not a chain start
            if sp_kind is not None:
                raw_rows.append({'page': page.index, 'bbox': line.bbox, 'kind': sp_kind, 'date': date_info,
                                 'desc': ' '.join(w.text for w in desc_words).strip() or full_text,
                                 'amts': amt_tokens, 'drcr': drcr_markers})
            elif date_info is not None:
                seen_txn = True
                raw_rows.append({'page': page.index, 'bbox': line.bbox, 'kind': 'txn', 'date': date_info,
                                 'desc': ' '.join(w.text for w in desc_words).strip(),
                                 'amts': amt_tokens, 'drcr': drcr_markers})
            else:
                if raw_rows and raw_rows[-1]['kind'] == 'txn':
                    prev = raw_rows[-1]
                    cont_text = ' '.join(w.text for w in desc_words).strip()
                    if cont_text:
                        prev['desc'] = (prev['desc'] + ' ' + cont_text).strip()
                    prev['bbox'] = _union_bbox([prev['bbox'], line.bbox])
                    if not prev['amts'] and amt_tokens:
                        num_band_amts = [a for a in amt_tokens if a['role'] in NUMERIC_ROLES]
                        if num_band_amts:
                            prev['amts'].extend(num_band_amts)
                            prev['drcr'].extend(drcr_markers)

    hyps = ['debit_credit_balance', 'credit_debit_balance', 'amount_drcr_balance', 'signed_amount_balance']
    has_drcr = any(r['drcr'] or any(a['drcr'] for a in r['amts']) for r in raw_rows)
    has_sign = any(any(a['sign'] in ('+', '-') for a in r['amts']) for r in raw_rows)
    if bands:
        if 'amount' in bands and ('drcr' in bands or has_drcr) and 'debit' not in bands:
            hyps = ['amount_drcr_balance'] + [h for h in hyps if h != 'amount_drcr_balance']
        elif 'debit' in bands and 'credit' in bands:
            if bands['credit'][0] < bands['debit'][0]:
                hyps = ['credit_debit_balance'] + [h for h in hyps if h != 'credit_debit_balance']
    if not has_drcr and (not bands or 'drcr' not in bands):
        hyps = [h for h in hyps if h != 'amount_drcr_balance'] + ['amount_drcr_balance']
    if not has_sign:
        hyps = [h for h in hyps if h != 'signed_amount_balance'] + ['signed_amount_balance']

    best_layout, best_rows, best_fit, best_checks = 'unknown', [], -1.0, 0
    for hyp in hyps:
        cand_rows = []
        for rr in raw_rows:
            deb, cred, bal = _assign_cells_for_hypothesis(rr, hyp, bands)
            cand_rows.append({'page': rr['page'], 'bbox': rr['bbox'], 'kind': rr['kind'], 'date': rr['date'],
                              'description': rr['desc'], 'debit': deb, 'credit': cred, 'balance': bal})
        fit, passed, checks = _evaluate_fit(cand_rows)
        if fit > best_fit:
            best_fit, best_layout, best_rows, best_checks = fit, hyp, cand_rows, checks

    healed = []
    if reocr is not None and best_rows:
        txn_indices = [i for i, r in enumerate(best_rows) if r['kind'] == 'txn' and r['balance'] is not None]

        def _prev_bal_for(pos: int):
            idx = txn_indices[pos]
            if pos > 0:
                return best_rows[txn_indices[pos - 1]]['balance']['value']
            for j in range(idx - 1, -1, -1):
                if best_rows[j]['kind'] in ('opening', 'brought_forward') and best_rows[j]['balance']:
                    return best_rows[j]['balance']['value']
            return None

        def _trans_ok(pos: int) -> bool:
            if pos < 0 or pos >= len(txn_indices):
                return True
            pb = _prev_bal_for(pos)
            if pb is None:
                return True
            r = best_rows[txn_indices[pos]]
            d = r['debit']['value'] if r['debit'] else 0.0
            c = r['credit']['value'] if r['credit'] else 0.0
            return abs((pb - d + c) - r['balance']['value']) <= 0.51

        for pos, r_idx in enumerate(txn_indices):
            if _trans_ok(pos):
                continue
            row = best_rows[r_idx]
            for field_name in ('debit', 'credit', 'balance'):
                cell = row.get(field_name)
                if cell is None:
                    continue
                new_text, new_conf = reocr(row['page'], cell['bbox'])
                parsed = _parse_amount_str(new_text, True)
                if parsed is None:
                    continue
                new_val = float(parsed[0])
                if abs(new_val - cell['value']) <= 1e-6:
                    continue
                old_cell = copy.deepcopy(cell)
                row[field_name] = {'raw': new_text, 'value': new_val, 'bbox': cell['bbox'], 'conf': float(new_conf)}
                if _trans_ok(pos) and _trans_ok(pos + 1):
                    healed.append({'row': r_idx, 'field': field_name, 'first_read': old_cell['raw'],
                                   'second_read': new_text, 'value': new_val, 'conf': float(new_conf)})
                    break
                row[field_name] = old_cell
        best_fit, _, best_checks = _evaluate_fit(best_rows)

    if best_checks == 0 or best_fit < 0.5:
        notes.append(f'Low transition fit ({best_fit:.2f}); layout or balance continuity uncertain.')
        if best_checks == 0 and bands is None:
            best_layout = 'unknown'

    return {'layout': best_layout, 'rows': best_rows, 'transition_fit': float(max(0.0, best_fit)),
            'healed': healed, 'notes': notes}


def _row_date(r: dict):
    if r.get('date') and r['date'].get('iso'):
        try:
            return datetime.strptime(r['date']['iso'], '%Y-%m-%d')
        except ValueError:
            return None
    return None


def _norm_counterparty(desc: str) -> str:
    s = re.sub(r'\d+', '', desc.upper())
    return re.sub(r'[^A-Z]+', ' ', s).strip()


def behavioral_checks(rows: list) -> list:
    findings = []
    txn_rows = [(i, r, _row_date(r)) for i, r in enumerate(rows) if r.get('kind') == 'txn']

    # (a) interest_implied_balance
    int_re = re.compile(r'(\bINT\b|\bINTEREST\b|INT\.PD|INT\s+CREDIT)', re.IGNORECASE)
    for idx, r, dt in txn_rows:
        if r.get('credit') and r['credit']['value'] > 0 and int_re.search(r.get('description', '')):
            interest = r['credit']['value']
            min_imp = interest * 4.0 / 0.04
            max_imp = interest * 4.0 / 0.025
            if dt is not None:
                window_bals = [r2['balance']['value'] for _, r2, dt2 in txn_rows
                               if dt2 is not None and timedelta(days=0) <= (dt - dt2) <= timedelta(days=92) and r2.get('balance')]
            else:
                window_bals = [r2['balance']['value'] for i2, r2, _ in txn_rows if i2 <= idx and r2.get('balance')]
            if window_bals:
                mean_bal = float(np.mean(window_bals))
                if mean_bal > 3.0 * max_imp:
                    findings.append({
                        'check': 'interest_implied_balance',
                        'title': 'Displayed balance far exceeds the balance implied by the interest credit',
                        'detail': (f"Interest credit of {interest:,.2f} implies a quarterly average balance between "
                                   f"{min_imp:,.0f} and {max_imp:,.0f}, but the statement's mean balance over the prior "
                                   f"92 days is {mean_bal:,.0f}. Innocent explanations: sweep or FD-linked accounts, "
                                   "interest for a different period, or a recent large inflow."),
                        'rows': [idx], 'tier_hint': 'INCONSISTENCY'})

    # (b) salary_pass_through
    sal_re = re.compile(r'\b(SALARY|SAL|PAYROLL)\b', re.IGNORECASE)
    excl_re = re.compile(r'\b(EMI|LOAN|NACH|ECS|SIP)\b', re.IGNORECASE)
    for idx, r, dt in txn_rows:
        if r.get('credit') and r['credit']['value'] > 0 and sal_re.search(r.get('description', '')) and dt is not None:
            sal_amt = r['credit']['value']
            by_cp = {}
            for idx2, r2, dt2 in txn_rows:
                if idx2 <= idx or dt2 is None:
                    continue
                if timedelta(days=0) <= (dt2 - dt) <= timedelta(days=1) and r2.get('debit') and r2['debit']['value'] > 0:
                    desc2 = r2.get('description', '')
                    if excl_re.search(desc2):
                        continue
                    cp = _norm_counterparty(desc2)
                    if cp:
                        by_cp.setdefault(cp, []).append((idx2, r2['debit']['value']))
            for cp, items in by_cp.items():
                tot_deb = sum(v for _, v in items)
                if tot_deb >= 0.8 * sal_amt:
                    findings.append({
                        'check': 'salary_pass_through',
                        'title': 'Salary credit passed straight through to one counterparty',
                        'detail': (f"Salary credit of {sal_amt:,.2f} was followed within 1 day by debit(s) totalling "
                                   f"{tot_deb:,.2f} to '{cp}'. Innocent explanations: rent, or a transfer to the "
                                   "applicant's own account elsewhere."),
                        'rows': [idx] + [i for i, _ in items], 'tier_hint': 'OBSERVATION'})
                    break

    # (c) same_amount_in_out
    paired = set()
    for i_pos, (idx1, r1, dt1) in enumerate(txn_rows):
        if dt1 is None:
            continue
        for idx2, r2, dt2 in txn_rows[i_pos + 1:]:
            if dt2 is None or abs((dt2 - dt1).total_seconds()) > 48 * 3600:
                continue
            c1 = r1['credit']['value'] if r1.get('credit') else None
            d1 = r1['debit']['value'] if r1.get('debit') else None
            c2 = r2['credit']['value'] if r2.get('credit') else None
            d2 = r2['debit']['value'] if r2.get('debit') else None
            match_val = None
            if c1 is not None and d2 is not None and c1 >= 10000 and abs(c1 - d2) < 0.01:
                match_val = c1
            elif d1 is not None and c2 is not None and d1 >= 10000 and abs(d1 - c2) < 0.01:
                match_val = d1
            if match_val is not None and (idx1, idx2) not in paired:
                paired.add((idx1, idx2))
                findings.append({
                    'check': 'same_amount_in_out',
                    'title': f'Same amount ({match_val:,.2f}) came in and went out within 48 hours',
                    'detail': (f"Equal inflow and outflow of {match_val:,.2f} within 48 hours can be used to inflate "
                               "a balance temporarily. Innocent explanations: merchant refund, reversal, self-transfer."),
                    'rows': [idx1, idx2], 'tier_hint': 'OBSERVATION'})
    return findings


if __name__ == '__main__':
    def _mk_line(lid, y, specs):
        words = [Word(text=t, bbox=(x0, y, x1, y + 12), conf=0.95, line_id=lid) for t, x0, x1 in specs]
        return Line(id=lid, words=words, bbox=_union_bbox([w.bbox for w in words]))

    # Test 1: single-amount Dr/Cr layout + 'DD Mon YYYY' dates
    lines_drcr = [
        _mk_line(0, 10, [('Date', 10, 60), ('Narration', 100, 250), ('Amount', 350, 420), ('Dr/Cr', 450, 490), ('Balance', 520, 600)]),
        _mk_line(1, 30, [('01', 10, 25), ('Jan', 28, 50), ('2024', 53, 85), ('Opening', 100, 160), ('Balance', 165, 220), ('10,000.00', 520, 590)]),
        _mk_line(2, 50, [('02', 10, 25), ('Jan', 28, 50), ('2024', 53, 85), ('ATM', 100, 130), ('WDL', 135, 170), ('2,000.00', 350, 410), ('Dr', 455, 475), ('8,000.00', 520, 590)]),
        _mk_line(3, 70, [('05', 10, 25), ('Jan', 28, 50), ('2024', 53, 85), ('NEFT', 100, 140), ('IN', 145, 165), ('5,000.00', 350, 410), ('Cr', 455, 475), ('13,000.00', 520, 590)]),
    ]
    p_drcr = Page(index=0, image_path='p0.png', width=700, height=1000, words=[w for l in lines_drcr for w in l.words], lines=lines_drcr)
    res1 = parse_statement([p_drcr])
    assert res1['layout'] == 'amount_drcr_balance', res1
    assert res1['transition_fit'] == 1.0
    assert res1['rows'][0]['kind'] == 'opening'
    assert res1['rows'][1]['date']['iso'] == '2024-01-02'
    assert res1['rows'][1]['debit']['value'] == 2000.0 and res1['rows'][1]['credit'] is None
    assert res1['rows'][2]['credit']['value'] == 5000.0 and res1['rows'][2]['debit'] is None

    # Test 2: Debit/Credit/Balance layout, B/F row, 2-line narration, 12-digit UPI ref, OCR heal, unhealable forgery
    lines_dcb = [
        _mk_line(0, 10, [('Date', 10, 60), ('Particulars', 100, 260), ('Withdrawal', 340, 420), ('Deposit', 440, 510), ('Balance', 540, 620)]),
        _mk_line(1, 30, [('B/F', 100, 130), ('50,000.00', 540, 610)]),
        _mk_line(2, 50, [('10-01-2024', 10, 80), ('UPI/401234567890/Merchant', 100, 280), ('1,000.00', 345, 410), ('49,000.00', 540, 610)]),
        _mk_line(3, 65, [('Payment', 100, 160), ('for', 165, 190), ('groceries', 195, 260)]),
        _mk_line(4, 85, [('11-01-2024', 10, 80), ('IMPS/998877665544/Rent', 100, 270), ('7,000.00', 345, 410), ('47,000.00', 540, 610)]),
        _mk_line(5, 105, [('12-01-2024', 10, 80), ('POS', 100, 135), ('500.00', 345, 400), ('46,500.00', 540, 610)]),
        _mk_line(6, 125, [('13-01-2024', 10, 80), ('FORGED', 100, 160), ('1,000.00', 345, 410), ('40,500.00', 540, 610)]),
        # REVIEW FIX test: a single credit token in the Deposit band must be kept
        _mk_line(7, 145, [('14-01-2024', 10, 80), ('SALARY', 100, 160), ('9,500.00', 445, 505), ('50,000.00', 540, 610)]),
    ]
    p_dcb = Page(index=0, image_path='p1.png', width=700, height=1000, words=[w for l in lines_dcb for w in l.words], lines=lines_dcb)

    def fake_reocr(page_idx, bbox):
        if bbox == (345, 85, 410, 97):
            return ('2,000.00', 0.99)
        if bbox == (345, 125, 410, 137):
            return ('1,000.00', 0.99)
        return ('', 0.0)

    res2 = parse_statement([p_dcb], reocr=fake_reocr)
    assert res2['layout'] == 'debit_credit_balance', res2
    assert res2['rows'][0]['kind'] == 'brought_forward'
    assert 'Payment for groceries' in res2['rows'][1]['description']
    assert res2['rows'][1]['debit']['value'] == 1000.0 and res2['rows'][1]['credit'] is None
    assert len(res2['healed']) == 1 and res2['healed'][0]['first_read'] == '7,000.00' and res2['healed'][0]['value'] == 2000.0
    assert res2['rows'][2]['debit']['value'] == 2000.0
    assert res2['rows'][4]['debit']['value'] == 1000.0  # forged row untouched
    assert res2['rows'][5]['credit']['value'] == 9500.0, res2['rows'][5]

    # Test 3: behavioral checks
    b_rows = [
        {'kind': 'txn', 'date': {'iso': '2024-01-01'}, 'description': 'SALARY JAN', 'debit': None, 'credit': {'value': 100000.0}, 'balance': {'value': 500000.0}},
        {'kind': 'txn', 'date': {'iso': '2024-01-02'}, 'description': 'NEFT TO BROKER 12345', 'debit': {'value': 85000.0}, 'credit': None, 'balance': {'value': 415000.0}},
        {'kind': 'txn', 'date': {'iso': '2024-02-10'}, 'description': 'UPI IN', 'debit': None, 'credit': {'value': 25000.0}, 'balance': {'value': 440000.0}},
        {'kind': 'txn', 'date': {'iso': '2024-02-11'}, 'description': 'UPI OUT', 'debit': {'value': 25000.0}, 'credit': None, 'balance': {'value': 415000.0}},
        {'kind': 'txn', 'date': {'iso': '2024-03-31'}, 'description': 'INT.PD', 'debit': None, 'credit': {'value': 100.0}, 'balance': {'value': 415100.0}},
    ]
    checks = {c['check'] for c in behavioral_checks(b_rows)}
    assert checks == {'interest_implied_balance', 'salary_pass_through', 'same_amount_in_out'}, checks
    print("table_parser self-test PASS")
