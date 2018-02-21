#!/usr/bin/env python3
##!/home/e42/dev/py3_envs/udi-lifx-poly-venv/bin/python
"""
LiFX NodeServer for UDI Polyglot v2
by Einstein.42 (James Milne) milne.james@gmail.com
"""

import polyinterface
import time
import sys
import lifxlan
from copy import deepcopy
import json
from threading import Thread
from pathlib import Path


LOGGER = polyinterface.LOGGER
BR_INCREMENT = 2620    # this is ~4% of 65535
BR_MIN = 1310          # minimum brightness value ~2%
BR_MAX = 65535         # maximum brightness value
FADE_INTERVAL = 5000   # 5s
BRTDIM_INTERVAL = 400  # 400ms

with open('server.json') as data:
    SERVERDATA = json.load(data)
    data.close()
try:
    VERSION = SERVERDATA['credits'][0]['version']
except (KeyError, ValueError):
    LOGGER.info('Version not found in server.json.')
    VERSION = '0.0.0'


# Changing these will not update the ISY names and labels, you will have to edit the profile.
COLORS = {
    0: ['RED', [62978, 65535, 65535, 3500]],
    1: ['ORANGE', [5525, 65535, 65535, 3500]],
    2: ['YELLOW', [7615, 65535, 65535, 3500]],
    3: ['GREEN', [16173, 65535, 65535, 3500]],
    4: ['CYAN', [29814, 65535, 65535, 3500]],
    5: ['BLUE', [43634, 65535, 65535, 3500]],
    6: ['PURPLE', [50486, 65535, 65535, 3500]],
    7: ['PINK', [58275, 65535, 47142, 3500]],
    8: ['WHITE', [58275, 0, 65535, 5500]],
    9: ['COLD_WHTE', [58275, 0, 65535, 9000]],
    10: ['WARM_WHITE', [58275, 0, 65535, 3200]],
    11: ['GOLD', [58275, 0, 65535, 2500]]
}


class Controller(polyinterface.Controller):
    def __init__(self, polyglot):
        super().__init__(polyglot)
        self.lifxLan = None
        self.name = 'LiFX Controller'
        self.discovery = False
        self.discovery_thread = None
        self.update_nodes = False

    def start(self):
        LOGGER.info('Starting LiFX Polyglot v2 NodeServer version {}'.format(VERSION))
        self._checkProfile()
        self.lifxLan = lifxlan.LifxLAN()
        self.discover()
        LOGGER.debug('Start complete')

    def _checkProfile(self):
        profile_version_file = Path('profile/version.txt')
        if profile_version_file.is_file() and 'customData' in self.polyConfig:
            with profile_version_file.open() as f:
                profile_version = f.read().replace('\n', '')
                f.close()
            if 'prof_ver' in self.polyConfig['customData']:
                if self.polyConfig['customData']['prof_ver'] != profile_version:
                    self.update_nodes = True
            else:
                self.update_nodes = True
            if self.update_nodes:
                LOGGER.info('New Profile Version detected: {}, all nodes will be updated'.format(profile_version))
                cust_data = deepcopy(self.polyConfig['customData'])
                cust_data['prof_ver'] = profile_version
                self.saveCustomData(cust_data)

    def shortPoll(self):
        if self.discovery:
            return
        for node in self.nodes:
            self.nodes[node].update()

    def longPoll(self):
        if self.discovery:
            return
        for node in self.nodes:
            self.nodes[node].long_update()

    def update(self):
        pass

    def long_update(self):
        pass

    def discover(self, command=None):
        if self.discovery_thread is not None:
            if self.discovery_thread.isAlive():
                LOGGER.info('Discovery is still in progress')
                return
            else:
                self.discovery = False
        self.discovery_thread = Thread(target=self._discovery_process)
        self.discovery_thread.start()

    def _discovery_process(self):
        if self.discovery:
            return
        self.discovery = True
        LOGGER.info('Starting LiFX Discovery thread...')
        try:
            devices = self.lifxLan.get_lights()
            bulbs_found = len(devices)
            LOGGER.info('{} bulbs found. Checking status and adding to ISY if necessary.'.format(bulbs_found))
            try:
                old_bulbs_found = int(self.getDriver('GV0'))
            except:
                old_bulbs_found = bulbs_found
            else:
                if bulbs_found != old_bulbs_found:
                    LOGGER.info('NOTICE: Bulb count {} is different, was {} previously'.format(bulbs_found, old_bulbs_found))
            self.setDriver('GV0', bulbs_found)
            for d in devices:
                label = str(d.get_label())
                name = 'LIFX {}'.format(label)
                address = d.get_mac_addr().replace(':', '').lower()
                if not address in self.nodes:
                    mac = d.get_mac_addr()
                    ip = d.get_ip_addr()
                    if d.supports_multizone():
                        LOGGER.info('Found MultiZone Bulb: {}({})'.format(name, address))
                        self.addNode(MultiZone(self, self.address, address, name, mac, ip, label), update = self.update_nodes)
                    else:
                        LOGGER.info('Found Bulb: {}({})'.format(name, address))
                        self.addNode(Light(self, self.address, address, name, mac, ip, label), update = self.update_nodes)
                gid, glabel, gupdatedat = d.get_group_tuple()
                gaddress = glabel.replace("'", "").replace(' ', '').lower()[:12]
                if not gaddress in self.nodes:
                    LOGGER.info('Found LiFX Group: {}'.format(glabel))
                    self.addNode(Group(self, self.address, gaddress, gid, glabel, gupdatedat), update = self.update_nodes)
        except (lifxlan.WorkflowException, OSError, IOError, TypeError) as ex:
            LOGGER.error('discovery Error: {}'.format(ex))
        self.discovery = False
        self.update_nodes = False
        LOGGER.info('LiFX Discovery thread is complete.')

    def all_on(self, command):
        try:
            self.lifxLan.set_power_all_lights("on", rapid=True)
        except (lifxlan.WorkflowException, OSError, IOError, TypeError) as ex:
            LOGGER.error('All On Error: {}'.format(ex))

    def all_off(self, command):
        try:
            self.lifxLan.set_power_all_lights("off", rapid=True)
        except (lifxlan.WorkflowException, OSError, IOError, TypeError) as ex:
            LOGGER.error('All Off Error: {}'.format(ex))

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 2},
               {'driver': 'GV0', 'value': 0, 'uom': 56}
              ]

    id = 'controller'

    commands = {'DISCOVER': discover, 'DON': all_on, 'DOF': all_off}


