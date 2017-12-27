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
from functools import wraps
from copy import deepcopy
import queue
import threading
import json
import time

LOGGER = polyinterface.LOGGER
with open('server.json') as data:
    SERVERDATA = json.load(data)
try:
    VERSION = SERVERDATA['credits'][0]['version']
except (KeyError, ValueError):
    LOGGER.info('Version not found in server.json.')
    VERSION = '0.0.0'
_SLOCK = threading.Lock()

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


class LoggerWriter:
    def __init__(self, level):
        # self.level is really like using log.debug(message)
        # at least in my case
        self.level = level

    def write(self, message):
        # if statement reduces the amount of newlines that are
        # printed to the logger
        if message != '\n':
            self.level(message)

    def flush(self):
        # create a flush method so things can be flushed when
        # the system wants to. Not sure if simply 'printing'
        # sys.stderr is the correct way to do it, but it seemed
        # to work properly for me.
        self.level(sys.stderr)

sys.stderr = LoggerWriter(LOGGER.error)

def socketLock(f):
    """
    Python Decorator to check global Socket Lock on LiFX mechanism. This prevents
    simultaneous use of the socket, which caused instability on the previous release.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        with _SLOCK:
            result = f(*args, **kwargs)
        return result
    return wrapper

class Controller(polyinterface.Controller):
    def __init__(self, poly):
        super().__init__(poly)
        self.lifxLan = lifxlan.LifxLAN(None)
        self.name = 'LiFX Controller'
        self.discovery = False
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target = self.processQueue)
        LOGGER.info('Started LiFX Protocol')

    def start(self):
        LOGGER.info('Starting LiFX Polyglot v2 NodeServer version {}'.format(VERSION))
        self.thread.daemon = True
        self.thread.start()
        self.q.put(lambda: self.discover())
        #self.discover()
        #self.processQueue()

    def processQueue(self):
        while True:
            with self.lock:
                cmd = self.q.get()
                cmd()
            self.q.task_done()

    def longPoll(self):
        for node in self.nodes:
            time.sleep(.5)
            self.nodes[node].update()

    def update(self):
        """ Nothing to update for controller node. """
        pass

    def discover(self, command = {}):
        if self.discovery == True: return
        self.discovery = True
        LOGGER.info('Starting LiFX Discovery...')
        try:
            devices = self.lifxLan.get_lights()
            LOGGER.info('{} bulbs found. Checking status and adding to ISY if necessary.'.format(len(devices)))
            for d in devices:
                label = str(d.get_label())
                name = 'LIFX {}'.format(label)
                address = d.get_mac_addr().replace(':', '').lower()
                if not address in self.nodes:
                    mac = d.get_mac_addr()
                    ip = d.get_ip_addr()
                    if d.supports_multizone():
                        LOGGER.info('Found MultiZone Bulb: {}({})'.format(name, address))
                        self.addNode(MultiZone(self, self.address, address, name, mac, ip, label))
                    else:
                        LOGGER.info('Found Bulb: {}({})'.format(name, address))
                        self.addNode(Light(self, self.address, address, name, mac, ip, label))
                gid, glabel, gupdatedat = d.get_group_tuple()
                gaddress = glabel.replace("'", "").replace(' ', '').lower()[:12]
                if not gaddress in self.nodes:
                    LOGGER.info('Found LiFX Group: {}'.format(glabel))
                    self.addNode(Group(self, self.address, gaddress, gid, glabel, gupdatedat))
        except (lifxlan.WorkflowException, OSError, IOError, TypeError) as ex:
            LOGGER.error('discovery Error: {}'.format(ex))
        finally:
            self.discovery = False
            LOGGER.info('LiFX Discovery Complete.')

    commands = {'DISCOVER': discover}


class Light(polyinterface.Node):
    """
    LiFX Light Parent Class
    """
    def __init__(self, parent, primary, address, name, mac, ip, label):
        super().__init__(parent, primary, address, name)
        self.device = None
        self.mac = mac
        self.ip = ip
        self.name = name
        self.control = parent
        self.power = False
        self.parent = parent
        self.pending = False
        self.lock = threading.Lock()
        self.q = queue.Queue()
        self.thread = threading.Thread(target = self.processQueue)
        self.label = label
        self.connected = 1
        self.mz = False
        self.tries = 0
        self.uptime = 0
        self.color= []
        self.lastupdate = time.time()
        self.duration = 0

    def start(self):
        self.device = lifxlan.Light(self.mac, self.ip)
        self.thread.daemon = True
        self.thread.start()
        self.q.put(lambda: self.update())

    def query(self, command = None):
        self.update()
        self.reportDrivers()

    def processQueue(self):
        while True:
            with self.lock:
                cmd = self.q.get()
                cmd()
                self.q.task_done()

    def outQueue(self):
        while True:
            cmd = self.outQ.get()
            cmd()
            self.outQ.task_done()

    def update(self):
        self.q.put(lambda: self._update())

    def _update(self):
        self.connected = 0
        try:
            self.color = list(self.device.get_color())
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} bulb color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.connected = 1
            for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
                self.setDriver(driver, self.color[ind])
        try:
            self.power = 1 if self.device.get_power() == 65535 else 0
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} bulb power. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.connected = 1
            self.setDriver('ST', self.power)
        try:
            self.uptime = self.nanosec_to_hours(self.device.get_uptime())
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} bulb uptime. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.connected = 1
            self.setDriver('GV6', self.uptime)
        self.setDriver('GV5', self.connected)
        self.setDriver('RR', self.duration)
        self.lastupdate = time.time()

    def nanosec_to_hours(self, ns):
        return round(ns/(1000000000.0*60*60), 2)

    def setOn(self, *args, **kwargs):
        try:
            self.q.put(lambda: self.device.set_power(True))
            self.setDriver('ST', 1)
        except (lifxlan.WorkflowException): pass

    def setOff(self, *args, **kwargs):
        try:
            self.q.put(lambda: self.device.set_power(False))
            self.setDriver('ST', 0)
        except (lifxlan.WorkflowException): pass

    def setColor(self, command):
        if self.connected:
            _color = int(command.get('value'))
            try:
                self.q.put(lambda: self.device.set_color(COLORS[_color][1], duration=self.duration, rapid=False))
            except (lifxlan.WorkflowException, IOError): pass
            LOGGER.info('Received SetColor command from ISY. Changing color to: {}'.format(COLORS[_color][0]))
            for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
                self.setDriver(driver, COLORS[_color][1][ind])
        else: LOGGER.error('Received SetColor, however the bulb is in a disconnected state... ignoring')

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
            elif _cmd == 'SETK':
                self.color[3] = _val
                driver = ['CLITEMP', self.color[3]]
            elif _cmd == 'SETD':
                self.duration = _val
                driver = ['RR', self.duration]
            try:
                self.parent.q.put(lambda: self.device.set_color(self.color, self.duration, rapid=False))
            except (lifxlan.WorkflowException, IOError): pass
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
            self.q.put(lambda: self.device.set_color(self.color, duration=self.duration, rapid=False))
        except (lifxlan.WorkflowException, IOError): pass
        for ind, driver in enumerate(('GV1', 'GV2', 'GV3', 'CLITEMP')):
            self.setDriver(driver, self.color[ind])
        self.setDriver('RR', self.duration)

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 25},
                {'driver': 'GV1', 'value': 0, 'uom': 56},
                {'driver': 'GV2', 'value': 0, 'uom': 56},
                {'driver': 'GV3', 'value': 0, 'uom': 56},
                {'driver': 'CLITEMP', 'value': 0, 'uom': 26},
                {'driver': 'GV5', 'value': 0, 'uom': 25},
                {'driver': 'GV6', 'value': 0, 'uom': 20},
                {'driver': 'RR', 'value': 0, 'uom': 42}]

    id = 'lifxcolor'

    commands = {
                    'DON': setOn, 'DOF': setOff, 'QUERY': query,
                    'SET_COLOR': setColor, 'SETH': setManual,
                    'SETS': setManual, 'SETB': setManual,
                    'SETK': setManual, 'SETK': setManual,
                    'SETD': setManual, 'SET_HSBKD': setHSBKD
                }

class MultiZone(Light):
    def __init__(self, parent, primary, address, name, mac, ip, label):
        super().__init__(parent, primary, address, name, mac, ip, label)
        self.num_zones = 0
        self.current_zone = 0
        self.new_color = None
        self.mz = True
        self.pending = False

    def _update(self):
        self.connected = 0
        zone = deepcopy(self.current_zone)
        if self.current_zone != 0: zone -= 1
        if not self.pending:
            try:
                self.color = self.device.get_color_zones()
            except (lifxlan.WorkflowException, OSError) as ex:
                LOGGER.error('Connection Error on getting {} multizone color. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
            else:
                self.connected = 1
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
            self.connected = 1
            self.setDriver('ST', self.power)
        try:
            self.uptime = self.nanosec_to_hours(self.device.get_uptime())
        except (lifxlan.WorkflowException, OSError) as ex:
            LOGGER.error('Connection Error on getting {} multizone uptime. This happens from time to time, normally safe to ignore. {}'.format(self.name, str(ex)))
        else:
            self.connected = 1
            self.setDriver('GV6', self.uptime)
        self.setDriver('GV5', self.connected)
        self.setDriver('RR', self.duration)
        self.lastupdate = time.time()

    def query(self, command = None):
        self.q.put(lambda: self.update())
        self.reportDrivers()

    def start(self):
        self.device = lifxlan.MultiZoneLight(self.mac, self.ip)
        self.thread.daemon = True
        self.thread.start()
        self.update()
        #self.update()

    def setOn(self, *args, **kwargs):
        try:
            self.q.put(lambda: self.device.set_power(True))
            self.setDriver('ST', 1)
        except (lifxlan.WorkflowException): pass

    def setOff(self, *args, **kwargs):
        try:
            self.q.put(lambda: self.device.set_power(False))
            self.setDriver('ST', 0)
        except (lifxlan.WorkflowException): pass

    def apply(self, command):
        try:
            if self.new_color:
                self.color = deepcopy(self.new_color)
                self.new_color = None
            self.q.put(lambda: self.device.set_zone_colors(self.color, self.duration, rapid=True))
        except (lifxlan.WorkflowException, IOError): pass
        LOGGER.info('Received apply command for {}'.format(self.address))
        self.pending = False

    def setColor(self, command):
        if self.connected:
            try:
                _color = int(command.get('value'))
                zone = deepcopy(self.current_zone)
                if self.current_zone != 0: zone -= 1
                if self.current_zone == 0:
                    self.q.put(lambda: self.device.set_zone_color(self.current_zone, self.num_zones, COLORS[_color][1], self.duration, True))
                else:
                    self.q.put(lambda: self.device.set_zone_color(zone, zone, COLORS[_color][1], self.duration, True))
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
                elif _cmd == 'SETK':
                    new_color[3] = int(_val)
                    driver = ['CLITEMP', new_color[3]]
                elif _cmd == 'SETD':
                    self.duration = _val
                    driver = ['RR', self.duration]
                self.color[zone] = new_color
                if self.current_zone == 0:
                    self.q.put(lambda: self.device.set_zone_color(0, self.num_zones, new_color, self.duration, rapid=False))
                else:
                    self.q.put(lambda: self.device.set_zone_color(zone, zone, new_color, self.duration, rapid=False))
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
                self.q.put(lambda: self.device.set_zone_color(zone, self.num_zones, self.new_color, self.duration, rapid=False))
            else:
                self.q.put(lambda: self.device.set_zone_color(zone, zone, self.new_color, self.duration, rapid=False, apply = 0))
        except (lifxlan.WorkflowException, IOError) as ex:
            LOGGER.error('set mz hsbkdz error %s', str(ex))

    commands = {
                    'DON': setOn, 'DOF': setOff,
                    'APPLY': apply, 'QUERY': query,
                    'SET_COLOR': setColor, 'SETH': setManual,
                    'SETS': setManual, 'SETB': setManual,
                    'SETK': setManual, 'SETD': setManual,
                    'SETZ': setManual, 'SET_HSBKDZ': setHSBKDZ
                }

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 25},
                {'driver': 'GV1', 'value': 0, 'uom': 56},
                {'driver': 'GV2', 'value': 0, 'uom': 56},
                {'driver': 'GV3', 'value': 0, 'uom': 56},
                {'driver': 'CLITEMP', 'value': 0, 'uom': 26},
                {'driver': 'GV4', 'value': 0, 'uom': 56},
                {'driver': 'GV5', 'value': 0, 'uom': 25},
                {'driver': 'GV6', 'value': 0, 'uom': 20},
                {'driver': 'RR', 'value': 0, 'uom': 42}]

    id = 'lifxmultizone'

class Group(polyinterface.Node):
    """
    LiFX Group Node Class
    """
    def __init__(self, parent, primary, address, gid, label, gupdatedat):
        self.label = label.replace("'", "")
        super().__init__(parent, primary, address, 'LIFX Group ' + str(label))
        self.parent = parent
        self.group = gid
        self.lifxLabel = label
        self.updated_at = gupdatedat
        self.lifxGroup = self.parent.lifxLan.get_devices_by_group(label)
        self.numMembers = len(self.lifxGroup.devices)
        self.members = []

    def start(self):
        self.update()
        #self.reportDrivers()

    def update(self):
        #self.members = list(filter(lambda d: self.parent.nodes[d].group == self.label, self.parent.nodes))
        #self.lifxGroup = self.parent.lifxLan.get_devices_by_group(self.lifxLabel)
        self.numMembers = len(self.lifxGroup.devices)
        self.setDriver('ST', self.numMembers)

    def query(self, command = None):
        self.update()
        self.reportDrivers()

    def outQueue(self):
        while True:
            cmd = self.outQ.get()
            cmd()
            self.outQ.task_done()

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

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 25}]

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
