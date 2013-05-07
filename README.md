===============================
3m Experiment Magnet Controller
===============================
see http://danzimmerman.com/projects/supplycontroller/

Files:
++++
Python GUI
++++

magsupply.py : Magnet control GUI, Ethernet-enabled 4-20mA controller
	formerly /data/bin/3mcontrol/magsupply_0_6_1.py interoperates with sodium:/data/tech_info/arduino/mag_control_ethernet_v_0_5

++++
Arduino Firmware
++++

magcontrol.pde : Ethernet-enabled 4-20mA controller Arduino firmware
	in old system sodium:/data/tech_info/arduino/mag_control_ethernet_v_0_5 - interoperates with repo python/magsupply_0_6_1.py (now just magsupply.py)

