# Flight-line integration contract

`klayout_connectivity.flight_lines.build_flight_lines` is the pure planning
boundary. The existing plugin remains responsible for obtaining connectivity
and drawing `pya.Marker` objects.

The plugin adapter must:

1. emit one `PinAccessPoint` per usable pin access point, with a stable
   `component_id` (the physical disconnected component), stable `pin_id`, the
   point coordinates, the requested `expected_net`, and the importer-verified
   `actual_net`;
2. set `is_short=True` for any access point in a detected short, and never
   substitute a terminal name for a missing `actual_net`;
3. call `build_flight_lines(points, expected_net)` and create one line marker
   per returned `FlightLine`, using `point_a` and `point_b` as endpoints.

The planner filters wrong-net/short points before graph construction. For `k`
eligible disconnected components it returns exactly `k - 1` lines, choosing
the nearest access-point pair for each component pair and resolving equal
distances by `(component_id, pin_id, x, y)`. The planner imports no `pya`, so
its contract can be tested in ordinary Python.
