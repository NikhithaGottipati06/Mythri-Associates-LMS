import sqlite3
import sys

import argparse

parser = argparse.ArgumentParser(description='Diagnose member counts in a branch DB')
parser.add_argument('db', nargs='?', default='branches/gannavaram.db', help='path to branch db')
parser.add_argument('--date', '-d', default='2026-08-18', help='ISO date YYYY-MM-DD to check (default: 2026-08-18)')
args = parser.parse_args()
db = args.db
iso = args.date
conn=sqlite3.connect(db)
conn.row_factory=sqlite3.Row
c=conn.cursor()
expr="substr(date_of_join,7,4)||'-'||substr(date_of_join,4,2)||'-'||substr(date_of_join,1,2)"
print('DB:', db)
print('Total members:', c.execute('SELECT COUNT(*) FROM members').fetchone()[0])
print('Total active members (status=ACTIVE):', c.execute("SELECT COUNT(*) FROM members WHERE COALESCE(status,'ACTIVE')='ACTIVE'").fetchone()[0])
print('Members with date_of_join <= 18/08/2026:', c.execute(f"SELECT COUNT(*) FROM members WHERE {expr} <= ?", (iso,)).fetchone()[0])
print('Members with date_of_join < 18/08/2026:', c.execute(f"SELECT COUNT(*) FROM members WHERE {expr} < ?", (iso,)).fetchone()[0])
print('Members with date_of_join = 18/08/2026:', c.execute(f"SELECT COUNT(*) FROM members WHERE {expr} = ?", (iso,)).fetchone()[0])
print('Members with NULL/empty date_of_join:', c.execute("SELECT COUNT(*) FROM members WHERE date_of_join IS NULL OR trim(date_of_join) = ''").fetchone()[0])

rows = c.execute(f"SELECT id, member_code, full_name, date_of_join, status FROM members WHERE COALESCE(status,'ACTIVE')='ACTIVE' AND ({expr} > ? OR date_of_join IS NULL OR trim(date_of_join)='')", (iso,)).fetchall()
print('\nActive members with future/missing join date:')
for r in rows:
    print(dict(r))

conn.close()
