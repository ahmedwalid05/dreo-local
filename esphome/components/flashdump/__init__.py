import esphome.codegen as cg
from esphome.components import button

flashdump_ns = cg.esphome_ns.namespace('flashdump')
FlashDumpButton = flashdump_ns.class_('FlashDumpButton', button.Button, cg.Component)
