#pragma once
#include "esphome/core/component.h"
#include "esphome/components/button/button.h"

namespace esphome {
namespace flashdump {

class FlashDumpButton : public button::Button, public Component {
 public:
  void dump_config() override {}
 protected:
  void press_action() override;
};

}  // namespace flashdump
}  // namespace esphome
namespace esphome { namespace flashdump { void trigger_dump(); } }
