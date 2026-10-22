"""Exercise production callbacks with a small Endstone API double.

The real mcbe-binarystream dependency is used. No Bedrock server/world is started.
"""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


class FakePlugin:
    def __init__(self):
        self.logger = types.SimpleNamespace(info=lambda message: None, error=lambda message: None)
        self.registered = None

    def register_events(self, listener):
        self.registered = listener


class FakeItem:
    def __init__(self, type):
        self.type = types.SimpleNamespace(id=type, translation_key=type)


class FakePlayer:
    def __init__(self, name, dimension, main="minecraft:torch", off=None):
        self.name = name
        self.dimension = dimension
        self.location = types.SimpleNamespace(x=0.25, y=64.0, z=0.25)
        self.inventory = types.SimpleNamespace(
            item_in_main_hand=FakeItem(main) if main else None,
            item_in_off_hand=FakeItem(off) if off else None,
        )
        self.is_op = True
        self.locale = "en_US"
        self.packets = []
        self.messages = []
        self.form = None

    def send_packet(self, packet_id, data):
        self.packets.append((packet_id, data))

    def send_message(self, message):
        self.messages.append(message)

    def send_form(self, form):
        self.form = form


class FakeControl:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeBlock:
    def __init__(self, block_type="minecraft:air", runtime_id=10):
        self.type = block_type
        self.data = types.SimpleNamespace(runtime_id=runtime_id)


class FakeDimension:
    def __init__(self, name="Overworld"):
        self.name = name
        self.blocks = {}
        self.reads = []

    def get_block_at(self, x, y, z):
        pos = (x, y, z)
        self.reads.append(pos)
        return self.blocks.get(pos, FakeBlock())

    def set(self, pos, block_type, runtime_id=20):
        self.blocks[pos] = FakeBlock(block_type, runtime_id)


class FakeTask:
    def __init__(self, callback, period):
        self.callback = callback
        self.period = period
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeScheduler:
    def __init__(self):
        self.tasks = []

    def run_task(self, plugin, callback, delay, period):
        task = FakeTask(callback, period)
        self.tasks.append(task)
        return task


class FakeServer:
    def __init__(self):
        self.online_players = []
        self.scheduler = FakeScheduler()
        self.created = []
        self.language = types.SimpleNamespace(translate=lambda key, *args: key)

    def create_block_data(self, block_type, states):
        self.created.append(block_type)
        # Only fake-light IDs may be looked up; restoring must read the world.
        assert block_type.startswith("minecraft:light_block_")
        return types.SimpleNamespace(runtime_id=100 + int(block_type.rsplit("_", 1)[1]))


def install_endstone_double():
    exports = {
        "endstone": {"Player": FakePlayer, "ColorFormat": types.SimpleNamespace(
            YELLOW="", RED="", GREEN="", WHITE="", BOLD="", LIGHT_PURPLE="")},
        "endstone.plugin": {"Plugin": FakePlugin},
        "endstone.level": {"Dimension": FakeDimension},
        "endstone.form": {name: FakeControl for name in ("ModalForm", "Toggle", "TextInput")},
        "endstone.inventory": {"ItemStack": FakeItem},
        "endstone.command": {"Command": object, "CommandSender": object},
        "endstone.event": {
            "event_handler": lambda callback: callback,
            **{name: FakeControl for name in (
                "PlayerJoinEvent", "PlayerQuitEvent", "PlayerDimensionChangeEvent")},
        },
    }
    for name, values in exports.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        sys.modules[name] = module


install_endstone_double()
# Preserve the plugin's existing import-time server-folder convention.
with tempfile.TemporaryDirectory() as folder:
    previous_cwd = os.getcwd()
    try:
        os.chdir(folder)
        Path("plugins").mkdir()
        module = importlib.import_module("endstone_u_dynamic_light.u_dynamic_light")
    finally:
        os.chdir(previous_cwd)


