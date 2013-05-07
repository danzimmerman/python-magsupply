#v 0.6 changes time zone bug : need conditional time.altzone/time.timezone depending on time.localtime().tm_isdst
#this version is magsupply_0_6_1.py in the old versioning system, switched to git in /home/axl/python/magsupply for further changes, copy MANUALLY to /data/bin/3mcontrol for now!!!
#this version has lots of testing to help 

from PySide import QtCore
from PySide.QtCore import *
from PySide.QtGui import *
from collections import deque

import sys, time, serial, math, Queue, random,signal
import datetime
import socket
import telnetlib

MAXIMUM_VOLTAGE = 200.0 #anything less than the 270V supply max.  No more than 150V for the single 3m magnet
#BASE_DIRECTORY = '/data/sixtycm/' #full path with trailing slash to the directory where "today's date" directories are stored
BASE_DIRECTORY = '/data/3m/'
#LOG_FILE_NAME = '60cm_heater.log'
LOG_FILE_NAME = 'magnet.log'
HOST = '192.168.1.177'  #the IP address of the Arduino ethernet
PORT = '8888' #the port
TELNET_TIMEOUT = 30
TELNET_DEBUG_LEVEL = 0
DEBUG_PRINT = 0

def fofl(tmp1, d): #function to format floats with d decimal places
	tmp2 = QString('%1').arg(tmp1,0,'f',d)
	return tmp2

def stringintgr(tmp1):
	tmp2 = str(tmp1)
	return tmp2



class MainMagControlWindow(QWidget):
	def __init__(self):
		QWidget.__init__(self, None)
		self.setWindowTitle('Magnet Control')
		# set up boxes, controls and limits

		grid = QGridLayout()
		
		
		#column 1 of 3 (0,1,2) is just a spacer
		grid.setColumnMinimumWidth(1,50)
		#label for a slider to set voltage
		slabel = QLabel()
		slabel.setText('Voltage\nSlider')
		grid.addWidget(slabel,0,0)
		#set up the slider
		self.voltslider = QSlider(Qt.Vertical)
		self.voltslider = QSlider(Qt.Vertical)
		grid.addWidget(self.voltslider,1,0,4,1)
		self.voltslider.setMinimum(0.0)
		self.voltslider.setMaximum(MAXIMUM_VOLTAGE)

		#a 'set to zero volts' button
		self.offbutton = QPushButton('&Off!')
		grid.addWidget(self.offbutton,5,0)
		#label for current read from supply
		timelabel = QLabel()
		timelabel.setText('Time (ssm)')
		grid.addWidget(timelabel,0,1);
		#box for current
		self.timebox = QDoubleSpinBox()
		self.timebox.setMinimum(0)
		self.timebox.setMaximum(86400)
		self.timebox.setSingleStep(1)
		self.timebox.setDecimals(0)
		self.timebox.setButtonSymbols(QAbstractSpinBox.NoButtons)
		self.timebox.setReadOnly(1)
		grid.addWidget(self.timebox,1,1)


		#input box label
		inlabel = QLabel()
		inlabel.setText('Set Voltage ('+str(MAXIMUM_VOLTAGE)+'V Max)')
		grid.addWidget(inlabel,0,2)
		#box for input voltage
		self.inbox = QDoubleSpinBox()
		self.inbox.setMinimum(0)
		self.inbox.setMaximum(MAXIMUM_VOLTAGE)
		self.inbox.setSingleStep(0.1)
		self.inbox.setDecimals(2)
		self.inbox.setSuffix(' V')
		self.inbox.setKeyboardTracking(0)
		grid.addWidget(self.inbox,1,2)

		#output microamps box label
		outlabel = QLabel()
		outlabel.setText('Command Microamps')
		grid.addWidget(outlabel,2,2);
		#box for outgoing microamp command string
		self.outbox = QDoubleSpinBox()
		self.outbox.setMinimum(4000)
		self.outbox.setMaximum(20000)
		self.outbox.setSingleStep(1)
		self.outbox.setDecimals(0)
		self.outbox.setSuffix(' uA')
		self.outbox.setButtonSymbols(QAbstractSpinBox.NoButtons)
		self.outbox.setReadOnly(1)
		grid.addWidget(self.outbox,3,2)
		

		#label for current read from supply
		currentlabel = QLabel()
		currentlabel.setText('Measured Current')
		grid.addWidget(currentlabel,4,2);
		#box for current
		self.currentbox = QDoubleSpinBox()
		self.currentbox.setMinimum(-200)
		self.currentbox.setMaximum(1000)
		self.currentbox.setSingleStep(0.1)
		self.currentbox.setDecimals(4)
		self.currentbox.setSuffix(' A')
		self.currentbox.setButtonSymbols(QAbstractSpinBox.NoButtons)
		self.currentbox.setReadOnly(1)
		grid.addWidget(self.currentbox,5,2)
		
		self.setLayout(grid)
		
		#self.connect(self.voltslider, SIGNAL('valueChanged(int)'), self.inbox, SLOT('setValue(int)')) #old style, fixing!
		self.voltslider.valueChanged.connect(self.inbox.setValue) #new slider/box connex

		self.ipp = InputProcessor()
		self.inbox.valueChanged.connect(self.ipp.calc_command_microamps)
		self.ipp.command_microamps_changed.sig.connect(self.outbox.setValue)
		self.ipp.voltage_update_slider.sig.connect(self.voltslider.setValue)
		self.ipp.voltage_reupdate_box.sig.connect(self.inbox.setValue)
		self.offbutton.clicked.connect(self.ipp.set_to_zero)

		
		self.comm_thread = CommunicateAndLogThread(1)
		self.comm_thread.got_some_data.sig.connect(self.currentbox.setValue) #update the box with the data emitted by the comm thread
		self.comm_thread.got_the_time.sig.connect(self.timebox.setValue)
		self.offbutton.clicked.connect(self.comm_thread.zero_the_time)
		self.comm_thread.got_microamps_from_logfile.sig.connect(self.ipp.recalc_command_microamps)
		self.ipp.command_microamps_changed.sig.connect(self.comm_thread.update_the_thread_microamps)
		
		self.comm_thread.start()