class Light(polyinterface.Node):
    """
    LiFX Light Parent Class
    """
    def __init__(self, controller, primary, address, name, mac, ip, label):
        super().__init__(controller, primary, address, name)
        self.device = None
        self.mac = mac
        self.ip = ip
        self.name = name
        self.power = False
        self.label = label
        self.connected = 1
        self.uptime = 0
        self.color= []
        self.lastupdate = time.time()
        self.duration = 0

    def start(self):
        self.device = lifxlan.Light(self.mac, self.ip)
        try:
            self.duration = int(self.getDriver('RR'))
        except:
            self.duration = 0
        self.update()
        self.long_update()

    def query(self, command = None):
        self.update()
        self.long_update()
        self.reportDrivers()

    def update(self):
        connected = 0
        try:
            self.color = list(self.device.get_color())
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} bulb color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            connected = 1
            for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
                self.setDriver(driver, self.color[ind])
        try:
            self.power = True if self.device.get_power() == 65535 else False
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} bulb power. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            connected = 1
            if self.power:
                self.setDriver('ST', self._bri_to_percent(self.color[2]))
            else:
                self.setDriver('ST', 0)
        self.connected = connected
        self.setDriver('GV5', self.connected)
        self.setDriver('RR', self.duration)
        self.lastupdate = time.time()

    def long_update(self):
        connected = 0
        try:
            self.uptime = self._nanosec_to_hours(self.device.get_uptime())
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} bulb uptime. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            connected = 1
            self.setDriver('GV6', self.uptime)
        if self.device.supports_infrared():
            try:
                ir_brightness = self.device.get_infrared()
            except (lifxlan.WorkflowException, OSError) as ex:
                LOGGER.error('Connection Error on getting {} bulb Infrared. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                connected = 1
                self.setDriver('GV7', ir_brightness)
        else:
            self.setDriver('GV7', 0)
        try:
            wifi_signal = float(self.device.get_wifi_signal_mw())
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} bulb WiFi signal strength. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            connected = 1
            self.setDriver('GV0', round(wifi_signal, 1))
        self.connected = connected
        self.setDriver('GV5', self.connected)
        self.lastupdate = time.time()

    def _nanosec_to_hours(self, ns):
        return int(round(ns/(1000000000.0*60*60)))

    def _bri_to_percent(self, bri):
        return float(round(bri*100/65535, 4))

    def setOn(self, command):
        cmd = command.get('cmd')
        val = command.get('value')
        new_bri = None
        if cmd == 'DFON' and self.color[2] != BR_MAX:
            new_bri = BR_MAX
            trans = 0
        elif cmd == 'DON' and val is not None:
            new_bri = int(round(int(val)*65535/255))
            if new_bri > BR_MAX:
                new_bri = BR_MAX
            elif new_bri < BR_MIN:
                new_bri = BR_MIN
            trans = self.duration
        elif self.power and self.color[2] != BR_MAX:
            new_bri = BR_MAX
            trans = self.duration
        if new_bri is not None:
            self.color[2] = new_bri
            try:
                self.device.set_color(self.color, trans, rapid=False)
            except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error DON {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                self.setDriver('GV3', self.color[2])
        try:
            self.device.set_power(True)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error on setting {} bulb power. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.power = True
            self.setDriver('ST', self._bri_to_percent(self.color[2]))

    def setOff(self, command):
        try:
            self.device.set_power(False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error on setting {} bulb power. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.power = False
            self.setDriver('ST', 0)

    def dim(self, command):
        if self.power is False:
            LOGGER.info('{} is off, ignoring DIM'.format(self.name))
        new_bri = self.color[2] - BR_INCREMENT
        if new_bri < BR_MIN:
            new_bri = BR_MIN
        self.color[2] = new_bri
        try:
            self.device.set_color(self.color, BRTDIM_INTERVAL, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error on dimming {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.setDriver('ST', self._bri_to_percent(self.color[2]))
            self.setDriver('GV3', self.color[2])

    def brighten(self, command):
        if self.power is False:
            # Bulb is currently off, let's turn it on ~2%
            self.color[2] = BR_MIN
            try:
                self.device.set_color(self.color, 0, rapid=False)
                self.device.set_power(True)
            except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error on brightnening {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                self.power = True
                self.setDriver('ST', self._bri_to_percent(self.color[2]))
            return
        new_bri = self.color[2] + BR_INCREMENT
        if new_bri > BR_MAX:
            new_bri = BR_MAX
        self.color[2] = new_bri
        try:
            self.device.set_color(self.color, BRTDIM_INTERVAL, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error on dimming {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.setDriver('ST', self._bri_to_percent(self.color[2]))
            self.setDriver('GV3', self.color[2])

    def fade_up(self, command):
        if self.power is False:
            # Bulb is currently off, let's turn it on ~2%
            self.color[2] = BR_MIN
            try:
                self.device.set_color(self.color, 0, rapid=False)
                self.device.set_power(True)
            except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error on brightnening {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                self.power = True
                self.setDriver('ST', self._bri_to_percent(self.color[2]))
        if self.color[2] == BR_MAX:
            LOGGER.info('{} Can not FadeUp, already at maximum'.format(self.name))
            return
        self.color[2] = BR_MAX
        try:
            self.device.set_color(self.color, FADE_INTERVAL, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error {} bulb Fade Up. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))

    def fade_down(self, command):
        if self.power is False:
            LOGGER.error('{} can not FadeDown as it is currently off'.format(self.name))
            return
        if self.color[2] <= BR_MIN:
            LOGGER.error('{} can not FadeDown as it is currently at minimum'.format(self.name))
            return
        self.color[2] = BR_MIN
        try:
            self.device.set_color(self.color, FADE_INTERVAL, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error {} bulb Fade Down. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))

    def fade_stop(self, command):
        if self.power is False:
            LOGGER.error('{} can not FadeStop as it is currently off'.format(self.name))
            return
        # check current brightness level
        try:
            self.color = list(self.device.get_color())
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} bulb color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
                self.setDriver(driver, self.color[ind])
        if self.color[2] == BR_MIN or self.color[2] == BR_MAX:
            LOGGER.error('{} can not FadeStop as it is currently at limit'.format(self.name))
            return
        try:
            self.device.set_color(self.color, 0, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error {} bulb Fade Stop. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))

    def setColor(self, command):
        if self.connected:
            _color = int(command.get('value'))
            try:
                self.device.set_color(COLORS[_color][1], duration=self.duration, rapid=False)
            except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error on setting {} bulb color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            LOGGER.info('Received SetColor command from ISY. Changing color to: {}'.format(COLORS[_color][0]))
            for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
                self.setDriver(driver, COLORS[_color][1][ind])
        else:
            LOGGER.error('Received SetColor, however the bulb is in a disconnected state... ignoring')

    def setManual(self, command):
        if self.connected:
            _cmd = command.get('cmd')
            _val = int(command.get('value'))
            if _cmd == 'SETH':
                self.color[0] = _val
                driver = ['GV1', self.color[0]]
            elif _cmd == 'SETS':
                self.color[1] = _val
                driver = ['GV2', self.color[1]]
            elif _cmd == 'SETB':
                self.color[2] = _val
                driver = ['GV3', self.color[2]]
            elif _cmd == 'CLITEMP':
                self.color[3] = _val
                driver = ['CLITEMP', self.color[3]]
            elif _cmd == 'RR':
                self.duration = _val
                driver = ['RR', self.duration]
            try:
                self.device.set_color(self.color, self.duration, rapid=False)
            except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error on setting {} bulb {}. This happens from time to time, normally safe to ignore. {}'.format(self.name, _cmd, str(ex)))
            LOGGER.info('Received manual change, updating the bulb to: {} duration: {}'.format(str(self.color), self.duration))
            if driver:
                self.setDriver(driver[0], driver[1])
        else: LOGGER.info('Received manual change, however the bulb is in a disconnected state... ignoring')

    def setHSBKD(self, command):
        query = command.get('query')
        try:
            self.color = [int(query.get('H.uom56')), int(query.get('S.uom56')), int(query.get('B.uom56')), int(query.get('K.uom26'))]
            self.duration = int(query.get('D.uom42'))
            LOGGER.info('Received manual change, updating the bulb to: {} duration: {}'.format(str(self.color), self.duration))
        except TypeError:
            self.duration = 0
        try:
            self.device.set_color(self.color, duration=self.duration, rapid=False)
        except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error on setting {} bulb color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
            self.setDriver(driver, self.color[ind])
        self.setDriver('RR', self.duration)

    def set_ir_brightness(self, command):
        _val = int(command.get('value'))
        if not self.device.supports_infrared():
            LOGGER.error('{} is not IR capable'.format(self.name))
            return
        try:
            self.device.set_infrared(_val)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error on setting {} bulb IR Brightness. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.setDriver('GV7', _val)

    def set_wf(self, command):
        WAVEFORM = ['Saw', 'Sine', 'HalfSine', 'Triangle', 'Pulse']
        if self.power is False:
            LOGGER.error('{} can not run Waveform as it is currently off'.format(self.name))
            return
        query = command.get('query')
        wf_color = [int(query.get('H.uom56')), int(query.get('S.uom56')), int(query.get('B.uom56')), int(query.get('K.uom26'))]
        wf_period = int(query.get('PE.uom42'))
        wf_cycles = int(query.get('CY.uom56'))
        wf_duty_cycle = int(query.get('DC.uom56'))
        wf_form = int(query.get('WF.uom25'))
        if wf_form >= 5:
            wf_transient = 1
            wf_form -= 5
        else:
            wf_transient = 0
        LOGGER.debug('Color tuple: {}, Period: {}, Cycles: {}, Duty cycle: {}, Form: {}, Transient: {}'.format(wf_color, wf_period, wf_cycles, wf_duty_cycle, WAVEFORM[wf_form], wf_transient))
        try:
            self.device.set_waveform(wf_transient, wf_color, wf_period, wf_cycles, wf_duty_cycle, wf_form)
        except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error on setting {} bulb Waveform. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 51},
                {'driver': 'GV0', 'value': 0, 'uom': 56},
                {'driver': 'GV1', 'value': 0, 'uom': 56},
                {'driver': 'GV2', 'value': 0, 'uom': 56},
                {'driver': 'GV3', 'value': 0, 'uom': 56},
                {'driver': 'CLITEMP', 'value': 0, 'uom': 26},
                {'driver': 'GV5', 'value': 0, 'uom': 2},
                {'driver': 'GV6', 'value': 0, 'uom': 20},
                {'driver': 'GV7', 'value': 0, 'uom': 56},
                {'driver': 'RR', 'value': 0, 'uom': 42}]

    id = 'lifxcolor'

    commands = {
                    'DON': setOn, 'DOF': setOff, 'QUERY': query,
                    'SET_COLOR': setColor, 'SETH': setManual,
                    'SETS': setManual, 'SETB': setManual,
                    'CLITEMP': setManual,
                    'RR': setManual, 'SET_HSBKD': setHSBKD,
                    'BRT': brighten, 'DIM': dim, 'FDUP': fade_up,
                    'FDDOWN': fade_down, 'FDSTOP': fade_stop,
                    'DFON': setOn, 'DFOF': setOff,
                    'SETIR': set_ir_brightness, 'WAVEFORM': set_wf
                }

class MultiZone(Light):
    def __init__(self, controller, primary, address, name, mac, ip, label):
        super().__init__(controller, primary, address, name, mac, ip, label)
        self.num_zones = 0
        self.current_zone = 0
        self.new_color = None
        self.pending = False

    def update(self):
        connected = 0
        zone = deepcopy(self.current_zone)
        if self.current_zone != 0: zone -= 1
        if not self.pending:
            try:
                self.color = self.device.get_color_zones()
            except (lifxlan.WorkflowException, OSError) as ex:
                LOGGER.error('Connection Error on getting {} multizone color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                connected = 1
                self.num_zones = len(self.color)
                for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
                    try:
                        self.setDriver(driver, self.color[zone][ind])
                    except (TypeError) as e:
                        LOGGER.debug('setDriver for color caught an error. color was : {}'.format(self.color or None))
                    self.setDriver('GV4', self.current_zone)
        try:
            self.power = 1 if self.device.get_power() == 65535 else 0
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} multizone power. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            connected = 1
            self.setDriver('ST', self._bri_to_percent(self.color[zone][2]))
        self.connected = connected
        self.setDriver('GV5', self.connected)
        self.setDriver('RR', self.duration)
        self.lastupdate = time.time()

    def start(self):
        self.device = lifxlan.MultiZoneLight(self.mac, self.ip)
        try:
            self.duration = int(self.getDriver('RR'))
        except:
            self.duration = 0
        try:
            self.current_zone = int(self.getDriver('GV4'))
        except:
            self.current_zone = 0
        self.update()
        self.long_update()

    def setOn(self, command):
        zone = deepcopy(self.current_zone)
        if self.current_zone != 0: zone -= 1
        cmd = command.get('cmd')
        val = command.get('value')
        new_bri = None
        if cmd == 'DFON' and self.color[zone][2] != BR_MAX:
            new_bri = BR_MAX
            trans = 0
        elif cmd == 'DON' and val is not None:
            new_bri = int(round(int(val)*65535/255))
            if new_bri > BR_MAX:
                new_bri = BR_MAX
            elif new_bri < BR_MIN:
                new_bri = BR_MIN
            trans = self.duration
        elif self.power and self.color[zone][2] != BR_MAX:
            new_bri = BR_MAX
            trans = self.duration
        if new_bri is not None:
            new_color = list(self.color[zone])
            new_color[2] = new_bri
            try:
                if self.current_zone == 0:
                    self.device.set_zone_color(0, self.num_zones, new_color, trans, rapid=False)
                else:
                    self.device.set_zone_color(zone, zone, new_color, trans, rapid=False)
            except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error DON {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                self.setDriver('GV3', new_color[2])
        try:
            self.device.set_power(True)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error on setting {} bulb power. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.power = True
            self.setDriver('ST', self._bri_to_percent(self.color[zone][2]))

    def dim(self, command):
        zone = deepcopy(self.current_zone)
        if self.current_zone != 0: zone -= 1
        if self.power is False:
            LOGGER.info('{} is off, ignoring DIM'.format(self.name))
        new_bri = self.color[zone][2] - BR_INCREMENT
        if new_bri < BR_MIN:
            new_bri = BR_MIN
        new_color = list(self.color[zone])
        new_color[2] = new_bri
        try:
            if self.current_zone == 0:
                self.device.set_zone_color(0, self.num_zones, new_color, BRTDIM_INTERVAL, rapid=False)
            else:
                self.device.set_zone_color(zone, zone, new_color, BRTDIM_INTERVAL, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error on dimming {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.setDriver('ST', self._bri_to_percent(new_color[2]))
            self.setDriver('GV3', new_color[2])

    def brighten(self, command):
        zone = deepcopy(self.current_zone)
        if self.current_zone != 0: zone -= 1
        new_color = list(self.color[zone])
        if self.power is False:
            # Bulb is currently off, let's turn it on ~2%
            new_color[2] = BR_MIN
            try:
                if self.current_zone == 0:
                    self.device.set_zone_color(0, self.num_zones, new_color, 0, rapid=False)
                else:
                    self.device.set_zone_color(zone, zone, new_color, 0, rapid=False)
                self.device.set_power(True)
            except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error on brightnening {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                self.power = True
                self.setDriver('ST', self._bri_to_percent(new_color[2]))
            return
        new_bri = self.color[zone][2] + BR_INCREMENT
        if new_bri > BR_MAX:
            new_bri = BR_MAX
        new_color[2] = new_bri
        try:
            if self.current_zone == 0:
                self.device.set_zone_color(0, self.num_zones, new_color, BRTDIM_INTERVAL, rapid=False)
            else:
                self.device.set_zone_color(zone, zone, new_color, BRTDIM_INTERVAL, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error on dimming {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.setDriver('ST', self._bri_to_percent(new_color[2]))
            self.setDriver('GV3', new_color[2])

    def fade_up(self, command):
        zone = deepcopy(self.current_zone)
        if self.current_zone != 0: zone -= 1
        new_color = list(self.color[zone])
        if self.power is False:
            # Bulb is currently off, let's turn it on ~2%
            new_color[2] = BR_MIN
            try:
                if self.current_zone == 0:
                    self.device.set_zone_color(0, self.num_zones, new_color, 0, rapid=False)
                else:
                    self.device.set_zone_color(zone, zone, new_color, 0, rapid=False)
                self.device.set_power(True)
            except lifxlan.WorkflowException as ex:
                LOGGER.error('Connection Error on brightnening {} bulb. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                self.power = True
                self.setDriver('ST', self._bri_to_percent(new_color[2]))
        if self.color[zone][2] == BR_MAX:
            LOGGER.info('{} Can not FadeUp, already at maximum'.format(self.name))
            return
        new_color[2] = BR_MAX
        try:
            if self.current_zone == 0:
                self.device.set_zone_color(0, self.num_zones, new_color, FADE_INTERVAL, rapid=False)
            else:
                self.device.set_zone_color(zone, zone, new_color, FADE_INTERVAL, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error {} bulb Fade Up. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))

    def fade_down(self, command):
        zone = deepcopy(self.current_zone)
        if self.current_zone != 0: zone -= 1
        new_color = list(self.color[zone])
        if self.power is False:
            LOGGER.error('{} can not FadeDown as it is currently off'.format(self.name))
            return
        if self.color[zone][2] <= BR_MIN:
            LOGGER.error('{} can not FadeDown as it is currently at minimum'.format(self.name))
            return
        new_color[2] = BR_MIN
        try:
            if self.current_zone == 0:
                self.device.set_zone_color(0, self.num_zones, new_color, FADE_INTERVAL, rapid=False)
            else:
                self.device.set_zone_color(zone, zone, new_color, FADE_INTERVAL, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error {} bulb Fade Down. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))

    def fade_stop(self, command):
        zone = deepcopy(self.current_zone)
        if self.current_zone != 0: zone -= 1
        if self.power is False:
            LOGGER.error('{} can not FadeStop as it is currently off'.format(self.name))
            return
        # check current brightness level
        try:
            self.color = self.device.get_color_zones()
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} multizone color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
                self.setDriver(driver, self.color[zone][ind])
        if self.color[zone][2] == BR_MIN or self.color[zone][2] == BR_MAX:
            LOGGER.error('{} can not FadeStop as it is currently at limit'.format(self.name))
            return
        try:
            if self.current_zone == 0:
                self.device.set_zone_color(0, self.num_zones, self.color[zone], 0, rapid=False)
            else:
                self.device.set_zone_color(zone, zone, self.color[zone], 0, rapid=False)
        except lifxlan.WorkflowException as ex:
            LOGGER.error('Connection Error {} bulb Fade Stop. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))

    def apply(self, command):
        try:
            if self.new_color:
                self.color = deepcopy(self.new_color)
                self.new_color = None
            self.device.set_zone_colors(self.color, self.duration, rapid=True)
        except (lifxlan.WorkflowException, IOError) as ex:
            LOGGER.error('Connection Error on setting {} bulb color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        LOGGER.info('Received apply command for {}'.format(self.address))
        self.pending = False

    def setColor(self, command):
        if self.connected:
            try:
                _color = int(command.get('value'))
                zone = deepcopy(self.current_zone)
                if self.current_zone != 0: zone -= 1
                if self.current_zone == 0:
                    self.device.set_zone_color(self.current_zone, self.num_zones, COLORS[_color][1], self.duration, True)
                else:
                    self.device.set_zone_color(zone, zone, COLORS[_color][1], self.duration, True)
                LOGGER.info('Received SetColor command from ISY. Changing {} color to: {}'.format(self.address, COLORS[_color][0]))
            except (lifxlan.WorkflowException, IOError) as ex:
                LOGGER.error('mz setcolor error {}'.format(str(ex)))
            for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
                self.setDriver(driver, COLORS[_color][1][ind])
        else: LOGGER.info('Received SetColor, however the bulb is in a disconnected state... ignoring')

    def setManual(self, command):
        if self.connected:
            _cmd = command.get('cmd')
            _val = int(command.get('value'))
            try:
                if _cmd == 'SETZ':
                    self.current_zone = int(_val)
                    if self.current_zone > self.num_zones: self.current_zone = 0
                    driver = ['GV4', self.current_zone]
                zone = deepcopy(self.current_zone)
                if self.current_zone != 0: zone -= 1
                new_color = list(self.color[zone])
                if _cmd == 'SETH':
                    new_color[0] = int(_val)
                    driver = ['GV1', new_color[0]]
                elif _cmd == 'SETS':
                    new_color[1] = int(_val)
                    driver = ['GV2', new_color[1]]
                elif _cmd == 'SETB':
                    new_color[2] = int(_val)
                    driver = ['GV3', new_color[2]]
                elif _cmd == 'CLITEMP':
                    new_color[3] = int(_val)
                    driver = ['CLITEMP', new_color[3]]
                elif _cmd == 'RR':
                    self.duration = _val
                    driver = ['RR', self.duration]
                self.color[zone] = new_color
                if self.current_zone == 0:
                    self.device.set_zone_color(0, self.num_zones, new_color, self.duration, rapid=False)
                else:
                    self.device.set_zone_color(zone, zone, new_color, self.duration, rapid=False)
            except (lifxlan.WorkflowException, TypeError) as ex:
                LOGGER.error('setmanual mz error {}'.format(ex))
            LOGGER.info('Received manual change, updating the mz bulb zone {} to: {} duration: {}'.format(zone, new_color, self.duration))
            if driver:
                self.setDriver(driver[0], driver[1])
        else: LOGGER.info('Received manual change, however the mz bulb is in a disconnected state... ignoring')

    def setHSBKDZ(self, command):
        query = command.get('query')
        if not self.pending:
            self.new_color = deepcopy(self.color)
            self.pending = True
        current_zone = int(query.get('Z.uom56'))
        zone = deepcopy(current_zone)
        if current_zone != 0: zone -= 1
        self.new_color[zone] = [int(query.get('H.uom56')), int(query.get('S.uom56')), int(query.get('B.uom56')), int(query.get('K.uom26'))]
        try:
            self.duration = int(query.get('D.uom42'))
        except TypeError:
            self.duration = 0
        try:
            if current_zone == 0:
                self.device.set_zone_color(zone, self.num_zones, self.new_color, self.duration, rapid=False)
            else:
                self.device.set_zone_color(zone, zone, self.new_color, self.duration, rapid=False, apply = 0)
        except (lifxlan.WorkflowException, IOError) as ex:
            LOGGER.error('set mz hsbkdz error %s', str(ex))

    commands = {
                    'DON': setOn, 'DOF': Light.setOff,
                    'APPLY': apply, 'QUERY': Light.query,
                    'SET_COLOR': setColor, 'SETH': setManual,
                    'SETS': setManual, 'SETB': setManual,
                    'CLITEMP': setManual, 'RR': setManual,
                    'SETZ': setManual, 'SET_HSBKDZ': setHSBKDZ,
                    'BRT': brighten, 'DIM': dim,
                    'FDUP': fade_up, 'FDDOWN': fade_down,
                    'FDSTOP': fade_stop, 'DFON': setOn,
                    'DFOF': Light.setOff, 'SETIR': Light.set_ir_brightness,
                    'WAVEFORM': Light.set_wf
                }

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 51},
                {'driver': 'GV0', 'value': 0, 'uom': 56},
                {'driver': 'GV1', 'value': 0, 'uom': 56},
                {'driver': 'GV2', 'value': 0, 'uom': 56},
                {'driver': 'GV3', 'value': 0, 'uom': 56},
                {'driver': 'CLITEMP', 'value': 0, 'uom': 26},
                {'driver': 'GV4', 'value': 0, 'uom': 56},
                {'driver': 'GV5', 'value': 0, 'uom': 2},
                {'driver': 'GV6', 'value': 0, 'uom': 20},
                {'driver': 'GV7', 'value': 0, 'uom': 56},
                {'driver': 'RR', 'value': 0, 'uom': 42}]

    id = 'lifxmultizone'


class Group(polyinterface.Node):
    """
    LiFX Group Node Class
    """
    def __init__(self, controller, primary, address, gid, label, gupdatedat):
        self.label = label.replace("'", "")
        super().__init__(controller, primary, address, 'LIFX Group ' + str(label))
        self.lifxLabel = label
        self.lifxGroup = self.controller.lifxLan.get_devices_by_group(label)
        self.numMembers = len(self.lifxGroup.devices)

    def start(self):
        self.update()
        #self.reportDrivers()

    def update(self):
        self.numMembers = len(self.lifxGroup.devices)
        self.setDriver('ST', self.numMembers)

    def long_update(self):
        pass

    def query(self, command = None):
        self.update()
        self.reportDrivers()

    def setOn(self, command):
        try:
            self.lifxGroup.set_power(True, rapid = False)
        except (lifxlan.WorkflowException, IOError) as ex:
            LOGGER.error('group seton error caught %s', str(ex))
        else:
            LOGGER.info('Received SetOn command for group {} from ISY. Setting all {} members to ON.'.format(self.label, self.numMembers))

    def setOff(self, command):
        try:
            self.lifxGroup.set_power(False, rapid = False)
        except (lifxlan.WorkflowException, IOError) as e:
            LOGGER.error('group setoff error caught {}'.format(str(e)))
        else:
            LOGGER.info('Received SetOff command for group {} from ISY. Setting all {} members to OFF.'.format(self.label, self.numMembers))

    def setColor(self, command):
        _color = int(command.get('value'))
        try:
            self.lifxGroup.set_color(COLORS[_color][1], 0, rapid = False)
        except (lifxlan.WorkflowException, IOError) as ex:
            LOGGER.error('group setcolor error caught %s', str(ex))
        else:
            LOGGER.info('Received SetColor command for group {} from ISY. Changing color to: {} for all {} members.'.format(self.name, COLORS[_color][0], self.numMembers))

    def setHSBKD(self, command):
        query = command.get('query')
        try:
            color = [int(query.get('H.uom56')), int(query.get('S.uom56')), int(query.get('B.uom56')), int(query.get('K.uom26'))]
            duration = int(query.get('D.uom42'))
        except TypeError:
            duration = 0

        try:
            self.lifxGroup.set_color(color, duration = duration, rapid = False)
        except (lifxlan.WorkflowException, IOError) as ex:
            LOGGER.error('group sethsbkd error caught {}'.format(str(ex)))
        else:
            LOGGER.info('Recieved SetHSBKD command for group {} from ISY, Setting all members to Color {}, duration {}'.format(self.label, color, duration))

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 56}]

    commands = {
                    'DON': setOn, 'DOF': setOff, 'QUERY': query,
                    'SET_COLOR': setColor, 'SET_HSBKD': setHSBKD
                }

    id = 'lifxgroup'

if __name__ == "__main__":
    try:
        polyglot = polyinterface.Interface('LiFX')
        polyglot.start()
        control = Controller(polyglot)
        control.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
