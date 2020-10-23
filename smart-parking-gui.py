import RPi.GPIO as GPIO
from guizero import App, Box, Text, TextBox, PushButton, warn
import argparse
import warnings
import time
import datetime
import csv
import json
import uuid
import math

uid = 0
currentRFid = None
RFidFile = 'rfid_db.csv'
RecordFile = 'record_db.csv'
RFidField = ['Id', 'RFid', 'User', 'Status', 'Last_Session_Id']
RecordField = ['Id','Date','Session_Id','RFid','Time_In','Time_Out','Fare']
sensorStatus = []

def checkParking():
    global occupancy, sensorStatus
    # checking available parking slot
    for sensor in sensorIr:
        if not GPIO.input(sensor):
            for status in sensorStatus:
                if status['SensorId'] == sensor:
                    if status['Status'] == "Available":
                        status['Status'] = "Occupied"
                        occupancy-=1
                        print("Sensor status: "+str(sensorStatus))
                        carLeft.after(3000, updateParking)
            
        else:
            for status in sensorStatus:
                if status['SensorId'] == sensor:
                    if status['Status'] == "Occupied":
                        status['Status'] = "Available"
                        occupancy+=1
                        print("Sensor status: "+str(sensorStatus))
                        carLeft.after(1000, updateParking)
            
def updateParking():
    global occupancy
    carLeft.value = "There are "+str(occupancy)+"/"+str(conf["SPACE_MAX"])+" parking space left."
    
def makeFile(filename, fieldnames):
    with open(filename, 'x', newline='') as newfile:
        prepfile = csv.DictWriter(newfile, fieldnames=fieldnames)
        
        prepfile.writeheader()
        print("[MAIN] "+filename+" prepared.")
def createId(tagId):
    global uid, RFidField
    if(tagId!= "" and len(tagId)==conf["RFID_LEN"]):
        updateName = app.question("Info","Owner of this RFid tag?")
        if(updateName != None and updateName != ""):
            with open('rfid_db.csv', 'a', newline='') as newid:
                updatefile = csv.DictWriter(newid, fieldnames=RFidField)
                updatefile.writerow({'Id':str(uid),'RFid':str(tagId),'User':updateName, 'Status':'In', 'Last_Session_Id': 'None'})
        print("[MAIN/CREATE] Successfully created Id "+tagId)
        uid = 0
        rfidStatus.value = "Success! Please try again."

        rfidStatus.after(3000, clearDisplay)
    
def clearDisplay():
    global occupancy
    print("[GUI] Clearing display!")
    rfidStatus.value = "---"
    rfidText.value = ""
    rfidTimeIn.value = ""
    rfidTimeOut.value = ""
    rfidFare.value = ""
    rfidTQ.value = ""
    carLeft.value = "There are "+str(occupancy)+"/"+str(conf["SPACE_MAX"])+" parking space left."
    rfidStatus.repeat(1000, checkRFidTag)
    rfidText.focus()
    