class makeFloatSignal(QObject):
	sig = Signal(float)

class CommunicateAndLogThread(QThread):
	def __init__(self,assignedThreadID):
		QThread.__init__(self)
		self.time_started = self.time_sec_since_midnight()
		self.timenow = -1
		self.this_thread_microamps = 4000
		self.todaysdate = datetime.date.today().strftime('%m%d%y')
		self.do_initialization= 1
		self.lastline = [0, 4000, 0]
		self.last_command_microamps = 4000.0
		self.ID = assignedThreadID
		self.got_some_data = makeFloatSignal()
		self.got_the_time = makeFloatSignal()
		self.got_microamps_from_logfile = makeFloatSignal()
		#construct the logfile name from the global BASE_DIRECTORY, today's date,
		#and the desired LOG_FILE_NAME, and print that and the start time to the console
		print 'Started at', self.time_started,' seconds since midnight'
		self.logfile = BASE_DIRECTORY+self.todaysdate+'/'+LOG_FILE_NAME
		print 'logging to: '+self.logfile
		
		try :
			h = open(self.logfile, 'r')
			if DEBUG_PRINT:
				print 'h is', h
			for line in deque(h,maxlen=1):
				self.lastline=line.split()
			self.last_command_microamps = self.lastline[1]
			self.do_initialization = 0
			print LOG_FILE_NAME+' exists, grabbing last commanded value...'
			print 'Last Command Is', self.last_command_microamps
			self.this_thread_microamps = self.last_command_microamps
			self.got_microamps_from_logfile.sig.emit(self.last_command_microamps)
			h.close()
		except IOError :
			h = open(self.logfile, 'w')
			h.close()

	def run(self):
		self.running = 0
		self.starting = 1
		while self.starting:
			telnetconn = telnetlib.Telnet()
			telnetconn.set_debuglevel(TELNET_DEBUG_LEVEL)
			#print 'try to open'
			if self.do_initialization:
				print 'No '+LOG_FILE_NAME+'; initializing...'
				try: 
					telnetconn.open(HOST,PORT)
					telnetconn.write('stop:\n')
					telnetconn.close()
				except socket.error:
					print round(self.time_sec_since_midnight()), 'Error initializing telnet connection and resetting supply'
					pass
			try:
				telnetconn.open(HOST,PORT)
				#print 'try to read the $ready$'
				telnetconn.write('set:'+str(self.last_command_microamps)+'\n')
				telnetconn.read_very_eager()
				startmsg = telnetconn.read_until('\n')
				
				print startmsg
				print round(self.time_sec_since_midnight()), 'Connected!'
				self.starting = 0
				self.running = 1
			except socket.error:
				print round(self.time_sec_since_midnight()), 'Error opening telnet connection for command, trying again in 15s'
				time.sleep(15)
				pass
		
		
		
		
		while self.running:
			try:
				telnetconn.write('set:'+str(self.this_thread_microamps)+'\n')
				if DEBUG_PRINT:
					print 'tried to write to the arduino...'
				time.sleep(0.005)
				if DEBUG_PRINT:
					print 'slept after writing'
				
				ack = telnetconn.read_until('\n',1)
				if DEBUG_PRINT:
					print 'acknowledgement=',ack
				time.sleep(0.005)
				if DEBUG_PRINT:
					print 'now trying to read the data...'
				telnetconn.write('read:\r\n')
				time.sleep(0.005)
				mssg = telnetconn.read_until('\n')
			except EOFError:
				print round(self.time_sec_since_midnight()), 'EOF Reached - Check Connection'
				self.running = 0
				self.starting = 1
				pass

			#print 'mssg=',mssg
			timestamp = self.time_sec_since_midnight()
			supply_data_array = mssg.split()
			#print timestamp,supply_data_array
			returned_microamps = long(supply_data_array[1])
			returned_magcurrent = float(supply_data_array[2])
			#print str(returned_magcurrent)
			self.got_the_time.sig.emit(round(timestamp))
			self.got_some_data.sig.emit(returned_magcurrent) #emit the signal 'received_some_data' with the current relative time
			
			try:
				signal.alarm(3)
				lf = open(self.logfile,'a')
				lf.write(str(timestamp)+' '+str(returned_microamps)+' '+str(returned_magcurrent)+'\n')
				lf.close()
			except Exception :
				print timestamp, 'timeout writing magnet.log'
				#signal.alarm(0)
				pass
			time.sleep(0.034183)  #adjusted for 20Hz sample rate
			time.sleep(0.05) #brings it to 10Hz



	@QtCore.Slot(float)
	def zero_the_time(self):
		self.t0 = time.time()
	def stop_thread_running(self):
		self.running = 0
	def time_sec_since_midnight(self):
		if time.localtime().tm_isdst == 0:
			tmptime=time.time()-time.timezone # seconds (local) since unix epoch, not daylight savings time
		if time.localtime().tm_isdst == 1:
			tmptime=time.time()-time.altzone # seconds (local) since unix epoch, daylight savings time
		self.timemidnight = math.floor((tmptime/86400.0))*86400.0 #seconds from epoch to midnight
		return tmptime-self.timemidnight
	@QtCore.Slot(float)
	def update_the_thread_microamps(self,uafloatin):
		self.this_thread_microamps = long(uafloatin)


