# AUTOGENERATED! DO NOT EDIT! File to edit: 06_sensors.ipynb (unless otherwise specified).

__all__ = ['fields_dict', 'SensorStream']

# Cell
import time
import serial
import numpy as np
import pandas as pd

from pathlib import Path
#import Jetson.GPIO as GPIO
import datetime
import pickle

# Cell

# Define dictionary column name and data type
fields_dict = {'rtc_now': 'datetime',
             'rtc_temp': 'float',
             'air_temp': 'float',
             'air_pressure': 'float',
             'air_humidity': 'float',
             'imu_cal': 'int',
             'imu_temp': 'float',
             'euler_x': 'float',
             'euler_y': 'float',
             'euler_z': 'float',

             'quat0': 'float',
             'quat1': 'float',
             'quat2': 'float',
             'quat3': 'float',

             'mag_x': 'float',
             'mag_y': 'float',
             'mag_z': 'float',
             'gps_now': 'datetime',
             'latitude': 'float',
             'longitude': 'float',
             'altitude': 'float',
             'numSV': 'int',
             'velN': 'float',
             'velE': 'float',
             'gSpeed': 'float',
             'heading': 'float',
             'velAcc': 'float',
             'pDOP': 'float',
             'hAcc': 'float',
             'vAcc': 'float',
             'headAcc': 'float',
             'magDec': 'float',
             'magAcc': 'float'}

# Cell
class SensorStream():

    def __init__(self, baudrate=921_600, port="/dev/ttyTHS0", start_pin=27, save_dir="/xavier_ssd/data/"):

        self.ser = serial.Serial(port=port,
                                baudrate=baudrate,
                                bytesize=serial.EIGHTBITS,
                                parity=serial.PARITY_NONE,
                                stopbits=serial.STOPBITS_ONE,
                                )

        # Initialise serial port and wait
        self.ser.flushInput()

        # Instantiate for storing data
        self.data = []
        self.data_df = None

        self.start_pin = start_pin

        #GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM) # BCM pin-numbering scheme from Raspberry Pi
        GPIO.setup(start_pin, GPIO.IN)
        self.dir = Path(f"{save_dir}{datetime.date.today()}")
        self.dir.mkdir(parents=False, exist_ok=True)
        self.fname = (f"{self.dir}/{datetime.datetime.now()}.pkl")

    def save(self):
        self.fname = (f"{self.dir}/{datetime.datetime.now()}.pkl")
        self.to_df(fields_dict,dropna_subset = ['rtc_now'],save_file=self.fname)
        print(f"Saved {len(self.data)} lines to {self.fname}")
        self.data = []
        print(self.data_df) #print(self.data_df.head(1)); print(self.data_df.tail(1))
        #self.ser.flushInput()


    def run(self):
        print("starting sensor datapacket reads")
        while True:
            try:
                if GPIO.input(self.start_pin) == True:
                    if len(self.data) == 0:
                        print("packets are coming")
                    self.record()

                    if len(self.data) > 2**14: # about 14k
                        self.save()

                else:
                    if len(self.data) > 0:
                        self.save()

                time.sleep(1)

            except KeyboardInterrupt:
                GPIO.cleanup()
                print("Exiting sensor read.")
                break
            except Exception as e:
                print(e)
                print("Attempting to start again!")
                self.ser.flushInput()
                self.data = []



    def record(self,max_timeout=2):

        start_time = time.time()

        # Check if line is ready
        while self.ser.inWaiting() > 0:

            # Read line from serial
            line_data = self.ser.readline()

            # Format data
            line_data = str(line_data).replace("b", "").replace("'", "").split(",")[:-1]

            # Append line to list
            self.data.append(line_data)

            if time.time()-start_time > max_timeout:
                print("timeout")
                self.ser.flushInput()
                break


    def to_df(self, fields_dict, dropna_subset = None, save_file = None):

        # Convert to dataframe and drop the first row of unclean data
        self.data_df = pd.DataFrame(self.data[1:], columns = fields_dict.keys())
        if dropna_subset:
            self.data_df.dropna(subset = dropna_subset, inplace=True)

        # Iterate through each column and update data type
        for field_name in fields_dict.keys():

            # Convert to float
            if fields_dict[field_name] == 'float' or fields_dict[field_name] == 'int':
                self.data_df[field_name] =  pd.to_numeric(self.data_df[field_name], errors='coerce')

            # Convert to datetime
            elif fields_dict[field_name] == 'datetime':
                self.data_df[field_name] =  pd.to_datetime(self.data_df[field_name], errors='coerce')

        if save_file is not None:
            with open(save_file,"wb") as handle:
                pickle.dump(self.data_df,handle,protocol=pickle.HIGHEST_PROTOCOL)

        # Return formatted data as dataframe
        return self.data_df