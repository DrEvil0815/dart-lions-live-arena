#!/usr/bin/env python3
"""Best-effort discovery of public Darthelfer league fixtures involving Dart Lions.

Uses the public event search in a real browser, without logins or undocumented write APIs.
Only verified league fixtures for Dart Lions I/II/III are added to the feed.
A failed search preserves the last known events (within a short date window).
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

BASE = 'https://www.darthelfer.de'
OUT = Path('auswaerts-events.json')
SEARCH_TERMS = [
    'Dart Lions', 'Gräfenberg', 'Graefenberg', 'TSV 09 Gräfenberg',
    'Hetzles', 'Hopfen Spiggerer', 'Hallerndorf',
    'Wimmelbach', 'Creek Steelers', 'Pettensiedel',
    'Bollnberch', 'Pinzberg', 'Neunkirchen',
]
OWN = re.compile(r'dart\s*lions(?:\s+(?:tsv\s*09\s*)?gr[aä]fenberg)?\s*(?:iii|ii|i|[123])\b', re.I)
UUID = re.compile(r'/public/tournament/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', re.I)
TZ = ZoneInfo('Europe/Berlin')
TODAY = dt.datetime.now(TZ).date()


def name(obj):
    return obj if isinstance(obj, str) else (obj.get('name') or obj.get('bezeichnung') or '') if isinstance(obj, dict) else ''


def event_date(main):
    # Darthelfer has varied field names across event types; do not guess the date.
    for key in ('datum', 'datumVon', 'startDatum', 'datumStart', 'turnierDatum', 'tournamentDate',
                'startDate', 'eventDate', 'beginn', 'start', 'date'):
        raw = str(main.get(key) or '')
        m = re.search(r'20\d{2}-\d{2}-\d{2}', raw)
        if m:
            try: return dt.date.fromisoformat(m.group())
            except ValueError: pass
    return None


def relevant(main):
    if not isinstance(main, dict): return None
    home, away = name(main.get('mannschaftHeim')), name(main.get('mannschaftGast'))
    title = str(main.get('bezeichnung') or '')
    league_type = str(main.get('turniersystem') or '').upper()
    if league_type and league_type != 'LIGASPIELTAG': return None
    if OWN.search(home) and away and not OWN.search(away): opponent = away
    elif OWN.search(away) and home and not OWN.search(home): opponent = home
    elif OWN.search(title) and (' vs ' in title.lower() or ' gegen ' in title.lower()):
        # Date and event can be included, but opponent can't safely be inferred.
        return None
    else: return None
    if re.search(r'abgeschlossen|beendet|finished|closed', str(main.get('tournamentstatus') or ''), re.I):
        return None
    day = event_date(main)
    if day is None or abs((TODAY - day).days) > 1: return None
    return {'day': day.isoformat(), 'opponent': opponent}


def get_links(page):
    urls = page.locator('a[href*="/public/tournament/"]').evaluate_all('(nodes) => nodes.map(a => a.href)')
    matches = set()
    for url in urls:
        if urlparse(url).hostname not in ('darthelfer.de', 'www.darthelfer.de'): continue
        m = UUID.search(url)
        if m: matches.add(m.group(1).lower())
    return matches


def search_ids(page):
    found = set()
    page.goto(BASE + '/public/tournaments', wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(6500)
    found |= get_links(page)
    # Search results are client-side. Query each known club spelling/name.
    locator = page.locator('input[placeholder*="Suche" i]').first
    if locator.count() == 0:
        locator = page.locator('input[type="search"]').first
    if locator.count() == 0:
        print('No public search input detected; collecting only visible links.', file=sys.stderr)
        return found
    for term in SEARCH_TERMS:
        try:
            locator.fill(term, timeout=8000)
            locator.press('Enter', timeout=4000)
            page.wait_for_timeout(1700)
            ids = get_links(page)
            print(f'Search {term!r}: {len(ids)} public tournament links')
            found |= ids
        except Exception as exc:
            print(f'Search {term!r}: {type(exc).__name__}: {exc}', file=sys.stderr)
    return found


def fetch_details(request, id_):
    try:
        resp = request.get(f'{BASE}/api/public/tournament/{id_}', timeout=15000)
        if not resp.ok: return None
        data = resp.json()
        return data.get('turnierMain') or data.get('turnierGruppe') or {}
    except Exception as exc:
        print(f'Detail {id_}: {type(exc).__name__}', file=sys.stderr)
        return None


def main():
    old = []
    if OUT.exists():
        try: old = json.loads(OUT.read_text(encoding='utf-8')).get('events', [])
        except (ValueError, OSError): pass
    discovered = {}
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page(locale='de-DE', timezone_id='Europe/Berlin')
        try: ids = search_ids(page)
        except Exception as exc:
            ids = set()
            errors.append(str(exc))
            print(f'Public search inaccessible: {exc}', file=sys.stderr)
        print(f'Unique candidate IDs: {len(ids)}')
        for id_ in sorted(ids):
            details = fetch_details(page.request, id_)
            meta = relevant(details)
            if meta:
                discovered[id_] = {'id':id_, **meta}
                print('Verified Dart Lions fixture:', id_, meta)
        browser.close()

    # Keep verified candidates for the current local day +/- one day, even on temporary outage.
    for c in old:
        try:
            if abs((TODAY - dt.date.fromisoformat(c['day'])).days) <= 1 and re.fullmatch(r'[0-9a-f-]{36}',c['id']):
                discovered.setdefault(c['id'], c)
        except (KeyError, ValueError, TypeError): continue
    payload = {'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
               'status':'search_error' if errors else 'ok',
               'events':list(discovered.values())}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {OUT} with {len(discovered)} verified fixtures')

if __name__ == '__main__': main()
