# UDI LiFX Poly
This is a simple integration of LiFX lights to ISY994i. Please install via [Polyglot v2](https://github.com/UniversalDevicesInc/polyglot-v2) Store. Report any problems on [UDI User Forum](https://forum.universal-devices.com/topic/19021-polyglot-lifx-nodesever/).

Custom parameters supported:
    - `devlist` - link to a YAML manifest of devices, skips automatic discovery. See [this post](https://forum.universal-devices.com/topic/19021-polyglot-lifx-nodesever/?do=findComment&comment=257145).
    - `change_no_pon` - change of color won't power the device on.
    - `ignore_second_on` - power on command will be ignored if device is already on.
