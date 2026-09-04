# KLayout Plugin: Visualize Connectivity Information

> **IIC SDL fork.** This repository is a fork of Martin Jan Köhler's
> [`iic-jku/klayout-connectivity-inspection`](https://github.com/iic-jku/klayout-connectivity-inspection).
> The original plugin, its history, copyright and GPLv3 license are preserved.
> The IIC SDL integration package in this fork was implemented by OpenAI Codex
> in the user-requested `gpt-5.6-sol` / `high reasoning` configuration for
> Michał Wołodźko. It does not claim authorship of the upstream plugin.

<!--
[![Watch the demo](doc/screenshot-demo-video.gif)](https://youtube.com/watch/v=TODO)
-->

* Navigate PCell instances
* Learn about terminals / pins
* Draw ratsnest / flywire for

The SDL v1 extension also loads `<layout>.sdl.json`, adds a Findings tab with
filtering, multi-select, status changes, zoom/highlight/cross-probing, and
renders deterministic flight-lines for `OPEN` findings only. Visibility can
be limited to selected nets, pins or instances. Static imported cells with
`INSTANCE_INFO__*` metadata and preserved terminal labels are included beside
PCells. Layouts without PCells or importer metadata take a non-expanding fast
path so large streamed hierarchies do not freeze the editor.

The complete Polish workflow is available inside KLayout under *Tools* →
*Connectivity Inspection* → *SDL / CAS User Manual...*. It covers every
import field, batch analysis, flight-line modes and the Findings/CAS browser.
   
This add-on can be installed through [KLayout](https://klayout.de) package manager, [see installation instructions here](#installation-instructions)

## Usage

### Tool activation and deactivation

TODO

## Installation using KLayout Package Manager

<a id="installation-instructions"></a>

> **Replacement fork:** `IICSDLConnectivityInspectionPlugin` uses the same
> Python module and menu entry as the upstream `ConnectivityInspectionPlugin`.
> Disable or uninstall the upstream package in a profile before enabling this
> fork; do not run both copies together. The existing `iic-ihp` integration
> already contains this fork's code and does not need a second Salt install.

1. From the main menu, click *Tools*→*Manage Packages* to open the package manager
2. Locate `IIC SDL Connectivity Inspection`, double-click it to select for installation, then click *Apply*
3. Review and close the package installation report
4. Confirm macro execution

The Salt.Mine release is named `IICSDLConnectivityInspectionPlugin` and depends
on the companion `IICSDLNetlistImportPlugin` fork, so the expected-connectivity
import and CAS inspection path are installed together.

## Verification record

- OpenAI Codex ran the automated Python suites, KLayout 0.30.6 batch tests and
  visual GUI checks of the incomplete-import warning, Findings multi-select,
  pin/net population and `OPEN` flight-lines on a copy of a real SG13G2
  project layout.
- Michał Wołodźko independently exercised the workflow on pilot project
  examples and reported the importer-parameter and empty-browser failures that
  this release diagnoses and fixes.

The companion fork is
[`mwolodzk/klayout-netlist-import`](https://github.com/mwolodzk/klayout-netlist-import).

## Technical Details about Connectivity Information

Normally, a layout file (e.g. GDS) does not know about devices / terminals / pins, etc.

To obtain the connectivity
- start from a given netlist: netlist import tool stores the connectivity information
   - our plugin [klayout-netlist-importer plugin](https://github.com/iic-jku/klayout-netlist-import) does this
- given a layout, a LVS script is used to obtain the connectivity information
- PDK PCells mark their pin polygons (device terminal names)

To store this information, we use the KLayout properties system.
Properties are keyed by integer, so we propose a table of dedicated well-known properties:

### PCells Pin Information Properties 

Pin polygons (e.g. device terminals) on the `pin` purpose layers will store information about the pins. 

| Property Key                              | Property Value Type | Purpose                         | Example        | Comment                         |
|-------------------------------------------|---------------------|---------------------------------|----------------|---------------------------------|
| `PIN_INFO__VERSION`                       | String              | Version of Pin Info Record      | `'0.1'`        | for compatibility (migrations)  |
| `PIN_INFO__LIB_NAME`                      | String              | Library Name                    | `'SG13_dev'`   |                                 |
| `PIN_INFO__CELL_NAME`                     | String              | Cell Name                       | `'ntap1'`      |                                 |
| `PIN_INFO__PIN_NAME`                      | String              | Cell Name                       | `'TIE'`        |                                 |
| `PIN_INFO__TERM_NAME`                     | String              | Cell Name                       | `'TIE'`        |                                 |


### Instance Information Properties

#### Example 1: Internal Static Cells

The `NetlistImportPlugin` stores the instance information properties on all instance objects.

| Property Key                              | Property Value Type | Purpose                         | Example           | Comment                         |
|-------------------------------------------|---------------------|---------------------------------|-------------------|---------------------------------|
| `INSTANCE_INFO__VERSION`                  | String              | Version of Instance Info Record | `'1'`             | for compatibility (migrations)  |
| `INSTANCE_INFO__LIB_NAME`                 | String              | Library Name                    | `''`              | empty for internal static cells |
| `INSTANCE_INFO__CELL_NAME`                | String              | Cell Name                       | `'inverter'`      |                                 |
| `INSTANCE_INFO__INSTANCE_NAME`            | String              | Instance Name                   | `'x1'`            |                                 |
| `INSTANCE_INFO__HIERARCHY_PATH`           | String              | Instance FQN                    | `'TOP.x1'`        |                                 |
| `INSTANCE_INFO__ORIGINAL_INSTANCE_PARAMS` | String              | Netlist Instance Params         |                   |                                 |   
| `INSTANCE_INFO__LOCAL_NET_MAP`            | String              | Maps nodes to nets (cell-local) | `'{"nwell": "nwell1", "psub": "psub", "VDD": "VDD", "vin": "vin1", "vout": "vout1", "VSS": "VSS"}'` |            |
| `INSTANCE_INFO__GLOBAL_NET_MAP`           | String              | Maps nodes to globally resolved nets | `'{"nwell": "TOP.nwell1", "psub": "TOP.psub", "VDD": "TOP.VDD", "vin": "TOP.vin1", "vout": "TOP.vout1", "VSS": "TOP.VSS"}'` | resolved top-down by NetlistImportPlugin |

#### Example 2: PCell

| Property Key                              | Property Value Type | Purpose                         | Example           | Comment                         |
|-------------------------------------------|---------------------|---------------------------------|-------------------|---------------------------------|
| `INSTANCE_INFO__VERSION`                  | String              | Version of Instance Info Record | `'1'`             | for compatibility (migrations)  |
| `INSTANCE_INFO__LIB_NAME`                 | String              | Library Name                    | `'SG13_dev'`      | empty for internal static cells |
| `INSTANCE_INFO__CELL_NAME`                | String              | Cell Name                       | `'pmos'`          |                                 |
| `INSTANCE_INFO__INSTANCE_NAME`            | String              | Instance Name                   | `'XM2'`           |                                 |
| `INSTANCE_INFO__HIERARCHY_PATH`           | String              | Instance FQN                    | `'inverter.XM2'`  |                                 |
| `INSTANCE_INFO__ORIGINAL_INSTANCE_PARAMS` | String              | Netlist Instance Params         | `'{"w": "120.0u", "l": "1.0u", "ng": "20", "m": "1", "mm_ok": "1"}'`                  |                                 |   
| `INSTANCE_INFO__LOCAL_NET_MAP`            | String              | Maps nodes to nets (cell-local) | `'{"d": "vout", "g": "vin", "s": "VDD", "b": "nwell"}'` |            |
| `INSTANCE_INFO__GLOBAL_NET_MAP`           | String              | Maps nodes to globally resolved nets | `'{"d": "TOP.vout", "g": "TOP.vin", "s": "TOP.VDD", "b": "TOP.nwell"}'` | resolved top-down by NetlistImportPlugin |
