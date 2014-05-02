# mechanism_dvs.py
#
# Copyright 2014 Cybercom Finland Oy
# All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# Author:
# Sami J. Makinen <sjm@cybercom.fi>

"""Implentation of VMware dvSwitch ML2 Mechanism driver for Neutron"""

import time
import threading

from oslo.config import cfg

from neutron.common import exceptions
from neutron.openstack.common import log as logging
from neutron.plugins.ml2 import driver_api as api

from pyVim.connect import SmartConnect as SmartConnect
from pyVim.connect import Disconnect as Disconnect
from pyVmomi import vim, vmodl


LOG = logging.getLogger(__name__)
MECHANISM_VERSION = 0.42
NET_TYPES_SUPPORTED = ('vlan',)



ML2_DVS = [
    cfg.StrOpt('vsphere_server', default='127.0.0.1',
               help=_('The server hostname or IP address'
                      ' of the vSphere SOAP API')),
    cfg.StrOpt('vsphere_user', default='admin',
               help=_('The username to use for vSphere API')),
    cfg.StrOpt('vsphere_pass', default='password', secret=True,
               help=_('The password to use for vSphere API')),
    cfg.StrOpt('dvs_name', default='mydvswitch',
               help=_('The name of VMware dvSwitch to use')),

    cfg.StrOpt('vsphere_proto', default='https',
               help=_('The vSphere API protocol: http or https')),
    cfg.IntOpt('vsphere_port', default=443,
               help=_('The vSphere API port, usually 80 or 443')),
    cfg.StrOpt('vsphere_path', default='/sdk',
               help=_('The vSphere API path, usually /sdk')),

    cfg.IntOpt('dvs_refresh_interval', default=600,
               help=_('How often to refresh dvSwitch portgroup information'
                      ' from vSphere')),

    cfg.IntOpt('todo_loop_interval', default=2,
               help=_('How often to poll TODO list for'
                      ' doable or expired work')),
    cfg.IntOpt('todo_initial_wait', default=10,
               help=_('How long to wait before initial attempt'
                      ' to reconfigure a new VM')),
    cfg.IntOpt('todo_polling_interval', default=6,
               help=_('How long to wait before another attempt'
                      ' to check a particular VM')),
    cfg.IntOpt('todo_expire_time', default=300,
               help=_('How long to keep trying for a particular VM')),
]
cfg.CONF.register_opts(ML2_DVS, "ml2_dvs")


class DvsConfigError(exceptions.NeutronException):
    message = _('%(msg)s')

class DvsRuntimeError(exceptions.NeutronException):
    message = _('%(msg)s')



TODO_CLASS_DEFAULT_EXPIRE = 300

class TodoEntry():
    def __init__(self, item, starttime=None, expiretime=None):
        if not starttime: starttime = time.time()
        if not expiretime: expiretime = starttime + TODO_CLASS_DEFAULT_EXPIRE

        self.starttime = starttime
        self.expiretime = expiretime
        self.done = False
        self.item = item


class TodoList():
    def __init__(self):
        self.todo = []
        self.lock = threading.Lock()

    def _cleanup(self, now=None):
        if not now: now = time.time()
        self.lock.acquire(blocking=True)
        for entry in self.todo:
            if entry.done or now >= entry.expiretime:
                self.todo.remove(entry)
        self.lock.release()
        return self

    def add(self, item, starttime, expiretime):
        now = time.time()
        LOG.info(_("todo add item=%s now=%d starttime-delta %d expire-delta %d"
                   % (repr(item), now, starttime-now, expiretime-now)))

        entry = TodoEntry(item, starttime=starttime, expiretime=expiretime)
        self.lock.acquire(blocking=True)
        self.todo.append(entry)
        self.lock.release()

    def get_tasks(self):
        doable_list = []
        now = time.time()
        self._cleanup(now)
        self.lock.acquire(blocking=True)
        for entry in self.todo:
            if now >= entry.starttime:
                doable_list.append(entry)
        self.lock.release()
        return tuple(doable_list)


