
VMware dvSwitch ML2 Mechanism driver for ML2 plugin at OpenStack Neutron
========================================================================

This mechanism driver implements Neutron ML2 Driver API and it is used
to manage the VMware vSphere infrastructure with a distributed virtual
switch (VMware dvSwitch).



Contact
-------

Issues/Questions/Bugs: sjm@cybercom.fi



Prerequisites
-------------

You will need the **pyVmomi** library for Python in order to be able
to communicate with vSphere servers.

* Please refer to:

https://github.com/vmware/pyvmomi

The pyVmomi SDK is a nice and clean Python API implementation
for **VMware vSphere API** - highly recommended.



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
the dvswitch at all. The connection is made only by reconfiguring
the virtual network card of the VM. In VMware terms, you make
a new *backing* for the virtual device and then issue a VM Reconfigure
event for the given VM.

Of course, this can only be done after the VM is created.
OpenStack and Neutron will call this driver well before
the relevant VM does even exist. All this means that the
driver must keep a TODO list of all *VM Reconfigure* requests to come.

This is done by a separate worker thread in some 10 seconds
after the driver `create_port_postcommit()` call. The exact timing
values are configurable, with reasonable defaults.
The worker TODO list resides in memory only.

At the driver initialization, the relevant dvSwitch is searched
and the driver will read the *port group information* from the dvSwitch.
This port group data will be stored in memory and automatically refreshed
from vSphere in every 10 minutes (adjustable).



Restrictions
------------

There is no permanent state e.g. in form of SQL tables for this driver.
This means that the TODO queue is volatile and will be lost
on Neutron server restart.

So far the driver has only been tested with vSphere version 5.1.
There should really be no reason why it would not run with any
newer version as well. Please give us feedback.
