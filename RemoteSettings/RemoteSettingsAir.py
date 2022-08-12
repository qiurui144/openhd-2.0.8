
import json
import configparser
import binascii
from itertools import chain
import os
import sys
import fileinput
import socket
import re
import threading

import subprocess
from subprocess import call
from tempfile import mkstemp
from shutil import move
from os import fdopen, remove
from time import sleep
import RPi.GPIO as GPIO


WFBCSettingsFile = "/boot/openhd-settings-1.txt"
OSDSettingsFile = "/boot/osdconfig.txt"
JoystickSettingsFile = "/boot/joyconfig.txt"
IsTerminateRemoteSettingsPath = "/tmp/IsTerminateRemoteSettingsPath.txt"
TerminateTimeOut = 0
IsPhoneConnected = 0

IPAndroidClient = ""

ConfigResp = bytearray(b'ConfigResp')
RequestAllSettings = bytearray(b'RequestAllSettings')
RequestChangeSettings = bytearray(b'RequestChangeSettings')
RequestChangeOSD = bytearray(b'RequestChangeOSD')
RequestChangeJoystick = bytearray(b'RequestChangeJoystick')
RequestChangeTxPower = bytearray(b'RequestChangeTxPower')
RequestPhoneConnected = bytearray(b'PhoneConnected')


