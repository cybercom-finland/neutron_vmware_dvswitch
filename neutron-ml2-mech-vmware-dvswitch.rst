..
 This work is licensed under a Creative Commons Attribution 3.0 Unported
 License.

 http://creativecommons.org/licenses/by/3.0/legalcode

===================================================
VMware dvSwitch/vSphere API support for Neutron ML2
===================================================

https://blueprints.launchpad.net/neutron/+spec/neutron-ml2-mech-vmware-dvswitch

This mechanism driver is created to support distributed virtual switches
on VMware vsphere. Currently, Neutron does not have such support.


Problem description
===================

In order to run OpenStack on top of VMware clusters and vSphere,
we need a network component to configure network connections
on the virtual hosts created by OpenStack.

In OpenStack Nova, everything else is handled,
except for the network connection of VMs.


Proposed change
===============

We propose a new mechanism driver for Neutron ML2 plugin
to handle network connections in vSphere.


Alternatives
------------

As it might be possible to handle network connections in Nova
as well as other things, it is more logical to handle this kind
of things via the network component i.e. Neutron.

We are not aware of any other ways to handle this.


Data model impact
-----------------

This mechanism driver does not need any database changes or additions.


REST API impact
---------------

This mechanism driver does not imply any REST API changes by itself,
because it is just a subcomponent of the Neutron ML2 plugin.


Security impact
---------------

This driver needs vSphere username and password
to be stored to the relevant configuration file.
Other than that, there should be no security related issues.


Notifications impact
--------------------

None.


Other end user impact
---------------------

None.


Performance Impact
------------------

The driver should not use any significant amount of resources.
At the initialization phase, a new worker thread and a watchdog
thread are created. Those threads will poll the driver's work
queue once per second or a couple of seconds. That's about it.

On the ML2 create_port_precommit and create_port_postcommit,
only quick sanity checks and work queue additions will be made.
The separate worker thread will make the vSphere API requests,
that are essentially just SOAP calls on HTTPS.
Implemented this way, the driver should not introduce
any noticeable delays or be able to block in the callbacks.


Other deployer impact
---------------------

This is a mechanism driver for ML2, so it should
be deployed as part of ML2 just like the other mech drivers are.


Developer impact
----------------

None.


Implementation
==============

Assignee(s)
-----------

Who is leading the writing of the code? Or is this a blueprint where you're
throwing it out there to see who picks it up?

If more than one person is working on the implementation, please designate the
primary author and contact.

Primary assignee:
  sjm-m

Other contributors:
  None

Work Items
----------

* Mech driver

* Example config


Dependencies
============

* The pyVmomi library for Python is mandatory for this driver to work.
  https://github.com/vmware/pyvmomi - this is a Python implementation
  of the vSphere API by VMware.


Testing
=======

We need 3rd party testing for this feature, because a working vSphere
installation is necessary. Cybercom is able to provide this testing
in the foreseeable future.


Documentation Impact
====================

None.


References
==========

https://github.com/cybercom-cloud/neutron_vmware_dvswitch

https://github.com/vmware/pyvmomi

http://lists.openstack.org/pipermail/openstack-dev/2014-May/034333.html
