

/*
Kinetics magnet supply network interface with current reading  version 0.5
by Axl, latest edit 9/18/12


sodium:/data/tech_info/arduino/mag_control_ethernet_v_0_5

This version, machine command version without serial debugging stream 
and with SPI clock divider set higher to try to speed up the connection
speedup works on bench test with bare DAC but will have to test SPI
clock divider change with optoisolated unit!

Current calibration from 9/12/12 sodium:/data/tech_info/calibrations/magcal_091212/ramp_index_Bdata.mat 

v.Ab2A = Ab2A 
v.Bb2A = Bb2A

Measured amps = Ab2A*bits+Bb2A

Arduino accepts an integer in microamps and
commands a signal from a DAC8551 SPI digital 
to analog converter calibrated to put 4-20mA 
into the Kinetics supply. In voltage control 
mode this changes the supply voltage from 0-270V.

the python code, latest version: /data/bin/3mcontrol/magsupply_0_5.py
gives a GUI frontend to interface with this system 
to set supply voltage and log magnet current. 

*/


#include <stdio.h>
#include <Messenger.h> 
#include <SPI.h>
#include <Ethernet.h>
#include <TimerOne.h>

int statled = 9; // status LED: pin 9, connected to green wire
int CS_DAC =8;   // chip select pin 8 connected to DAC8551 "not SYNC" pin 5 with yellow wire, pin 7 for arduino with broken pin
int ETHPIN =10;
int SDPIN = 4; 
//MOSI pin (11) connected to DAC8551 D_{IN}, pin 7 with red wire
//CLK pin (13) connected to DAC8551 SCLK, pin 6 with orange wire
int jj = 0; //index for loop
int IB = 0b11010100; //initialization byte, six junk bits (110101 easy to scope) and 00 for normal op of DAC
int HB = 0b00000000; // high byte of command data
int LB = 0b00000000; // low byte of command data

int welcome = 1; // initialize to "true" to go through welcome screen once
long commandua = 4000;  // variable to hold the commanded voltage read from the client
long commanduaold = 4000; //when command current is successfully set, this is set too
float commanduaf = 0.0; //float version of commandua
float commandbf = 0.0;  // float version of commandbits
long commandbits = 13065;
float A = (65300.0-13065.0)/(20000.0-4000.0); //(maxbits-minbits)/(max I - min I) - command bits to voltage slope
float B = 65300.0-20000.0*A;                  // maxbits - (max I) * slope - 4mA intercept
float Veq = 0.0;
char sbuf[32];

//network parameters
//byte mac[] = { 0x90, 0xA2, 0xDA, 0x0D, 0x8B, 0xBC }; //shield "A"
byte mac[] = { 0x90, 0xA2, 0xDA, 0x0D, 0x30, 0x79 }; //shield "B"
byte serverIP[] = { 192,168,1,177 };
int serverPort=8888;

Messenger message = Messenger();
Server server = Server(serverPort);


//variables for current measurement
long Iarray[16]; //16 samples low pass filter to give better bit depth (12 bit equiv if noise is sufficient)
volatile long newread = 0; //newread will be updated by the interrupt at regular intervals
volatile int Iindex = 0; // index for elements of Iarray
volatile long Isum = 0;
float Iavg = 0;
float Ab2A = -0.866600606132161;
float Bb2A = 698.4821366001779;


void setup()
           {
             pinMode(statled, OUTPUT); // set status LED as output
             pinMode(CS_DAC,OUTPUT);   // set DAC chip select pin as output
             pinMode(ETHPIN,OUTPUT);   // set ethernet chip select pin as output (probably not necessary)
             pinMode(SDPIN,OUTPUT);    //this is the SD card chip select, set high to keep it from interfering
             delay(50);
             digitalWrite(statled,HIGH);
             delay(200);
             digitalWrite(CS_DAC,HIGH);      
             digitalWrite(ETHPIN,HIGH);
             digitalWrite(SDPIN,HIGH);
             digitalWrite(statled,LOW);
             for (int jjj = 0; jjj < 16; jjj++)
                 {
                    Iarray[jjj] = 0;   
                 }
      
             Timer1.initialize(3125); //3125 microseconds = 16 samples average to make outputs at 20Hz 
             Timer1.attachInterrupt(updateI);
             delay(50);
             SPI.setClockDivider(SPI_CLOCK_DIV4);  //try this to speed up ethernet??
             SPI.begin();
             delay(100);
             
             Ethernet.begin(mac,serverIP);
             delay(100);
             server.begin();
             delay(100);
            
             HB = highByte(commandbits);
             LB = lowByte(commandbits);
             writedac(IB,HB,LB,CS_DAC); //initialize at 0mA - goes to 4mA when connected           
           }

