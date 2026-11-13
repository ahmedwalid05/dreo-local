import esphome.codegen as cg
from esphome.components import button
from . import flashdump_ns, FlashDumpButton

CONFIG_SCHEMA = button.button_schema(FlashDumpButton)

async def to_code(config):
    var = await button.new_button(config)
    await cg.register_component(var, config)