def decode_packet(packet):
    packet_id, data = packet
    values = []
    offset = 0
    for field in range(6):
        value, shift = 0, 0
        while True:
            byte = data[offset]
            offset += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                break
            shift += 7
        values.append((value >> 1) ^ -(value & 1) if field < 3 else value)
    assert offset == len(data)
    assert packet_id == 21
    assert values[4:] == [3, 0]
    return tuple(values[:3]), values[3]


class DynamicLightTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        module.config_data_file_path = str(Path(self.folder.name) / "config.json")
        module.lang_dir = str(Path(self.folder.name) / "lang")
        Path(module.lang_dir).mkdir()
        self.plugin = module.u_dynamic_light()
        self.plugin.server = FakeServer()
        self.dim = FakeDimension()
        self.player = FakePlayer("Alex", self.dim)
        self.plugin.server.online_players = [self.player]

    def packets(self, player=None):
        return [decode_packet(packet) for packet in (player or self.player).packets]

    def test_stationary_first_player_does_not_starve_moving_second_player(self):
        second = FakePlayer("Steve", self.dim)
        second.location.x = 3
        self.plugin.server.online_players.append(second)
        self.plugin.light_manage()
        self.player.packets.clear()
        second.packets.clear()
        second.location.x = 4
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [])
        self.assertEqual(self.packets(second), [((4, 65, 0), 114), ((3, 65, 0), 10)])

    def test_unchanged_updates_are_suppressed_with_bounded_direct_reapply(self):
        self.plugin.light_manage()
        for _ in range(19):
            self.plugin.light_manage()
        self.assertEqual(len(self.packets()), 1)
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((0, 65, 0), 114)] * 2)
        self.assertEqual(self.plugin.server.created, ["minecraft:light_block_14"])

    def test_tall_grass_uses_air_above_without_modifying_plants(self):
        self.dim.set((0, 64, 0), "minecraft:tall_grass")
        self.dim.set((0, 65, 0), "minecraft:tall_grass")
        before = dict(self.dim.blocks)
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((0, 66, 0), 114)])
        self.assertEqual(self.dim.blocks, before)
        self.assertEqual(len(self.dim.reads), 2)

    def test_single_block_grass_keeps_original_head_position(self):
        self.dim.set((0, 64, 0), "minecraft:short_grass")
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((0, 65, 0), 114)])

    def test_other_supported_obstructions_use_air_only(self):
        for block in ("large_fern", "double_plant", "vine", "water", "seagrass", "rose_bush"):
            with self.subTest(block=block):
                self.plugin.recorder.clear()
                self.player.packets.clear()
                self.dim.set((0, 65, 0), "minecraft:" + block)
                self.plugin.light_manage()
                self.assertEqual(self.packets(), [((0, 66, 0), 114)])
                self.assertEqual(self.dim.blocks[(0, 65, 0)].type, "minecraft:" + block)

    def test_two_cell_vertical_ray_has_bounded_read_count(self):
        self.dim.set((0, 65, 0), "minecraft:vine")
        self.dim.set((0, 66, 0), "minecraft:vine")
        self.assertEqual(self.plugin._find_light_position(self.player), [0, 67, 0])
        self.assertEqual(len(self.dim.reads), 3)

    def test_solid_blocks_stop_rays_and_are_never_skipped(self):
        self.dim.set((0, 65, 0), "minecraft:tall_grass")
        for pos in ((0, 66, 0), (1, 65, 0), (-1, 65, 0), (0, 65, 1), (0, 65, -1), (0, 64, 0)):
            self.dim.set(pos, "minecraft:stone")
        self.assertIsNone(self.plugin._find_light_position(self.player))
        self.assertNotIn((0, 67, 0), self.dim.reads)  # Air beyond ceiling is unreachable.
        self.assertLessEqual(len(self.dim.reads), 8)

    def test_enclosed_water_does_not_become_a_fake_light(self):
        self.dim.set((0, 65, 0), "minecraft:water")
        for ray in self.plugin._LIGHT_SEARCH_RAYS:
            for dx, dy, dz in ray:
                self.dim.set((dx, 65 + dy, dz), "minecraft:water")
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [])
        self.assertEqual(len(self.dim.reads), 8)

    def test_unknown_obstruction_fails_closed(self):
        self.dim.set((0, 65, 0), "custom:passable_block")
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [])
        self.assertEqual(len(self.dim.reads), 1)

    def test_movement_places_new_light_before_restoring_current_real_block(self):
        self.plugin.light_manage()
        self.player.packets.clear()
        self.dim.set((0, 65, 0), "minecraft:oak_stairs", 777)
        self.player.location.x = 1
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((1, 65, 0), 114), ((0, 65, 0), 777)])

    def test_world_change_under_stationary_light_restores_new_state(self):
        self.plugin.light_manage()
        self.player.packets.clear()
        self.dim.set((0, 65, 0), "minecraft:stone", 888)
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((0, 65, 0), 888)])
        self.assertNotIn(self.player.name, self.plugin.recorder)

    def test_brightness_change_same_position_does_not_clear_replacement(self):
        self.plugin.light_manage()
        self.player.packets.clear()
        self.player.inventory.item_in_off_hand = FakeItem("minecraft:lantern")
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((0, 65, 0), 115)])

    def test_empty_hands_remove_light_and_do_not_skip_next_player(self):
        self.plugin.light_manage()
        self.player.packets.clear()
        self.player.inventory.item_in_main_hand = None
        second = FakePlayer("Steve", self.dim, main=None, off="minecraft:soul_torch")
        self.plugin.server.online_players.append(second)
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((0, 65, 0), 10)])
        self.assertEqual(self.packets(second), [((0, 65, 0), 110)])

    def test_coincident_sources_remain_independent_self_only_clients(self):
        second = FakePlayer("Steve", self.dim, main="minecraft:lantern")
        self.plugin.server.online_players.append(second)
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((0, 65, 0), 114)])
        self.assertEqual(self.packets(second), [((0, 65, 0), 115)])
        self.player.inventory.item_in_main_hand = None
        second.packets.clear()
        self.plugin.light_manage()
        self.assertEqual(self.packets(second), [])
        self.assertEqual(self.plugin.recorder[second.name]["runtime_id"], 115)

    def test_dimension_change_discards_old_coordinate_without_restore(self):
        self.plugin.light_manage()
        self.player.packets.clear()
        old_dim = self.dim
        self.player.dimension = FakeDimension("Nether")
        self.player.location.x = 8
        self.plugin.on_player_dimension_change(FakeControl(
            player=self.player, from_dimension=old_dim, to_dimension=self.player.dimension))
        self.assertEqual(self.packets(), [])
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((8, 65, 0), 114)])

    def test_dimension_guard_also_handles_transition_before_event(self):
        for moved in (False, True):
            with self.subTest(moved=moved):
                self.plugin.recorder.clear()
                self.player.dimension = self.dim
                self.player.location.x = 0
                self.plugin.light_manage()
                self.player.packets.clear()
                self.player.dimension = FakeDimension("Nether")
                self.player.location.x = 8 if moved else 0
                self.plugin.light_manage()
                self.assertEqual(self.packets(), [((8 if moved else 0, 65, 0), 114)])

    def test_dimension_guard_applies_when_light_is_removed(self):
        self.plugin.light_manage()
        self.player.packets.clear()
        self.player.dimension = FakeDimension("Nether")
        self.player.inventory.item_in_main_hand = None
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [])
        self.assertEqual(self.plugin.recorder, {})

    def test_quit_rejoin_at_same_position_gets_fresh_light(self):
        self.plugin.light_manage()
        self.player.packets.clear()
        event = FakeControl(player=self.player)
        self.plugin.on_player_quit(event)
        self.assertEqual(self.packets(), [])
        self.plugin.on_player_join(event)
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((0, 65, 0), 114)])

    def test_empty_server_prunes_stale_records(self):
        self.plugin.light_manage()
        self.player.packets.clear()
        self.plugin.server.online_players.clear()
        self.plugin.light_manage()
        self.assertEqual(self.plugin.recorder, {})
        self.assertEqual(self.packets(), [])

    def test_disable_cancels_task_and_restores_current_dimension_only(self):
        self.plugin.on_enable()
        self.assertIs(self.plugin.registered, self.plugin)
        self.plugin.light_manage()
        self.player.packets.clear()
        self.dim.set((0, 65, 0), "minecraft:water", 444)
        task = self.plugin._light_task
        self.plugin.on_disable()
        self.assertTrue(task.cancelled)
        self.assertIsNone(self.plugin._light_task)
        self.assertEqual(self.packets(), [((0, 65, 0), 444)])
        self.assertEqual(self.plugin.recorder, {})
        self.plugin.on_disable()  # Idempotent cleanup.
        self.assertEqual(len(self.packets()), 1)

    def submit(self, values):
        self.plugin.on_command(self.player, types.SimpleNamespace(name="ud"), [])
        self.player.form.on_submit(self.player, json.dumps(values))

    def test_interval_form_saves_and_replaces_task_without_clearing_lights(self):
        self.plugin.on_enable()
        self.plugin.light_manage()
        self.player.packets.clear()
        old_task = self.plugin._light_task
        toggles = [False] * len(self.plugin.config_data["item_type_id_allow_in_offhand"])
        self.submit(["3"] + toggles)
        saved = json.loads(Path(module.config_data_file_path).read_text())
        self.assertEqual(saved["refresh_tick"], 3)
        self.assertTrue(old_task.cancelled)
        self.assertEqual(self.plugin._light_task.period, 3)
        self.assertEqual(self.packets(), [])
        self.assertTrue(self.plugin.recorder)
        self.assertTrue(all(not value for value in saved["item_type_id_allow_in_offhand"].values()))
        self.plugin._light_task.callback()
        self.assertEqual(self.packets(), [])

    def test_unchanged_interval_does_not_restart_task(self):
        self.plugin.on_enable()
        task = self.plugin._light_task
        self.submit(["1"] + list(self.plugin.config_data["item_type_id_allow_in_offhand"].values()))
        self.assertIs(self.plugin._light_task, task)
        self.assertFalse(task.cancelled)

    def test_invalid_form_has_no_partial_config_or_scheduler_changes(self):
        self.plugin.on_enable()
        before = json.dumps(self.plugin.config_data)
        task = self.plugin._light_task
        toggles = list(self.plugin.config_data["item_type_id_allow_in_offhand"].values())
        for value in ("0", "-1", "1.5", "no", str(2**64), True, None):
            with self.subTest(value=value):
                self.submit([value] + toggles)
                self.assertEqual(json.dumps(self.plugin.config_data), before)
                self.assertIs(self.plugin._light_task, task)
                self.assertFalse(task.cancelled)
        self.submit(["2"])
        self.player.form.on_submit(self.player, "not json")
        self.assertEqual(json.dumps(self.plugin.config_data), before)

    def test_save_failure_preserves_live_config_task_and_retry_reschedules(self):
        self.plugin.on_enable()
        old_task = self.plugin._light_task
        before = json.dumps(self.plugin.config_data)
        old_bytes = Path(module.config_data_file_path).read_bytes()
        values = ["3"] + list(self.plugin.config_data["item_type_id_allow_in_offhand"].values())
        with mock.patch.object(self.plugin, "save_config_data", side_effect=OSError("disk full")):
            self.submit(values)
        self.assertEqual(json.dumps(self.plugin.config_data), before)
        self.assertEqual(Path(module.config_data_file_path).read_bytes(), old_bytes)
        self.assertIs(self.plugin._light_task, old_task)
        self.assertFalse(old_task.cancelled)
        self.assertTrue(self.plugin.server.scheduler.tasks[-1].cancelled)
        self.assertEqual(self.player.messages[-1], self.plugin.get_text(self.player, "reload.message.fail"))
        self.submit(values)
        self.assertTrue(old_task.cancelled)
        self.assertEqual(self.plugin._light_task.period, 3)
        self.assertEqual(self.plugin.config_data["refresh_tick"], 3)
        self.assertEqual(json.loads(Path(module.config_data_file_path).read_text())["refresh_tick"], 3)

    def test_scheduler_exception_preserves_old_task_and_retry_succeeds(self):
        self.plugin.on_enable()
        old_task = self.plugin._light_task
        old_bytes = Path(module.config_data_file_path).read_bytes()
        values = ["3"] + list(self.plugin.config_data["item_type_id_allow_in_offhand"].values())
        for error in (RuntimeError("scheduler unavailable"), OverflowError("period overflow"),
                      TypeError("native conversion failed")):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(self.plugin.server.scheduler, "run_task", side_effect=error):
                    self.submit(values)
                self.assertIs(self.plugin._light_task, old_task)
                self.assertFalse(old_task.cancelled)
                self.assertEqual(self.plugin.config_data["refresh_tick"], 1)
                self.assertEqual(Path(module.config_data_file_path).read_bytes(), old_bytes)
        self.submit(values)
        self.assertTrue(old_task.cancelled)
        self.assertEqual(self.plugin._light_task.period, 3)

    def test_scheduler_none_result_does_not_commit_config_or_cancel_old_task(self):
        self.plugin.on_enable()
        old_task = self.plugin._light_task
        values = ["3"] + list(self.plugin.config_data["item_type_id_allow_in_offhand"].values())
        with mock.patch.object(self.plugin.server.scheduler, "run_task", return_value=None):
            self.submit(values)
        self.assertIs(self.plugin._light_task, old_task)
        self.assertFalse(old_task.cancelled)
        self.assertEqual(self.plugin.config_data["refresh_tick"], 1)
        self.submit(values)
        self.assertTrue(old_task.cancelled)
        self.assertEqual(self.plugin._light_task.period, 3)

    def test_failed_atomic_config_replace_keeps_previous_file_and_removes_temp(self):
        self.plugin.on_enable()
        old_task = self.plugin._light_task
        old_bytes = Path(module.config_data_file_path).read_bytes()
        values = ["3"] + list(self.plugin.config_data["item_type_id_allow_in_offhand"].values())
        with mock.patch.object(module.os, "replace", side_effect=OSError("replace failed")):
            self.submit(values)
        self.assertEqual(Path(module.config_data_file_path).read_bytes(), old_bytes)
        self.assertEqual(list(Path(self.folder.name).glob(".config-*.tmp")), [])
        self.assertIs(self.plugin._light_task, old_task)
        self.assertFalse(old_task.cancelled)
        self.assertEqual(self.plugin.config_data["refresh_tick"], 1)
        self.submit(values)
        self.assertEqual(self.plugin._light_task.period, 3)

    def test_unchanged_interval_recreates_missing_task(self):
        self.assertIsNone(self.plugin._light_task)
        self.submit(["1"] + list(self.plugin.config_data["item_type_id_allow_in_offhand"].values()))
        self.assertEqual(self.plugin._light_task.period, 1)
        self.assertFalse(self.plugin._light_task.cancelled)

    def test_signed_block_position_packet_golden_including_negative_height(self):
        self.plugin._send_block(self.player, [1, -2, 3], 300)
        self.assertEqual(self.player.packets, [(21, bytes.fromhex("02 03 06 ac 02 03 00"))])

    def test_negative_fractional_coordinates_floor_consistently(self):
        self.player.location.x = -0.2
        self.player.location.y = -2.2
        self.player.location.z = -1.8
        self.plugin.light_manage()
        self.assertEqual(self.packets(), [((-1, -2, -2), 114)])


if __name__ == "__main__":
    unittest.main()
