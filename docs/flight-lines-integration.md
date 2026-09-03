# Flight-line integration contract

`klayout_connectivity.flight_lines.build_flight_lines` is the pure planning
boundary. The SDL producer writes its result to the public
`<layout>.sdl.json` `snapshot.flight_lines` array. The existing plugin loads
that array and remains responsible for drawing `pya.Marker` objects.

The SDL producer must:

1. emit one `PinAccessPoint` per usable pin access point, with a stable
   `component_id` (the physical disconnected component), stable `pin_id`, the
   point coordinates, the requested `expected_net`, and the importer-verified
   `actual_net`;
2. set `is_short=True` for any access point in a detected short, and never
   substitute a terminal name for a missing `actual_net`;
3. call `build_flight_lines(points, expected_net)` and serialize each returned
   line with `line_id`, `expected_net`, `component_a/b`, `pin_a/b`, and
   `start/end`.

The plugin adapter then loads only lines that are backed by an `OPEN` finding
with matching components (and, when supplied, pins). Any line touching a
`SHORT` or `WRONG_NET` component is rejected. It exposes the five pure filter
modes from `flight_overlay.VisibilityMode`: `Off`, `Selected Nets`,
`Selected Pins`, `Selected Instances`, and `All Opens`.

`FlightLineMarkerSeam` is the KLayout-facing lifecycle seam. Its `create` and
`destroy` callbacks are ordinary Python callables, so replacement/refresh
behavior is testable without a GUI; replacing the snapshot with no lines
always destroys old markers.

The planner filters wrong-net/short points before graph construction. For `k`
eligible disconnected components it returns exactly `k - 1` lines, choosing
the nearest access-point pair for each component pair and resolving equal
distances by `(component_id, pin_id, x, y)`. The planner imports no `pya`, so
its contract can be tested in ordinary Python.
