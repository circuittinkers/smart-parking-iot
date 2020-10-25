import RPi.GPIO as GPIO
from guizero import App, Box, Text, TextBox, PushButton, warn
import argparse
import warnings
import time
import copy
import datetime
import csv
import json
import uuid
import math
import dweepy
import gspread
from oauth2client.service_account import ServiceAccountCredentials

uid = 0
currentRFid = None
RFidFile = 'rfid_db.csv'
RecordFile = 'record_db.csv'
RFidField = ['Id', 'RFid', 'User', 'Status', 'Last_Session_Id']
RecordField = ['Id','Date','Session_Id','RFid','Time_In','Time_Out','Fare']
sensorStatus = []
currentRecord = []
sensorUpdate = True
localUpdate = True

def syncData():
    global sensorUpdate, localUpdate
    # syncing data to cloud
    isSync = False
    # in order to prevent dweet limits, sync only happens if there is new update
    if sensorUpdate:
        appendSensor = {}
        dataSync.value = "Syncing..."
        print("[MAIN/SYNC] Syncing space to freeboard.io [1/2]")
        # deep copy sensorStatus to lastSensor for next sync
        for sensor in sensorStatus:
            appendSensor[str(sensor['SensorId'])] = sensor['Status']
        print("appendSensor = "+str(appendSensor))
        dweepy.dweet_for(conf['DWEET_KEY'],appendSensor)
        sensorUpdate = False
        isSync = True
    else:
        print("[MAIN/SYNC] Skipped sync to freeboard.io [1/2]")
    # check if any new record, if there is append them
    if localUpdate:
        dataSync.value = "Syncing..."
        print("[MAIN/SYNC] Syncing record to google sheet [2/2]")
        if isAuth:
            spreadsheet = client.open('Smart Parking System (Record)')

            with open(RecordFile, 'r') as file_obj:
                content = file_obj.read()
                client.import_csv(spreadsheet.id, data=content)
        else:
            print("[MAIN/SYNC] No authorization to update google sheet. Please check")
        isSync = True
        localUpdate = False
    else:
        print("[MAIN/SYNC] Skipped sync to google sheet [2/2]")
    if isSync:
        dataSync.value = ""

def checkParking():
    global occupancy, sensorStatus, sensorUpdate
    # checking available parking slot
    for sensor in sensorIr:
        if not GPIO.input(sensor):
            for status in sensorStatus:
                if status['SensorId'] == sensor:
                    if status['Status'] == 1:
                        status['Status'] = 0
                        occupancy-=1
                        print("[MAIN/PARKING] Sensor status: "+str(sensorStatus))
                        carLeft.after(3000, updateParking)
                        sensorUpdate = True
            
        else:
            for status in sensorStatus:
                if status['SensorId'] == sensor:
                    if status['Status'] == 0:
                        status['Status'] = 1
                        occupancy+=1
                        print("[MAIN/PARKING] Sensor status: "+str(sensorStatus))
                        carLeft.after(1000, updateParking)
                        sensorUpdate = True
            
def updateParking():
    global occupancy
    carLeft.value = "There are "+str(occupancy)+"/"+str(conf["SPACE_MAX"])+" parking space left."
    
def makeFile(filename, fieldnames):
    with open(filename, 'x', newline='') as newfile:
        prepfile = csv.DictWriter(newfile, fieldnames=fieldnames)
        
        prepfile.writeheader()
        print("[MAIN/MAKE] "+filename+" prepared.")
