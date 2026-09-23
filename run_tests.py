import sys
from pathlib import Path

root = Path(__file__).parent
sys.path.insert(0, str(root))

from health_utils import compute_base_health, compute_change_pct, adjust_health

print('Running quick health_utils checks...')
# basic smoke tests
assert compute_base_health([]) == 0
sales = [{"submitted_at": "2026-06-01 10:00:00", "quantity": 5},
         {"submitted_at": "2026-06-02 09:00:00", "quantity": 2}]
print('base health:', compute_base_health(sales))
print('change pct:', compute_change_pct(200, 100))
print('adjusted health:', adjust_health(50, 100, cap_points=15))
print('All quick tests passed')