void loop()
{
  Client client = server.available();
  
  if (client.connected() && welcome > 0)
     {
       delay(100);
       HB = highByte(commandbits);
       LB = lowByte(commandbits);
       writedac(IB,HB,LB,CS_DAC);
       client.println("$ready$");
       welcome = 0;

     }
  
  if (client)
     {
        String cmdStr = "";  
        while (client.available()>0)
            {
             char c = client.read();
             cmdStr+=c; //append character to command string
             
             if (c=='\n')
                { 

                  if (!(cmdStr.indexOf("set:")==0 || cmdStr.indexOf("read:")==0 || cmdStr.indexOf("stop:")==0) )
                     {
                       client.println("$err:syntax$");
                       client.flush();
                       cmdStr = "";
                     }
                  if (cmdStr.indexOf("set:")==0)
                     { 
                       String value = cmdStr;
                       value = value.replace("set:", "");  //NOTE: in Arduino 1.0.1 there is no need to reassign, just value.replace() is ok
                       commandua = StringToLong(value);  
                       if (commandua < 4000 || commandua > 20000)
                          {
                            client.println("$err:range$");
                            commandua = commanduaold;
                          }          
                       else 
                           {
                             commanduaold = commandua;
                             commanduaf = (float) commandua;
                             commandbf = A*commanduaf+B; //corrected measured offset
                             commandbits = (long) floor(commandbf);
                             Veq = (commanduaf-4000)*270.0/(20000.0-4000.0); //calculate supply voltage
                             HB = highByte(commandbits);
                             LB = lowByte(commandbits);
                             client.println("$ok:set$");
                             writedac(IB,HB,LB,CS_DAC);
                           
                           }
                     } 
                   
                   if (cmdStr.indexOf("read:")==0)
                     {
                       client.print("$ok:data$ ");
                       client.print(commandua);
                       client.print(" ");
                       Iavg = Ab2A*Isum/16.0+Bb2A;
                       client.println(dtostrf(Iavg,8,4,sbuf));
                     }
                     
                   if (cmdStr.indexOf("stop:")==0)
                     {
                       client.println("$ok:stop$");
                       commandbits=13065; //shut off voltage
                       HB = highByte(commandbits);
                       LB = lowByte(commandbits);
                       writedac(IB,HB,LB,CS_DAC);
                       client.stop();
                       welcome = 1;
                       commandua=4000;
                       
                     }
                     
                  cmdStr=""; //reset the command string
                  client.flush();   
                 }
             
           }         
        }
}//end of loop()


//==========FUNCTION DEFS ====================

int writedac(int hibyte, int medbyte, int lobyte,int chip_select) 
            {  //can't leave CS low for ethernet
              
              SPI.setDataMode(SPI_MODE1); //for DAC
              SPI.setClockDivider(SPI_CLOCK_DIV128); //slow down for optoisolator
              delayMicroseconds(4);
              digitalWrite(chip_select,HIGH);
              delayMicroseconds(4);
              digitalWrite(chip_select,LOW);
              delayMicroseconds(4);
              SPI.transfer(hibyte);
              SPI.transfer(medbyte);
              SPI.transfer(lobyte);
              delayMicroseconds(4);
              digitalWrite(chip_select,HIGH);
              delayMicroseconds(6);
              SPI.setDataMode(SPI_MODE0); //for Ethernet Shield
              SPI.setClockDivider(SPI_CLOCK_DIV4); // speed back up for ethernet
              
            }

 void updateI() //keep updating array, every 16 samples take an average
             { 
               Iarray[Iindex] = analogRead(A0);
               Iindex = (Iindex+1)%16;
               if (Iindex==0){
               Isum = 0;
               for (int nn=0; nn<16; nn++){
               Isum = Isum+Iarray[nn]; 
               }
              }
             }
   
int StringToLong(String value)
                {
                  char buf[value.length()];
                  value.toCharArray(buf,value.length());
                  return atoi(buf);
                }

     
