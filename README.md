VMware dvSwitch ML2 Mechanism driver for ML2 plugin at OpenStack Neutron
========================================================================

Source: https://github.com/cybercom-finland/neutron_vmware_dvswitch

This mechanism driver implements Neutron ML2 Driver API and it is used
to manage the VMware vSphere infrastructure with a distributed virtual
switch (VMware dvSwitch).


Prerequisites
-------------

You will need the **pyVmomi** library for Python in order to be able
to communicate with vSphere servers.

* Please refer to:

https://github.com/vmware/pyvmomi

The pyVmomi SDK is a nice and clean Python API implementation
for **VMware vSphere API** - highly recommended.

VMware vCenter vSphere Permissions
VIRTUAL MACHINE
		CONFIGURATION
				MODIFY DEVICE SETTINGS
				SETTINGS
HOST
		CONFIGURATION
				SYSTEM MANAGEMENT


Deployment
----------

You need to add a `[ml2_dvs]` section to your `ml2_conf.ini`,
usually found at the directory `/etc/neutron/plugins/ml2/`.

The driver should reside in the directory
`/usr/lib/python2.6/site-packages/neutron/plugins/ml2/drivers/dvs/`
or similar, whatever is correct for your Neutron installation.

Most importantly, you have to enable the driver in your WSGI
Python environment by editing a file like

`/usr/lib/python2.6/site-packages/neutron-2013.2.3-py2.6.egg-info/entry_points.txt`

or similar, whatever is correct for your Python version and Neutron.


In the python egg metadata, you will find something like this:

	[neutron.ml2.type_drivers]
	flat = neutron.plugins.ml2.drivers.type_flat:FlatTypeDriver
	vlan = neutron.plugins.ml2.drivers.type_vlan:VlanTypeDriver
	local = neutron.plugins.ml2.drivers.type_local:LocalTypeDriver
	gre = neutron.plugins.ml2.drivers.type_gre:GreTypeDriver
	vxlan = neutron.plugins.ml2.drivers.type_vxlan:VxlanTypeDriver

	[neutron.ml2.mechanism_drivers]
	hyperv = neutron.plugins.ml2.drivers.mech_hyperv:HypervMechanismDriver
	l2population = neutron.plugins.ml2.drivers.l2pop.mech_driver:L2populationMechanismDriver
	ncs = neutron.plugins.ml2.drivers.mechanism_ncs:NCSMechanismDriver
	cisco_nexus = neutron.plugins.ml2.drivers.cisco.mech_cisco_nexus:CiscoNexusMechanismDriver
	openvswitch = neutron.plugins.ml2.drivers.mech_openvswitch:OpenvswitchMechanismDriver
	linuxbridge = neutron.plugins.ml2.drivers.mech_linuxbridge:LinuxbridgeMechanismDriver
	arista = neutron.plugins.ml2.drivers.mech_arista.mechanism_arista:AristaDriver
	test = neutron.tests.unit.ml2.drivers.mechanism_test:TestMechanismDriver
	logger = neutron.tests.unit.ml2.drivers.mechanism_logger:LoggerMechanismDriver
	dvs = neutron.plugins.ml2.drivers.dvs.mechanism_dvs:VmwareDvswitchMechanismDriver


As you can see, the last line about **dvs** is important for us.
You probably need to add it manually, if you are installing
the dvSwitch driver separately, after installing Neutron from a package.



Configuration
-------------

First you have to enable the dvswitch mechanism driver from the ml2 config:

	[ml2]
	type_drivers = local,flat,vlan
	tenant_network_types = local,flat,vlan
	mechanism_drivers = openvswitch,dvs
	...

Then configure the dvs mech driver, use something like:

	[ml2_dvs]
	vsphere_server = my.vsphere.server.local
	vsphere_user = vsphereuser
	vsphere_pass = mypassword
	dvs_name = my-dvSwitch-name


A more complete example config with comments is included in the repo.
The default values for various tuning knobs should be reasonable,
so you should usually only need to specify vsphere server, user, password
and of course, the relevant dvSwitch name in your environment.

Please refer to `ml2_conf_dvs.ini` example config.



Random details about the implementation
---------------------------------------

In VMware, to connect a Virtual Machine (VM) to a certain
network/subnet/vlan/portgroup, you don't really configure
the dvswitch at all. The connection is made by *reconfiguring
the virtual network card* of the VM. In VMware terms, you make
a new *backing* for the virtual device and then issue a *VM Reconfigure
Request* for the given VM via the vSphere API.

Of course, the reconfiguration can only be done *after the VM is created*.
OpenStack and Neutron will call this driver well before
the relevant VM does even exist. All this means that the
driver must keep a **TODO List** of all VM Reconfiguration requests
to be done.

The TODO request is handled by a *separate worker thread* in some 10 seconds
after the driver's `create_port_postcommit()` call. The exact timing
values are configurable, with reasonable defaults.
The worker TODO List resides in memory only.

The VM reconfiguration attempts might be repeated until the driver
detects that the VM exists and the network connection of the VM
is what it should be, i.e. the *port backing* of the virtual ethernet
is correct.

This periodic checking with adjustable polling interval is done
in order to rule out any sporadic errors in vSphere.
If the reconfiguration really does not *ever* succeed,
the failing TODO task will finally expire.

The default TODO request expiration time is 5 minutes and adjustable.
The driver is trying hard to be as robust as possible without being
too spammy for the vSphere server.

The vSphere connection and login session is first requested at the
driver initialization phase. The vSphere session handle is stored
in the driver's in-memory state, and checked for validity immediately
before each real vSphere API call. The checking is done by asking
the current time from the vSphere server. If this fails, a new login
is attempted right away, just before the actual vSphere API call.
This behaviour is in accordance with the vSphere API Best Practices.
Usually there is a session idle timeout of 30 minutes
in the vSphere server side.

At the driver initialization, the relevant dvSwitch is searched for
by its name and the driver will read the *port group information*
from the dvSwitch. This port group data will be stored to the driver's
in-memory state. The information will be automatically refreshed
from vSphere in every 10 minutes (adjustable).

The OpenStack/Neutron network names are matched with the VMware dvSwitch
portgroup names. The driver does care about the VLAN ID.



Restrictions, shortcomings, bugs, warnings, TODO
------------------------------------------------

* **Only VLAN network type is relevant and supported.**

* There is not yet support for portgroup i.e. OpenStack network
  creation. **All networks must have pre-existing portgroups in the dvSwitch.**

* **Only VMs with a single nic are supported.**
  Or at least, the driver only supports connecting the first nic.

* There is no permanent state e.g. in form of SQL tables for this driver.
  The TODO queue is volatile, because it resides only in the driver's
  in-memory state. It will be lost on Neutron server restart.
  **Care should be taken to not restart the Neutron server while there are
  any VM creation in progress.**

* Edit: There is now a watchdog thread capable of restarting the worker.

* So far the driver has only been tested with vSphere version 5.1.
  There should really be no reason why it would not run with any
  newer version as well. **Please give us feedback.**

* The driver works only if Neutron server process is single threaded.


Contact
-------

Issues/Questions/Bugs: GitHub