GPIO.setmode(GPIO.BCM)
GPIO.setup(20, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(21, GPIO.IN, pull_up_down=GPIO.PUD_UP)

input_state0 = GPIO.input(20)
input_state1 = GPIO.input(21)

if (input_state0 == False) and (input_state1 == False):
    WFBCSettingsFile = "/boot/openhd-settings-4.txt"

if (input_state0 == False) and (input_state1 == True):
    WFBCSettingsFile = "/boot/openhd-settings-3.txt"

if (input_state0 == True) and (input_state1 == False):
    WFBCSettingsFile = "/boot/openhd-settings-2.txt"

if (input_state0 == True) and (input_state1 == True):
    WFBCSettingsFile = "/boot/openhd-settings-1.txt"


wbc_settings_blacklist = [""]
def replace_OSD_config(LookFor, NewLine):
    os.system('mount -o remount,rw /boot')
#example: #define COPTER true
#use: replace_OSD_config(COPTER, COPTER true)
    ret = -1
    print("replace_OSD_config in: Look for: " + LookFor + " NewLine: " + NewLine)
    print("File Name: " + OSDSettingsFile)
    for line in fileinput.input([OSDSettingsFile], inplace=True):
        if line.strip().startswith('#define ' + LookFor):
            line = '#define ' + NewLine + '\n'
            ret = 1
        sys.stdout.write(line)

    os.system('mount -o remount,ro /boot')
    return ret


def replace_Joystick_config(LookFor, NewLine):
    os.system('mount -o remount,rw /boot')
#example: #define UPDATE_NTH_TIME 10
#use: replace_OSD_config(UPDATE_NTH_TIME, UPDATE_NTH_TIME 3)
    ret = -1
    print("replace_OSD_config in: Look for: " + LookFor + "NewLine: " + NewLine)
    for line in fileinput.input([JoystickSettingsFile], inplace=True):
        if line.strip().startswith('#define ' + LookFor):
            line = '#define ' + NewLine + '\n'
            ret = 1
        sys.stdout.write(line)

    os.system('mount -o remount,ro /boot')
    return ret


def replace_TxPower_config(Param, Value):

    if 'txpowerA' in Param:
        subprocess.Popen(["/usr/local/bin/txpower_atheros", Value])

    if 'txpowerR' in Param:
        subprocess.Popen(["/usr/local/bin/txpower_ralink", Value])

    return 1


def replace_WFBC_config(file_path, LookFor, NewLine):
    #Create temp file
    os.system('mount -o remount,rw /boot')
    NewLine += "\n"
    fh, abs_path = mkstemp()
    with fdopen(fh,'w') as new_file:
        with open(file_path) as old_file:
            for line in old_file:
                if  line.startswith( LookFor ) == True:
                    new_file.write(NewLine)
                else:
                    new_file.write(line)
    #Remove original file
    remove(file_path)
    #Move new file
    move(abs_path, file_path)
    os.system('mount -o remount,ro /boot')


def read_osd_settings(response_header):
    d = {}

    with open (OSDSettingsFile, 'rt') as file:  # Open file lorem.txt for reading of text data.
        for line in file: # Store each line in a string variable "line"
            if 'define COPTER true' in line:
                d['Copter'] = "true"
                print("copter = true")
            if 'define COPTER false' in line:
                d['Copter'] = "false"
                print("Copter = false")

            if 'define IMPERIAL true' in line:
                d['Imperial'] = "true"
                print("Imperial = true")
            if 'define IMPERIAL false' in line:
                d['Imperial'] = "false"
                print("Imperial = false")

    response_header['settings'].update(d)
    return response_header

def read_txpower_settings(response_header):
    txp = {}

    processA = subprocess.Popen(["sed", "s/.*txpower=\\([0-9]*\\).*/\\1/", "/etc/modprobe.d/ath9k_hw.conf"], stdout=subprocess.PIPE)
    ret_txpowerA = processA.communicate()[0]
    txpowerA = re.sub("[^0-9]+", "", ret_txpowerA.decode('utf-8'))
    processR = subprocess.Popen(["sed", "s/.*txpower=\\([0-9]*\\).*/\\1/", "/etc/modprobe.d/rt2800usb.conf"], stdout=subprocess.PIPE)
    ret_txpowerR = processR.communicate()[0]
    txpowerR = re.sub("[^0-9]+", "", ret_txpowerR.decode('utf-8'))

    txp['txpowerR'] = txpowerR
    txp['txpowerA'] = txpowerA

    print("txpowerR: ")
    print(txp['txpowerR'])
    print("txpowerA: ")
    print(txp['txpowerA'])

    response_header['settings'].update(txp)
    return response_header

def read_joystick_settings(response_header):
    d = {}

    with open (JoystickSettingsFile, 'rt') as file:  # Open file lorem.txt for reading of text data.
        for line in file: # Store each line in a string variable "line"
            if '#define UPDATE_NTH_TIME' in line:
                splitResult = line.split("UPDATE_NTH_TIME")
                filter = re.sub("\D", "", splitResult[1])
                d['UPDATE_NTH_TIME'] = filter
                print("Result: ")
                print(d['UPDATE_NTH_TIME'])

    response_header['settings'].update(d)
    return response_header


def read_wbc_settings(response_header):

    virtual_section = 'root'
    settings = {}
    config = configparser.ConfigParser()
    config.optionxform = str
    with open(WFBCSettingsFile, 'r') as lines:
        lines = chain(('[' + virtual_section + ']',), lines)
        config.read_file(lines)

    
    for key in config[virtual_section]:
        if key not in wbc_settings_blacklist:
            settings[key] = config.get(virtual_section, key)

    response_header['settings'] = settings
    return response_header

def SendData(IP, MessageBuf): 
    global IPAndroidClient
    UDP_PORT = 9292
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
    sock.sendto( MessageBuf, (IPAndroidClient, UDP_PORT))

def SendDataToWFBC(MessageBuf):
    global IPAndroidClient
    UDP_PORT = 9292
    sockToAir = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
    sockToAir.sendto( bytes(MessageBuf,'utf-8'), ('127.0.0.1', UDP_PORT))

complete_response = {}
read_wbc_settings(complete_response)
read_txpower_settings(complete_response)
read_osd_settings(complete_response)
read_joystick_settings(complete_response)

def SendAllSettingToPhone():
    for te in complete_response['settings']:
        
        SendBuff = bytearray()
	    #Header
        SendBuff[0:0] = ConfigResp

    
	    #Form Payload. Header from 0 to 19 byte, 20+ data
        ValuePayload = te.encode('utf-8')
        SendBuff.extend(te.encode('utf-8') )
        SendBuff.extend(str.encode("=",'utf-8') )
    
        data = complete_response['settings'][te]
        ValueDataPayload = data.encode('utf-8')
        SendBuff.extend(ValueDataPayload)

        global IPAndroidClient
        SendData(IPAndroidClient,SendBuff)
        print("v :", SendBuff)
        SendBuff.clear()

def ConfirmSave(VarName):
    SendBuffSave = bytearray()
    SendBuffSave[0:0] = ConfigResp
   
    PayLoad = VarName.encode('utf-8')
    SendBuffSave.extend(PayLoad)
    SendBuffSave.extend(str.encode("=SavedAir",'utf-8') )

    global IPAndroidClient
    SendData(IPAndroidClient,SendBuffSave)
    print("confirm save Air to Ground to Phone: ", SendBuffSave)
    SendBuffSave.clear()

def SendACKToGround(VarName):
    print("Sending ACK to Ground RPi...  ")
    print(VarName)
    SendDataToWFBC(VarName)


def NoPhoneDetected():
    for i in range(TerminateTimeOut):
        sleep(1);
    if IsPhoneConnected == 0:
        print("NoPhoneDetected")
        for x in range(5):
            SendDataToWFBC("RemoteSettingsTerminated")
            sleep(0.25)
        hFile = open(IsTerminateRemoteSettingsPath,"w")
        hFile.write("1")
        hFile.close()
        os.system('/usr/local/share/RemoteSettings/TerminateRemoteSettingsAir.sh')
        sys.exit(1)

def PhoneConnected():
    global IsPhoneConnected
    IsPhoneConnected = 1

UDP_IP = ""
UDP_PORT = 9393
sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))