def createId(tagId):
    global uid, RFidField
    # check if length of the tag is same as in config
    if(tagId!= "" and len(tagId)==conf["RFID_LEN"]):
        updateName = app.question("Info","Owner of this RFid tag?")
        if(updateName != None and updateName != ""):
            with open('rfid_db.csv', 'a', newline='') as newid:
                updatefile = csv.DictWriter(newid, fieldnames=RFidField)
                updatefile.writerow({'Id':str(uid),'RFid':"RF"+str(tagId),'User':updateName, 'Status':'In', 'Last_Session_Id': 'None'})
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
    tagLabel = "RF"+tagId
    if tagId != "" and len(tagId)==conf["RFID_LEN"]:
        RFidRegistered = False
        print("[MAIN/INFO] Retrieved RFID Serial: "+tagId)

        temp = []
        currentRFid = None
        with open(RFidFile) as csvfile:
            reader = csv.DictReader(csvfile)                
            for row in reader:
                temp.append(row)
                # "RF"+str(tagId) to 
                if row["RFid"] == tagLabel:
                    RFidRegistered = True
                    print("[GUI] Welcome " + row["User"])
                    rfidStatus.value = "Welcome " + row["User"]
                    currentRFid = tagLabel
                uid+=1
            
            time.sleep(1)
            if currentRFid != None:
                timeIn = ""
                timeOut = ""
                print("[MAIN/INFO] Updating user status for "+currentRFid)
                with open(RFidFile, 'w', newline='') as statusfile:
                    statusUpdate = csv.DictWriter(statusfile, fieldnames=RFidField)
                    
                    statusUpdate.writeheader()
                    for key in temp:
                        if key['RFid'] == currentRFid:
                            # if status is In, generate new session id (using uuid4)
                            if key['Status'] == 'In':
                                sessionId = str(uuid.uuid4().hex)
                                print("[MAIN/INFO] User checking in...")
                                print("[MAIN/INFO] Updating user with session id: "+sessionId)
                                key['Last_Session_Id'] = sessionId
                                bufferIn = [key['RFid'], sessionId]
                                timeIn = RFidCheckIn(bufferIn)
                                key['Status'] = 'Out'
                                rfidTimeIn.value = "Time in: "+timeIn
                                rfidTimeOut.value = "Time out: None"
                            # else, find the latest session id and estimate the fare
                            elif key['Status'] == 'Out':
                                print("[MAIN/INFO] User checking out...")
                                fare, duration, timeIn, timeOut = RFidCheckOut(key['Last_Session_Id'])
                                if fare != None:                                    
                                    print("[MAIN/INFO] User has spent "+str(duration)+" minutes. The fare is RM"+str(fare))
                                    rfidTimeIn.value = "Time in: "+timeIn
                                    rfidTimeOut.value = "Time out: "+timeOut
                                    rfidFare.value = "Fare: RM"+str(fare)
                                    rfidTQ.value = conf['APP_THANKYOU']
                                    key['Status'] = 'In'
                            rfidStatus.after(5000, clearDisplay)
                        statusUpdate.writerow(key)
        
        if not RFidRegistered:
            print("[MAIN/WARN] RFid tag is not registered")
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
    global localUpdate
    generateRFid = bufferData[0]
    generateId = bufferData[1]
    currentTs = time.localtime()
    currentDate = time.strftime("%d/%m/%Y", currentTs)
    currentTime = time.strftime("%H:%M:%S", currentTs)
    print("[MAIN/IN] Today is: "+currentDate+" / Now is: "+currentTime)
    
    # read the latest local record
    with open(RecordFile) as recordread:
        # getting latest uid (readlines include the header)
        uid = len(recordread.readlines())
    print("[MAIN/IN] Appending latest local record")
    with open(RecordFile, 'a', newline='') as recordfile:
        record = csv.DictWriter(recordfile, fieldnames=RecordField)
        record.writerow({'Id':str(uid),'Date':currentDate,'Session_Id':generateId,'RFid':generateRFid, 'Time_In':currentTime, 'Time_Out': 'None','Fare':'None'})
        localUpdate = True
    return currentDate + " " + currentTime

def RFidCheckOut(sessionId):
    global currentRecord, localUpdate
    lookId = sessionId
    currentTs = time.localtime()
    currentDate = time.strftime("%d/%m/%Y", currentTs)
    currentTime = time.strftime("%H:%M:%S", currentTs)
    
    # read the latest local report
    previousDate = None
    previousTime = None
    isIdFound = False
    currentRecord.clear()
    print("[MAIN/OUT] Fetching latest local record")
    with open(RecordFile) as comparefile:
        compare = csv.DictReader(comparefile)
        for row in compare:
            currentRecord.append(row)
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
            for key in currentRecord:
                if key['Session_Id'] == lookId:
                    print("[MAIN/OUT] Updating local record...")
                    key['Time_Out'] = currentTime
                    key['Fare'] = fare
                recordUpdate.writerow(key)
            localUpdate = True
        return fare, duration,(previousDate+" "+previousTime), (currentDate+" "+currentTime)
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
# (IMPORTANT #1) If you need to add more sensor, please add them to conf.json
# with their gpio pin(s) and update the names here in sensorIr.
# Kindly use the same name for ease
# (IMPORTANT #2) Then, increase the SPACE_MAX in conf.json to increase the max
# number of parking
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
    sensorStatus.append({'SensorId':sensor, 'Status':1})
    GPIO.setup(sensor,GPIO.IN)

print("[MAIN/INFO] IR sensor ready...")
print("[MAIN/INFO] Available sensors: "+str(sensorStatus))

# init and connecting google sheet api
scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
         "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
isAuth = False
try:
    credentials = ServiceAccountCredentials.from_json_keyfile_name('gs_client_secret.json', scope)
    isAuth = True
except:
    print("[MAIN/WARN] Failed to init Google Service Account. Please ensure that gs_client_secret.json is present!")

if isAuth:
    client = gspread.authorize(credentials)

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
dataSync = Text(app, text="")
dataSync.repeat((conf['SYNC_SEC']*1000), syncData)

rfidText.focus()
app.display()

# ----- end of main -----