import json
import math
import os
import tempfile

from binarystream import BinaryStream

from endstone_u_dynamic_light.lang import load_lang

from endstone import Player, ColorFormat

from endstone.plugin import Plugin
from endstone.level import Dimension
from endstone.form import ModalForm, Toggle, TextInput
from endstone.inventory import ItemStack
from endstone.command import Command, CommandSender
from endstone.event import (
    event_handler, PlayerJoinEvent, PlayerQuitEvent, PlayerDimensionChangeEvent
)

current_dir = os.getcwd()

first_dir = os.path.join(current_dir, "plugins", "u-dynamic-light")

if not os.path.exists(first_dir):
    os.mkdir(first_dir)

config_data_file_path = os.path.join(first_dir, "config.json")

lang_dir = os.path.join(first_dir, "lang")

if not os.path.exists(lang_dir):
    os.mkdir(lang_dir)


class u_dynamic_light(Plugin):
    api_version = "0.11"

    # The API has no collision/passability query. Only traverse these known
    # non-solid blocks; the fake light itself must always occupy real air.
    _LIGHT_SEARCH_PASS_THROUGH = frozenset({
        "minecraft:tallgrass", "minecraft:double_plant",  # Legacy block IDs
        "minecraft:short_grass", "minecraft:tall_grass",
        "minecraft:fern", "minecraft:large_fern",
        "minecraft:short_dry_grass", "minecraft:tall_dry_grass",
        "minecraft:sunflower", "minecraft:lilac", "minecraft:rose_bush",
        "minecraft:peony", "minecraft:vine", "minecraft:glow_lichen",
        "minecraft:seagrass", "minecraft:kelp", "minecraft:kelp_plant",
        "minecraft:water", "minecraft:flowing_water", "minecraft:bubble_column",
    })
    # Head first, then up (at most two cells), horizontal neighbours, and feet.
    # Stop each ray at an unknown/solid block. At most eight block reads.
    _LIGHT_SEARCH_RAYS = (
        ((0, 1, 0), (0, 2, 0)),
        ((1, 0, 0),), ((-1, 0, 0),),
        ((0, 0, 1),), ((0, 0, -1),), ((0, -1, 0),),
    )
    _LIGHT_REAPPLY_TICKS = 20

    def __init__(self):
        super().__init__()

        # Load config data
        if not os.path.exists(config_data_file_path):
            with open(config_data_file_path, "w", encoding="utf-8") as f:
                config_data = {
                    "item_type_id_allow_in_offhand": {
                        "minecraft:torch": True,
                        "minecraft:soul_torch": True,
                        "minecraft:redstone_torch": True,
                        "minecraft:copper_torch": True,

                        "minecraft:lantern": True,
                        "minecraft:soul_lantern": True,
                        "minecraft:copper_lantern": True,
                        "minecraft:exposed_copper_lantern": True,
                        "minecraft:oxidized_copper_lantern": True,
                        "minecraft:waxed_copper_lantern": True,
                        "minecraft:waxed_exposed_copper_lantern": True,
                        "minecraft:waxed_oxidized_copper_lantern": True,
                        "minecraft:waxed_weathered_copper_lantern": True,
                        "minecraft:weathered_copper_lantern": True,

                        "minecraft:lava_bucket": True,

                        "minecraft:campfire": False,
                        "minecraft:soul_campfire": False,

                        "minecraft:beacon": False,
                        "minecraft:enchanting_table": False,
                        "minecraft:glowstone": False,
                        "minecraft:lit_pumpkin": False,
                        "minecraft:sculk_catalyst": False,

                        "minecraft:ochre_froglight": False,
                        "minecraft:pearlescent_froglight": False,
                        "minecraft:verdant_froglight": False,

                        "minecraft:conduit": False,
                        "minecraft:sea_lantern": False,
                        "minecraft:sea_pickle": False,

                        "minecraft:brown_mushroom": False,
                        "minecraft:glow_berries": False,
                        "minecraft:glow_lichen": False,

                        "minecraft:small_amethyst_bud": False,
                        "minecraft:medium_amethyst_bud": False,
                        "minecraft:large_amethyst_bud": False,
                        "minecraft:amethyst_cluster": False,

                        "minecraft:magma": False,
                        "minecraft:shroomlight": False,
                        "minecraft:crying_obsidian": False,

                        "minecraft:end_rod": False,
                        "minecraft:ender_chest": False,
                        "minecraft:dragon_egg": False
                    },
                    "refresh_tick": 1
                }

                json_str = json.dumps(config_data, indent=4, ensure_ascii=False)

                f.write(json_str)
        else:
            with open(config_data_file_path, "r", encoding="utf-8") as f:
                config_data = json.loads(f.read())

        self.config_data = config_data

        # Load lang data
        self.lang_data = load_lang(lang_dir)

        self.may_glowing_item_type_id_dict = {
            "minecraft:torch": 14,
            "minecraft:soul_torch": 10,
            "minecraft:redstone_torch": 7,
            "minecraft:copper_torch": 14,

            "minecraft:lantern": 15,
            "minecraft:soul_lantern": 10,
            "minecraft:copper_lantern": 15,
            "minecraft:exposed_copper_lantern": 15,
            "minecraft:oxidized_copper_lantern": 15,
            "minecraft:waxed_copper_lantern": 15,
            "minecraft:waxed_exposed_copper_lantern": 15,
            "minecraft:waxed_oxidized_copper_lantern": 15,
            "minecraft:waxed_weathered_copper_lantern": 15,
            "minecraft:weathered_copper_lantern": 15,

            "minecraft:lava_bucket": 15,

            "minecraft:campfire": 15,
            "minecraft:soul_campfire": 10,

            "minecraft:beacon": 15,
            "minecraft:enchanting_table": 7,
            "minecraft:glowstone": 15,
            "minecraft:lit_pumpkin": 15,
            "minecraft:sculk_catalyst": 6,

            "minecraft:ochre_froglight": 15,
            "minecraft:pearlescent_froglight": 15,
            "minecraft:verdant_froglight": 15,

            "minecraft:conduit": 15,
            "minecraft:sea_lantern": 15,
            "minecraft:sea_pickle": 6,

            "minecraft:brown_mushroom": 1,
            "minecraft:glow_berries": 14,
            "minecraft:glow_lichen": 7,

            "minecraft:small_amethyst_bud": 1,
            "minecraft:medium_amethyst_bud": 2,
            "minecraft:large_amethyst_bud": 4,
            "minecraft:amethyst_cluster": 5,

            "minecraft:magma": 3,
            "minecraft:shroomlight": 15,
            "minecraft:crying_obsidian": 10,

            "minecraft:end_rod": 14,
            "minecraft:ender_chest": 7,
            "minecraft:dragon_egg": 1
        }

        self.may_glowing_item_type_id_list = [key for key in self.may_glowing_item_type_id_dict.keys()]

        self.recorder = {}
        self._light_runtime_ids = {}
        self._light_tick = 0
        self._light_task = None

    def on_enable(self):
        self.register_events(self)
        self._light_task = self._schedule_light_task(self.config_data["refresh_tick"])

        self.logger.info(
            f"{ColorFormat.YELLOW}"
            f"U-DynamicLight is enabled..."
        )

    def _schedule_light_task(self, refresh_tick: int):
        return self.server.scheduler.run_task(
            self, self.light_manage, delay=0, period=refresh_tick
        )

    def on_disable(self):
        if self._light_task is not None:
            self._light_task.cancel()
            self._light_task = None
        for player in self.server.online_players:
            self.light_off(player)
        self.recorder.clear()
        self._light_runtime_ids.clear()

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent):
        self.recorder.pop(event.player.name, None)

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent):
        self.recorder.pop(event.player.name, None)

    @event_handler
    def on_player_dimension_change(self, event: PlayerDimensionChangeEvent):
        # This event fires after the transition. UpdateBlock has no dimension
        # field, so restoring an old coordinate here would affect the new world.
        self.recorder.pop(event.player.name, None)

    commands = {
        "offhand": {
            "description": "Switch glowing items to offhand",
            "usages": ["/offhand"],
            "permissions": ["u_dynamic_light.command.offhand"]
        },
        "ud": {
            "description": "Call out main form of U-DynamicLight",
            "usages": ["/ud"],
            "permissions": ["u_dynamic_light.command.ud"]
        }
    }

    permissions = {
        "u_dynamic_light.command.offhand": {
            "description": "Switch items to offhand",
            "default": True
        },
        "u_dynamic_light.command.ud": {
            "description": "Call out main form of U-DynamicLight",
            "default": "Operator"
        }

    }

    def on_command(self, sender: CommandSender, command: Command, args: list[str]):
        if command.name == "offhand":
            if not isinstance(sender, Player):
                sender.send_message(
                    f"{ColorFormat.RED}"
                    f"This command can only be executed by a player..."
                )

                return

            if sender.inventory.item_in_main_hand is None:
                sender.send_message(
                    f"{ColorFormat.RED}"
                    f"{self.get_text(sender, 'switch.message.fail_1')}"
                )

                return
            else:
                item_in_main_hand_type_id = sender.inventory.item_in_main_hand.type.id

                if not self.config_data["item_type_id_allow_in_offhand"].get(item_in_main_hand_type_id):
                    sender.send_message(
                        f"{ColorFormat.RED}"
                        f"{self.get_text(sender, 'switch.message.fail_2')}"
                    )

                    item_allow_in_offhand_name_list = []
                    for item_type_id, bool_value in self.config_data["item_type_id_allow_in_offhand"].items():
                        if bool_value:
                            itemstack = ItemStack(
                                type=item_type_id
                            )

                            item_type_translation_key = itemstack.type.translation_key
                            item_name = self.server.language.translate(
                                item_type_translation_key,
                                None,
                                sender.locale
                            )

                            item_allow_in_offhand_name_list.append(item_name)

                    if len(item_allow_in_offhand_name_list) != 0:
                        sender.send_message(
                            f"{ColorFormat.YELLOW}"
                            f"{self.get_text(sender, 'switch.message.fail_3')}"
                        )

                        for i in item_allow_in_offhand_name_list:
                            sender.send_message(
                                f"{ColorFormat.YELLOW}- {i}"
                            )

                    return
                else:
                    itemstack_for_offhand = sender.inventory.item_in_main_hand

                    if sender.inventory.item_in_off_hand.type.id == "minecraft:air":
                        itemstack_for_main_hand = None
                    else:
                        itemstack_for_main_hand = sender.inventory.item_in_off_hand

                    sender.inventory.item_in_off_hand = itemstack_for_offhand
                    sender.inventory.item_in_main_hand = itemstack_for_main_hand

                    sender.send_message(
                        f"{ColorFormat.YELLOW}"
                        f"{self.get_text(sender, 'switch.message.success')}"
                    )

        if command.name == "ud":
            if not isinstance(sender, Player):
                sender.send_message(
                    f"{ColorFormat.RED}"
                    f"This command can only be executed by a player..."
                )

                return

            if sender.is_op:
                textinput = TextInput(
                    label=f"{ColorFormat.GREEN}"
                          f"{self.get_text(sender, 'form.textinput.label')}: "
                          f"{ColorFormat.WHITE}"
                          f"{self.config_data['refresh_tick']} (tick)",
                    placeholder=self.get_text(sender, "form.textinput.placeholder"),
                    default_value=str(self.config_data["refresh_tick"])
                )

                controls: list = [textinput]

                for item_type_id, bool_value in self.config_data["item_type_id_allow_in_offhand"].items():
                    itemstack = ItemStack(
                        type=item_type_id
                    )

                    item_translation_key = itemstack.type.translation_key
                    item_name = self.server.language.translate(
                        item_translation_key,
                        None,
                        sender.locale
                    )

                    controls.append(
                        Toggle(
                            label=f"{ColorFormat.GREEN}"
                                  f"{item_name}",
                            default_value=bool_value
                        )
                    )

                form = ModalForm(
                    title=f'{ColorFormat.BOLD}{ColorFormat.LIGHT_PURPLE}'
                          f"U-DynamicLight",
                    controls=controls,
                    submit_button=f"{ColorFormat.YELLOW}"
                                  f"{self.get_text(sender, 'form.submit_button')}",
                    on_close=None
                )

                def on_submit(s: Player, json_str: str):
                    try:
                        data = json.loads(json_str)
                        if not isinstance(data, list) or len(data) != 1 + len(
                            self.config_data["item_type_id_allow_in_offhand"]
                        ):
                            raise ValueError("Invalid form response")
                        if not isinstance(data[0], str):
                            raise ValueError("Refresh interval must be an integer")
                        update_refresh_tick = int(data[0])
                        if not 0 < update_refresh_tick <= 2**64 - 1 or not all(
                            isinstance(value, bool) for value in data[1:]
                        ):
                            raise ValueError("Invalid configuration")
                    except (ValueError, TypeError):
                        s.send_message(
                            f"{ColorFormat.RED}"
                            f"{self.get_text(s, 'reload.message.fail')}"
                        )
                        return

                    candidate = dict(self.config_data)
                    candidate["refresh_tick"] = update_refresh_tick
                    candidate["item_type_id_allow_in_offhand"] = dict(zip(
                        self.config_data["item_type_id_allow_in_offhand"], data[1:]
                    ))
                    replacement = None
                    try:
                        if update_refresh_tick != self.config_data["refresh_tick"] or self._light_task is None:
                            # Queue first: a scheduler failure must leave the old
                            # task running. These callbacks run on the server thread.
                            replacement = self._schedule_light_task(update_refresh_tick)
                            if replacement is None:
                                raise RuntimeError("Could not schedule light updates")
                        self.save_config_data(candidate)
                    except (OSError, RuntimeError, ValueError, TypeError, OverflowError) as error:
                        if replacement is not None:
                            replacement.cancel()
                        self.logger.error(f"Could not reload U-DynamicLight configuration: {error}")
                        s.send_message(
                            f"{ColorFormat.RED}"
                            f"{self.get_text(s, 'reload.message.fail')}"
                        )
                        return

                    self.config_data = candidate
                    if replacement is not None:
                        previous = self._light_task
                        self._light_task = replacement
                        if previous is not None:
                            previous.cancel()

                    s.send_message(
                        f"{ColorFormat.YELLOW}"
                        f"{self.get_text(s, 'reload.message.success')}"
                    )

                form.on_submit = on_submit

                sender.send_form(form)

    # Persist a staged configuration without changing live state on failure.
    def save_config_data(self, config_data=None) -> None:
        if config_data is None:
            config_data = self.config_data
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=os.path.dirname(config_data_file_path),
                prefix=".config-", suffix=".tmp", delete=False
            ) as file:
                temporary_path = file.name
                json.dump(config_data, file, indent=4, ensure_ascii=False)
            # Same-directory replacement leaves the old JSON intact if writing
            # fails, and readers never see a partially written configuration.
            os.replace(temporary_path, config_data_file_path)
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _send_block(self, player: Player, pos: list, runtime_id: int) -> None:
        bs = BinaryStream()
        # Signed BlockPos (Bedrock protocol 944+, unchanged from this release).
        bs.write_varint(pos[0])
        bs.write_varint(pos[1])
        bs.write_varint(pos[2])
        bs.write_unsigned_varint(runtime_id)
        bs.write_unsigned_varint(3)  # Update neighbours and client rendering
        bs.write_unsigned_varint(0)  # Main block layer only
        player.send_packet(21, bs.get_and_release_data())

    def _restore_light(self, player: Player, record: dict) -> None:
        if player.dimension.name != record["dim"].name:
            return
        # Read now, not when the light was placed: a real block may have changed.
        block = record["dim"].get_block_at(*record["pos"])
        self._send_block(player, record["pos"], block.data.runtime_id)

    def light_on(self, player: Player, pos: list, dim: Dimension, runtime_id: int) -> None:
        old = self.recorder.get(player.name)
        # Place the new light first. A brightness-only change must not then
        # restore the same coordinate, which would erase the replacement.
        self._send_block(player, pos, runtime_id)
        self.recorder[player.name] = {
            "pos": pos,
            "dim": dim,
            "runtime_id": runtime_id,
            "sent_tick": self._light_tick,
        }
        if old is not None and old["pos"] != pos:
            self._restore_light(player, old)

    def light_off(self, player: Player) -> None:
        old = self.recorder.pop(player.name, None)
        if old is not None:
            self._restore_light(player, old)

    def _find_light_position(self, player: Player):
        location = player.location
        head = [math.floor(location.x), math.floor(location.y + 1), math.floor(location.z)]
        dim = player.dimension
        block_type = dim.get_block_at(*head).type
        if block_type == "minecraft:air":
            return head
        if block_type not in self._LIGHT_SEARCH_PASS_THROUGH:
            return None
        for ray in self._LIGHT_SEARCH_RAYS:
            for dx, dy, dz in ray:
                pos = [head[0] + dx, head[1] + dy, head[2] + dz]
                block_type = dim.get_block_at(*pos).type
                if block_type == "minecraft:air":
                    return pos
                if block_type not in self._LIGHT_SEARCH_PASS_THROUGH:
                    break
        return None

    def light_manage(self) -> None:
        self._light_tick += self.config_data["refresh_tick"]
        players = list(self.server.online_players)
        online_names = {player.name for player in players}
        # Also prune when the server is empty; quit events are the fast path.
        for name in list(self.recorder):
            if name not in online_names:
                self.recorder.pop(name)

        for player in players:
            level = max(
                self.may_glowing_item_type_id_dict.get(item.type.id, 0)
                if item is not None else 0
                for item in (player.inventory.item_in_main_hand, player.inventory.item_in_off_hand)
            )
            if level == 0:
                self.light_off(player)
                continue

            pos = self._find_light_position(player)
            if pos is None:
                self.light_off(player)
                continue

            runtime_id = self._light_runtime_ids.get(level)
            if runtime_id is None:
                runtime_id = self.server.create_block_data(
                    "minecraft:light_block_" + str(level), None
                ).runtime_id
                self._light_runtime_ids[level] = runtime_id

            old = self.recorder.get(player.name)
            if old is not None and (
                old["pos"] == pos
                and old["dim"].name == player.dimension.name
                and old["runtime_id"] == runtime_id
                and self._light_tick - old["sent_tick"] < self._LIGHT_REAPPLY_TICKS
            ):
                # One stationary player must not starve the rest of the loop.
                continue
            # An occasional direct reapply recovers from normal chunk/block
            # packets overwriting the fake light. No clear/recreate cycle.
            self.light_on(player, pos, player.dimension, runtime_id)

    # Get text
    def get_text(self, player: Player, text_key: str) -> str:
        player_lang = player.locale

        try:
            if self.lang_data.get(player_lang) is None:
                text_value = self.lang_data["en_US"][text_key]
            else:
                if self.lang_data[player_lang].get(text_key) is None:
                    text_value = self.lang_data["en_US"][text_key]
                else:
                    text_value = self.lang_data[player_lang][text_key]

            return text_value
        except Exception as e:
            self.logger.error(
                f"{ColorFormat.RED}"
                f"{e}"
            )

            return text_key