if len(sys.argv) >= 2:
    InParam = sys.argv[1]
    if InParam != "0":
        if InParam.isnumeric() == 1:
            print("Terminate function enabled, timeout = ", InParam)
            try:
                TerminateTimeOut = int(InParam)
                tHandler = threading.Thread(target=NoPhoneDetected)
                tHandler.start()
            except ValueError:
                print("TimeOut to int except")
else:
    print("Terminate function disabled")

while True:
    data, addr = sock.recvfrom(1024) # buffer size is 1024 bytes
  
    IPAndroidClient = addr[0]
    print("ip: ", IPAndroidClient)    
    if data == RequestAllSettings:
        SendAllSettingToPhone()
    if data == RequestPhoneConnected:
        PhoneConnected()
    if RequestChangeSettings in data:
        DataStr = data.decode('utf-8')
        parts = DataStr.split(RequestChangeSettings.decode('utf-8') )
        VariableNamAndData = parts[1]
        VariableNamAndDataArr = VariableNamAndData.split("=")
        VariableNam = VariableNamAndDataArr[0]
        VariableNameReport = VariableNamAndDataArr[0]
        Data = VariableNamAndDataArr[1]
        VariableNam = VariableNam + "="
#add sync conde
#        SendACKToGround(DataStr)
#if no error, replace local config file
        replace_WFBC_config(WFBCSettingsFile,VariableNam,VariableNamAndData)
        try:
            if VariableNamAndData.startswith('TxPowerAir=') == True:
                splitResult = VariableNamAndData.split("=")
                filter = re.sub("\D", "", splitResult[1])
                subprocess.check_call(['/usr/local/bin/txpower_atheros',  filter ])
        except Exception as e:
            print("TxPowerAir except: " + str(e) )

        ConfirmSave(VariableNameReport)
        complete_response = {}
        read_wbc_settings(complete_response)
        read_txpower_settings(complete_response)
        read_osd_settings(complete_response)
        read_joystick_settings(complete_response)

#change OSD settings
    if RequestChangeOSD in data:
        DataStr = data.decode('utf-8')
        parts = DataStr.split(RequestChangeOSD.decode('utf-8') )
        VariableNamAndData = parts[1]
        print("VariableNamAndData: " + VariableNamAndData)
        VariableNamAndDataArr = VariableNamAndData.split("=")
        VariableNam = VariableNamAndDataArr[0]
        VariableNameReport = VariableNamAndDataArr[0]
        Data = VariableNamAndDataArr[1]
        ret = replace_OSD_config(VariableNam.upper(), VariableNam.upper() + " " + Data)
        if ret == 1:
            ConfirmSave(VariableNameReport)
        #reload values from disk to memory
        complete_response = {}
        read_wbc_settings(complete_response)
        read_txpower_settings(complete_response)
        read_osd_settings(complete_response)
        read_joystick_settings(complete_response)

#change Joystick settings
    if RequestChangeJoystick in data:
        DataStr = data.decode('utf-8')
        parts = DataStr.split(RequestChangeJoystick.decode('utf-8') )
        VariableNamAndData = parts[1]
        print("VariableNamAndData: " + VariableNamAndData)
        VariableNamAndDataArr = VariableNamAndData.split("=")
        VariableNam = VariableNamAndDataArr[0]
        VariableNameReport = VariableNamAndDataArr[0]
        Data = VariableNamAndDataArr[1]
        ret = replace_Joystick_config(VariableNam.upper(), VariableNam.upper() + " " + Data)
        if ret == 1:
            ConfirmSave(VariableNameReport)
        #reload values from disk to memory
        complete_response = {}
        read_wbc_settings(complete_response)
        read_txpower_settings(complete_response)
        read_osd_settings(complete_response)
        read_joystick_settings(complete_response)

#change TX Power settings
    if RequestChangeTxPower in data:
        DataStr = data.decode('utf-8')
        parts = DataStr.split(RequestChangeTxPower.decode('utf-8') )
        VariableNamAndData = parts[1]
        print("VariableNamAndData: " + VariableNamAndData)
        VariableNamAndDataArr = VariableNamAndData.split("=")
        VariableNam = VariableNamAndDataArr[0]
        VariableNameReport = VariableNamAndDataArr[0]
        Data = VariableNamAndDataArr[1]
        #add sync conde
        ret = replace_TxPower_config(VariableNam, Data)
        if ret == 1:
            ConfirmSave(VariableNameReport)
        #reload values from disk to memory
        complete_response = {}
        read_wbc_settings(complete_response)
        read_txpower_settings(complete_response)
        read_osd_settings(complete_response)
        read_joystick_settings(complete_response)


    print("received message:", data)

sys.exit()
#OLD
