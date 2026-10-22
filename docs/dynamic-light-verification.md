# Dynamic-light refactor verification

## Scope and behavior

This change keeps the existing self-only lighting model: a holder receives their
own fake block packets. It does not broadcast lights to other players or modify
server blocks, inventories, recipes, or item brightness values. Two players at
the same coordinate have independent client state.

- Every online player is processed, even when an earlier player's light is unchanged.
- The original head cell is preferred. If it contains a supported plant or water,
  the search checks up to two cells above, the four directly adjacent horizontal
  cells, then the feet cell. It reads at most eight candidates per holder per
  update; an ordinary air-head case reads one. An unknown or solid block stops
  that search direction. Only exact `minecraft:air` can host the fake light.
- The explicit traversal list covers tall/short grass, ferns, tall flowers, vines,
  glow lichen, seagrass/kelp, and water. It is deliberately not a generic
  passability detector: Endstone exposes no collision/passability query. Unknown
  custom blocks, doors, slabs, etc. are not traversed. Fully submerged/enclosed
  holders without nearby air still get no light. Plants and water are never
  replaced, including client-side.
- A moved light is sent before its old coordinate is restored. Brightness changes
  at the same coordinate need one overwrite, with no intervening air packet.
  Restoration reads the current world block's complete runtime ID, preserving
  changes made since the light was placed.
- Unchanged updates send nothing, except a direct reapply about every 20 ticks
  (rounded up to the refresh interval). This recovers a stationary light after
  ordinary block/chunk packets overwrite it, without an off/on cycle. There are
  at most two packets per holder per update; runtime IDs are cached by brightness.
- Join, quit, and dimension-change callbacks discard stale state. Old-dimension
  restoration is never sent to a player in a different dimension. Disable cancels
  the scheduled task and restores online players in the matching dimension.
- A valid `/ud` interval is written to `config.json` and immediately replaces the
  scheduler task. Changing offhand toggles alone does not restart the task.
  Reload stages the replacement before cancelling the old task and atomically
  replaces the JSON file; scheduler/write failures leave the previous live
  settings/task intact, report an error, and allow retrying the same values.

## Automated verification

From the repository root, with Python 3.11–3.15:

```sh
python -m pip install . build
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m build
```

The tests call the actual plugin methods and form/event callbacks through a small
Endstone API double. Packet serialization uses the real `mcbe-binarystream`
2.1.0 dependency, including a byte-level golden for a negative-height signed position.
They cover two players with one stationary, tall/short vegetation, water, bounded
search and solid barriers, brightness changes, coincident self-only sources,
current-state restoration, dimension/quit/rejoin/disable cleanup, refresh interval
saving/rescheduling, failed-save/scheduling retries, and invalid form input. CI builds one universal wheel and source distribution, then installs that exact
wheel and its real dependency on Python 3.11, 3.12, 3.13, 3.14, and 3.15 to run
the same 30 tests. The release is blocked unless every matrix entry passes.
The package declares `>=3.11,<3.16` and pins `mcbe-binarystream==2.1.0` to the
verified serializer version. This Python matrix does not establish that every
Endstone binary distribution embeds each supported Python version.

## Compatibility and remaining in-game checks

The packet layout remains the existing release's signed XYZ `BlockPos`, packet
21, flags 3, main block layer 0. This targets Bedrock protocol 944+ (1.26.14+) and
the reported Endstone 0.11.14 / Bedrock 1.26.52.3 environment. It does not add a
legacy unsigned-Y protocol path. Endstone API calls/events were checked against
v0.11.3 source; `api_version` remains 0.11.

Unit tests and a wheel build do not establish client-rendering behavior. No live
Bedrock client/server test or deployment is included. Before deploying widely,
test with the actual client/server versions:

1. At night, hold a torch and walk/sprint/jump between open ground, one-block
   grass, two-block grass, ferns, tall flowers, and a water edge. Check for visible
   gaps and verify the vegetation/water still looks normal.
2. Keep one holder still while another walks and changes main/offhand brightness.
   Put both at the same coordinate; removing one light should not affect the
   other holder's view.
3. Place/change a real block at the old fake-light coordinate, move away, and
   verify the block appears correctly. Let a normal chunk/block update overwrite
   a stationary light and check that it returns within the reapply period.
4. Change dimensions, reconnect, teleport, and reload/disable the plugin. Check
   for stale light at the old coordinate and unrelated block changes in the new
   dimension.
5. Save `/ud` intervals 1 and 3, confirm the JSON and update cadence, then restart
   and verify the saved value is used.

Nearby reads use Endstone's world API; it does not expose general world-height
bounds or guaranteed unloaded-block behavior. Custom-height dimensions, extreme
world boundaries, custom passable blocks, and client chunk-arrival timing still
need server-specific testing. A displaced air light can have a slightly different
illumination shape from a head-position light; complete flicker removal is not
claimed without that live check.

## API/protocol references

- [Endstone v0.11.3 block bindings](https://github.com/EndstoneMC/endstone/blob/v0.11.3/src/endstone/python/block.cpp)
- [Endstone v0.11.3 scheduler bindings](https://github.com/EndstoneMC/endstone/blob/v0.11.3/src/endstone/python/scheduler.cpp)
- [Dimension/quit event timing](https://github.com/EndstoneMC/endstone/blob/v0.11.3/src/endstone/runtime/bedrock_hooks/script_player_gameplay_handler.cpp)
- [Version-dependent UpdateBlock position schema](https://github.com/EndstoneMC/bedrock-protocol/blob/main/protocol/block.py)
- [Official vanilla block names](https://learn.microsoft.com/en-us/minecraft/creator/commands/enums/block?view=minecraft-bedrock-stable)
