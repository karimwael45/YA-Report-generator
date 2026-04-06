#!/usr/bin/env python3
"""
Quick test script to verify all routes are registered
"""
from app import app

print("=" * 60)
print("FLASK ROUTES VERIFICATION")
print("=" * 60)

routes = {}
for rule in app.url_map.iter_rules():
    if rule.endpoint != 'static':
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        routes[rule.rule] = methods

print("\n📋 All registered routes:\n")
for route in sorted(routes.keys()):
    print(f"  {routes[route]:8s} {route}")

print("\n✓ Quiz/Mock specific routes:")
qm_routes = [r for r in routes.keys() if 'qm' in r.lower()]
for r in qm_routes:
    print(f"  ✓ {r}")

if not qm_routes:
    print("  ❌ NO QUIZ/MOCK ROUTES FOUND!")

print("\n" + "=" * 60)
print(f"Total routes: {len(routes)}")
print("=" * 60)