class InputProcessor():
	def __init__(self):
		self.commandvoltage = 0
		self.magnetcurrent = 0
		self.commandmicroamps = 0
		self.Avolt = (65300.0-13065.0)/(20000.0-4000.0)
		self.Bvolt = 65300.0-20000.0*self.Avolt
		self.command_microamps_changed = makeFloatSignal()
		self.voltage_update_slider = makeFloatSignal()
		self.voltage_reupdate_box = makeFloatSignal()

	@QtCore.Slot(float)
	def calc_command_microamps(self,commandedvoltage):
		self.microamps = round(16000.0*commandedvoltage/270.0+ 4000.0)
		self.command_microamps_changed.sig.emit(self.microamps)  #this line means 'emit the signal 'command_microamps_changed' with a value of self.microamps'
		self.voltint = int(commandedvoltage)
		self.voltage_update_slider.sig.emit(self.voltint)
		self.voltage_reupdate_box.sig.emit(commandedvoltage)

	@QtCore.Slot(float)
	def set_to_zero(self):
		self.voltage_update_slider.sig.emit(0)
		self.voltage_reupdate_box.sig.emit(0)

	@QtCore.Slot(float)
	def recalc_command_microamps(self,microamps_read_from_logfile):
		self.microamps = microamps_read_from_logfile
		self.command_microamps_changed.sig.emit(self.microamps)  #this line means 'emit the signal 'command_microamps_changed' with a value of self.microamps'
		commandedvoltage = (self.microamps-4000.0)*270.0/16000.0
		self.voltint = int(commandedvoltage)
		self.voltage_update_slider.sig.emit(self.voltint)
		self.voltage_reupdate_box.sig.emit(commandedvoltage)

	






if __name__ == '__main__':
	app = QApplication(sys.argv)

	w = MainMagControlWindow()
	w.show()





	sys.exit(app.exec_())