def checkRFidTag():
    global uid, currentRFid, occupancy
    # get rfidText value from text box
    tagId = rfidText.value
    if tagId != "" and len(tagId)==conf["RFID_LEN"]:
        RFidRegistered = False
        print("[MAIN] Retrieved RFID Serial: "+tagId)

        temp = []
        currentRFid = None
        with open(RFidFile) as csvfile:
            reader = csv.DictReader(csvfile)                
            for row in reader:
                temp.append(row)
                if row["RFid"] == tagId:
                    RFidRegistered = True
                    print("[GUI] Welcome " + row["User"])
                    rfidStatus.value = "Welcome " + row["User"]
                    currentRFid = tagId
                    # rfidStatus.after(5000, clearDisplay)
                uid+=1
            
            time.sleep(1)
            if currentRFid != None:
                timeIn = ""
                timeOut = ""
                print("[MAIN] Updating user status for "+currentRFid)
                with open(RFidFile, 'w', newline='') as statusfile:
                    statusUpdate = csv.DictWriter(statusfile, fieldnames=RFidField)
                    
                    statusUpdate.writeheader()
                    for key in temp:
                        if key['RFid'] == currentRFid:
                            # if status is In, generate new session id (using uuid4)
                            if key['Status'] == 'In':
                                sessionId = str(uuid.uuid4().hex)
                                print("[MAIN] User checking in...")
                                print("[MAIN] Updating user with session id: "+sessionId)
                                key['Last_Session_Id'] = sessionId
                                bufferIn = [key['RFid'], sessionId]
                                timeIn = RFidCheckIn(bufferIn)
                                key['Status'] = 'Out'
                                rfidTimeIn.value = "Time in: "+timeIn
                                rfidTimeOut.value = "Time out: None"
                                # occupancy is not monitored via checkin/out. it should be from detecting i/o
                                # occupancy-=1
                            # else, find the latest session id and estimate the fare
                            elif key['Status'] == 'Out':
                                print("[MAIN] User checking out...")
                                fare, duration, timeOut = RFidCheckOut(key['Last_Session_Id'])
                                if fare != None:                                    
                                    print("[MAIN] User has spent "+str(duration)+" minutes. The fare is RM"+str(fare))
                                    rfidTimeIn.value = "Time in: "+timeIn
                                    rfidTimeOut.value = "Time out: "+timeOut
                                    rfidFare.value = "Fare: RM"+str(fare)
                                    rfidTQ.value = conf['APP_THANKYOU']
                                    key['Status'] = 'In'
                                    # occupancy+=1
                            rfidStatus.after(5000, clearDisplay)
                        statusUpdate.writerow(key)
        
        if not RFidRegistered:
            print("[MAIN] RFid tag is not registered")
            rfidStatus.value = "RFid tag does not exist."
            # request adding to database
            rfidStatus.cancel(checkRFidTag)
            updateDatabase = False
            updateDatabase = app.yesno("Info","Do you want to update this RFid tag?")
            if updateDatabase:
                createId(tagId)
            else:
                uid = 0
                rfidStatus.after(3000, clearDisplay)
        
        else:
            uid = 0
            rfidStatus.cancel(checkRFidTag)
            
def RFidCheckIn(bufferData):
    generateRFid = bufferData[0]
    generateId = bufferData[1]
    currentTs = time.localtime()
    currentDate = time.strftime("%d/%m/%Y", currentTs)
    currentTime = time.strftime("%H:%M:%S", currentTs)
    print("[MAIN/IN] Today is: "+currentDate)
    print("[MAIN/IN] Now is: "+currentTime)
    
    # read the latest local record
    with open(RecordFile) as recordread:
        # getting latest uid (readlines include the header)
        uid = len(recordread.readlines())
    print("[MAIN/IN] Appending latest local record")
    with open(RecordFile, 'a', newline='') as recordfile:
        record = csv.DictWriter(recordfile, fieldnames=RecordField)
        record.writerow({'Id':str(uid),'Date':currentDate,'Session_Id':generateId,'RFid':generateRFid, 'Time_In':currentTime, 'Time_Out': 'None','Fare':'None'})       
    return currentDate + " " + currentTime

def RFidCheckOut(sessionId):
    lookId = sessionId
    currentTs = time.localtime()
    currentDate = time.strftime("%d/%m/%Y", currentTs)
    currentTime = time.strftime("%H:%M:%S", currentTs)
    
    # read the latest local report
    tempData = []
    previousDate = None
    previousTime = None
    isIdFound = False
    print("[MAIN/OUT] Fetching latest local record")
    with open(RecordFile) as comparefile:
        compare = csv.DictReader(comparefile)
        for row in compare:
            tempData.append(row)
            if row['Session_Id'] == lookId:
                previousDate = row['Date']
                previousTime = row['Time_In']
                isIdFound = True
    if isIdFound:
        duration = getDuration(previousDate, previousTime, currentDate, currentTime)
        fare = getFare(duration)
        # update to local record
        with open(RecordFile,'w',newline='') as updatefile:
            recordUpdate = csv.DictWriter(updatefile, fieldnames=RecordField)
                    
            recordUpdate.writeheader()
            for key in tempData:
                if key['Session_Id'] == lookId:
                    print("[MAIN/OUT] Updating local record...")
                    key['Time_Out'] = currentTime
                    key['Fare'] = fare
                recordUpdate.writerow(key)
        return fare, duration, (currentDate+" "+currentTime)
    return None, None, ""