class VmwareDvswitchMechanismDriver(api.MechanismDriver):
    """ML2 Mechanism driver for VMWare dvSwitches"""

    def __init__(self):
        LOG.info(_("dvs.__init__(): %s" % repr(self)))
        try:
            self.vsphere_server = cfg.CONF.ml2_dvs.vsphere_server
            self.vsphere_user = cfg.CONF.ml2_dvs.vsphere_user
            self.vsphere_pass = cfg.CONF.ml2_dvs.vsphere_pass
            self.vsphere_proto = cfg.CONF.ml2_dvs.vsphere_proto
            self.vsphere_port = int(cfg.CONF.ml2_dvs.vsphere_port)
            self.vsphere_path = cfg.CONF.ml2_dvs.vsphere_path

            self.dvs_name = cfg.CONF.ml2_dvs.dvs_name
            self.dvs_refresh_interval = int(cfg.CONF.ml2_dvs.dvs_refresh_interval)

            self.todo_loop_interval = int(cfg.CONF.ml2_dvs.todo_loop_interval)
            self.todo_initial_wait = int(cfg.CONF.ml2_dvs.todo_initial_wait)
            self.todo_polling_interval = int(cfg.CONF.ml2_dvs.todo_polling_interval)
            self.todo_expire_time = int(cfg.CONF.ml2_dvs.todo_expire_time)

            self.si_lock = threading.Lock()
            self.dvs_lock = threading.Lock()
            self.si = None
            self.todo = TodoList()

        except Exception as error:
            msg = (_("Could not Initialize parameters: %(err)s") %
                     {'err': error})
            LOG.exception(msg)
            raise DvsConfigError(msg=msg)

        # instance init okay
        return None


    def initialize(self):
        LOG.info(_("ML2 dvs driver initializing"))
        self._init_si()
        self._update_dvs()
        self.pg_ts = time.time()
        self.worker = threading.Thread(target=self._todo_worker)
        self.worker.start()
        LOG.info(_("dvs driver initialized: dvs_name=%s dvs_refresh=%d" %
                   (self.dvs_name, self.dvs_refresh_interval)))
        return self


    def _todo_worker(self):
        LOG.info(_("TODO worker thread started with"
                   " loop interval: %d initial wait: %d polling interval: %d expire time: %d" %
                   (self.todo_loop_interval, self.todo_initial_wait,
                    self.todo_polling_interval, self.todo_expire_time)))

        while True:
            now = time.time()
            tasks = self.todo.get_tasks()
            if tasks: LOG.info(_("Worker found %d doable tasks"), len(tasks))

            for entry in tasks:
                LOG.info(_("TODO worker: connect vm %s to network %s") %
                         (entry.item[0], entry.item[1]))

                if self._connect_vm(entry.item[0], entry.item[1]):
                    entry.done = True
                else:
                    entry.starttime = now + self.todo_polling_interval

            time.sleep(self.todo_loop_interval)


    def _check_si(self):
        try:
            ret = self.si.CurrentTime()
        except Exception as error:
            if not self.si == None:
                msg = (_("check_si failed, error: %(err)s") %
                       {'err': error})
                LOG.info(msg)
            self._init_si()
        return self


    def _init_si(self):
        if not self.si_lock.acquire(blocking=False):
            # Another thread must be already doing this. Bailing out.
            return self

        try:
            LOG.info(_("CONNECT - proto %s server %s port %d path %s"
                       " user %s dvs_name %s") %
                     (self.vsphere_proto, self.vsphere_server,
                      self.vsphere_port, self.vsphere_path,
                      self.vsphere_user, self.dvs_name))

            self.si = SmartConnect(protocol=self.vsphere_proto,
                                   host=self.vsphere_server,
                                   port=self.vsphere_port,
                                   path=self.vsphere_path,
                                   user=self.vsphere_user,
                                   pwd=self.vsphere_pass)
            self.si_lock.release()

        except Exception as error:
            self.si = None
            self.si_lock.release()
            msg = (_("Could not connect to vsphere server: %(err)s") %
                     {'err': error})
            LOG.exception(msg)
            raise DvsRuntimeError(msg=msg)

        return self


    def _check_dvs(self):
        """Periodically update dvs metadata from vsphere"""

        # Always ensure vsphere connection is okay
        self._check_si()

        # Do we need to refresh dvSwitch information?
        if time.time() < self.pg_ts + self.dvs_refresh_interval:
            return self

        # Possibly stale dvs information, update it and store the timestamp.
        # My name is Case, Justin Case.

        if not self.dvs_lock.acquire(blocking=False):
            # Some other thread is already doing this.
            return self

        try:
            self._update_dvs()
            self.pg_ts = time.time()
            self.dvs_lock.release()
        except Exception as error:
            self.dvs_uuid = None
            self.pg_ts = time.time()
            self.pg_key = None
            self.pg_name = None
            self.dvs_lock.release()
            msg = (_("dvs update failed: %(err)s") %
                     {'err': error})
            LOG.exception(msg)
            raise DvsRuntimeError(msg=msg)

        return self


    def _update_dvs(self):
        """Update dvs metadata from vsphere"""

        # Should not be called from any other method than
        # initialize() or _check_dvs()

        c = self.si.content
        mydvs = None
        self.dvs_uuid = None

        oview = c.viewManager.CreateContainerView(c.rootFolder, [vim.DistributedVirtualSwitch], True)
        for dvs in oview.view:
            if not dvs.name == self.dvs_name: continue

            mydvs = dvs
            self.dvs_uuid = dvs.summary.uuid
            break
        oview.Destroy()

        if not mydvs:
            msg = (_("Could not find dvs \"%s\"") % self.dvs_name)
            LOG.exception(msg)
            raise DvsRuntimeError(msg=msg)

        self.pg_key = {}
        self.pg_name = {}
        for pg in mydvs.portgroup:
            print repr((pg.config.name, pg.key))
            self.pg_key[pg.config.name] = pg.key
            self.pg_name[pg.key] = pg.config.name

        return self


    def _find_vm(self, name):
        """Find VM by name"""
        c = self.si.content
        myvm = None

        oview =  c.viewManager.CreateContainerView(c.rootFolder, [vim.VirtualMachine], True)
        for vm in oview.view:
            if not vm.name == name: continue
            myvm = vm
            break
        oview.Destroy()
        return myvm


    def _connect_vm(self, vm_uuid, pg_name):
        LOG.info(_("_connect_vm uuid %s port group %s") % (vm_uuid, pg_name))
        self._check_si()

        try:
            myvm = self._find_vm(vm_uuid)
            if not myvm:
                LOG.info(_("VM not found yet. Never gonna give you up."
                           " Just kidding, eventually I will."))
                return None

        except Exception as error:
            LOG.info(_("*** _find_vm(%s) failed: %s") %
                     (vm_uuid, error))
            return False

        try:
            nic = []
            for vd in myvm.config.hardware.device:
                if isinstance(vd, vim.vm.device.VirtualEthernetCard):
                    nic.append(vd)

            # NOTE: currently we support only nic0 connections
            if len(nic) > 1: LOG.info(_("WARNING: VM %s has %d nics") %
                                      (vm_uuid, len(nic)))

        except Exception as error:
            LOG.info(_("*** VM %s device enumeration failed: %s") %
                     (vm_uuid, error))
            return False

        if nic[0].backing.port.portgroupKey == self.pg_key[pg_name]:
            LOG.info(_("*** VM %s nic0 port group OK") %
                     vm_uuid)
            # Connection has been successful, return True
            return True

        else:
            LOG.info(_("*** Changing VM %s nic0 port group to %s") %
                     (vm_uuid, pg_name))

            try:
                conn = vim.dvs.PortConnection()
                conn.switchUuid = self.dvs_uuid
                conn.portgroupKey = self.pg_key[pg_name]
                backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo()
                backing.port = conn

                # Create a new object of same type as nic[0]
                veth = type(nic[0])()
                veth.key = nic[0].key

                # MAC address is preserved
                veth.macAddress = nic[0].macAddress
                # New backing - with the desired port group
                veth.backing = backing

                vdev = vim.vm.device.VirtualDeviceSpec()
                vdev.operation = vim.vm.device.VirtualDeviceSpec.Operation('edit')
                vdev.device = veth

                vmc = vim.vm.ConfigSpec()
                vmc.deviceChange.append(vdev)

                LOG.info(_("*** Sending VM %s Reconfigure request.") %
                         vm_uuid)
                myvm.Reconfigure(vmc)

            except Exception as error:
                LOG.info(_("*** Error: VM %s Reconfiguration failed: %s") %
                         (vm_uuid, error))

            # We just TRIED to reconfigure the VM,
            # so we return False right now.

            # We do not blindly trust that this will succeed
            # at the first attempt. Usually it will, though.

            # The VM nic0 connection will be re-checked later after a delay.
            # The task will be marked as "done" only after the (re)connection
            # has been successful and True returned from this method.

            return False


    def create_port_precommit(self, mech_context):
        """Sanity check for port creation/connection"""

        LOG.info(_("create_port_precommit called, sanity check."))

        port = mech_context.current
        net = mech_context.network.current

        myname = net.get('name')
        if not self.pg_key.has_key(myname):
            msg = (_("Could not find portgroup name \"%s\"") % myname)
            LOG.exception(msg)
            self.si = None
            raise DvsRuntimeError(msg=msg)

        mytype = net.get('provider:network_type')
        if not mytype in NET_TYPES_SUPPORTED:
            msg = (_("Unsupported provider:network_type \"%s\"") % mytype)
            LOG.exception(msg)
            self.si = None
            raise DvsRuntimeError(msg=msg)

        return None


    def create_port_postcommit(self, mech_context):
        """Associate the assigned vlan/portgroup to the VM."""

        self._check_dvs()
        now = time.time()

        port = mech_context.current
        net = mech_context.network.current

        mypg = net.get('name')
        vm_uuid = port.get('device_id')

        # The worker thread will really handle the VM network reconfig.
        # We cannot just sit and wait here.

        self.todo.add(item = (vm_uuid, mypg),
                      starttime = now + self.todo_initial_wait,
                      expiretime = now + self.todo_expire_time)
        return None


    def delete_port_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        #LOG.info(_("delete_port_precommit: called"))


    def delete_port_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.info(_("delete_port_postcommit: called"))
        self._check_dvs()


    def update_port_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        #LOG.info(_("update_port_precommit: called"))


    def update_port_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.info(_("update_port_postcommit: called"))
        self._check_dvs()


    def create_network_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        #LOG.info(_("create_network_precommit: called"))


    def create_network_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.info(_("create_network_postcommit: called"))
        self._check_dvs()


    def delete_network_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        #LOG.info(_("delete_network_precommit: called"))


    def delete_network_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.info(_("delete_network_postcommit: called"))
        self._check_dvs()


    def update_network_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        #LOG.info(_("update_network_precommit: called"))


    def update_network_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.info(_("update_network_postcommit: called"))
        self._check_dvs()


    def create_subnet_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        #LOG.info(_("create_subnet_precommit: called"))


    def create_subnet_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.info(_("create_subnet_postcommit: called"))
        self._check_dvs()


    def delete_subnet_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        #LOG.info(_("delete_subnet_precommit: called"))


    def delete_subnet_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.info(_("delete_subnet_postcommit: called"))
        self._check_dvs()


    def update_subnet_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        #LOG.info(_("update_subnet_precommit(self: called"))


    def update_subnet_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.info(_("update_subnet_postcommit: called"))
        self._check_dvs()

# EOF mechanism_dvs.py