def getDuration(lastDate, lastTime, nowDate, nowTime):
    # compare date, if not equal, charge maximum fare
    if lastDate == nowDate:
        getLastTime = time.strptime(lastTime, "%H:%M:%S")
        getNowTime = time.strptime(nowTime, "%H:%M:%S")
        
        # convert hour into minutes then calculate duration
        lastMinute = (int(getLastTime.tm_hour) * 60) + int(getLastTime.tm_min)
        nowMinute = (int(getNowTime.tm_hour) * 60) + int(getNowTime.tm_min)
        
        duration = nowMinute - lastMinute
    else:
        print("[MAIN/TIME] Duration is over 24 hour, charging maximum fares")
        duration = 1440 # mins
        
    return duration

def getFare(duration):
    if duration < 60:
        # less than 60
        fare = int(conf['FARE_MIN'])
    elif duration > 60 and duration < 1440:
        # more than 60 but less than a full day
        getHour = math.floor(duration/60)
        fare = getHour * int(conf['FARE_STANDARD'])
    elif duration >= 1440:
        fare = int(conf['FARE_MAX'])
    
    return fare

# ------ main ------

# construct arg parser
ap = argparse.ArgumentParser()
ap.add_argument("-c", "--conf", required=True,
    help="path to JSON configuration file")
args = vars(ap.parse_args())

# filter warning and load config
warnings.filterwarnings("ignore")
conf = json.load(open(args["conf"]))

# init car occupancy value
occupancy = conf["SPACE_MAX"]
sensorIr = [conf['GPIO_IR1'],conf['GPIO_IR2'],conf['GPIO_IR3']]

# init rfid_db and records_db
try:
    isFile = open(RFidFile)
    isFile.close()
except:
    print("[MAIN/WARN] "+RFidFile+" does not exist! Generating...")
    makeFile(RFidFile, RFidField)
    
try:
    isFile = open(RecordFile)
    isFile.close()                                    
except:
    print("[MAIN/WARN] "+RecordFile+" does not exist. Generating...")
    makeFile(RecordFile, RecordField)
    
# init and connecting sensors
GPIO.setmode(GPIO.BCM)
for sensor in sensorIr:
    sensorStatus.append({'SensorId':sensor, 'Status':"Available"})
    GPIO.setup(sensor,GPIO.IN)

print("[MAIN/INFO] IR sensor ready...")
print("Sensors: "+str(sensorStatus))

# app gui setup
app = App(title=conf["APP_TITLE"], width=conf["WINDOW_WIDTH"], height=conf["WINDOW_HEIGHT"], layout="auto", bg="white")
app.text_size = "15"

instructionText = Text(app, text=conf["APP_INSTRUCTION"])
rfidText = TextBox(app)
rfidStatus = Text(app, text="---")
rfidTimeIn = Text(app, text="")
rfidTimeOut = Text(app, text="")
rfidFare = Text(app, text="")
rfidTQ = Text(app, text="")

rfidStatus.text_size = "13"
rfidTimeIn.text_size = "13"
rfidTimeOut.text_size = "13"
rfidFare.text_size = "13"
rfidTQ.text_size = "15"
rfidStatus.repeat(1000, checkRFidTag)

designBy = Text(app, text=conf["APP_CREDIT"],align="bottom")
carLeft = Text(app, text="There are "+str(occupancy)+"/"+str(conf["SPACE_MAX"])+" parking space left.", align="bottom")
carLeft.repeat(1000, checkParking)

rfidText.focus()
app.display()

# ----- end of main -----