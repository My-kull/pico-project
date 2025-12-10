# Kubios HRV - Cloud analysis viewer

import machine
import utime
import network
import ujson
try:
    import ssd1306
except:
    ssd1306 = None
try:
    from umqtt.simple import MQTTClient
except:
    MQTTClient = None

# ----------------- CONFIG -----------------
I2C_SCL = 15
I2C_SDA = 14
OLED_ENABLED = ssd1306 is not None
OLED_WIDTH = 128
OLED_HEIGHT = 64
EXIT_PIN = 7
NAV_PIN = 10

# MQTT/Kubios config
SSID = "KME759_Group_10"
PASSWORD = "C4lories"
BROKER_IP = "192.168.10.253"
BROKER_PORT = 21883
DEVICE_MAC = "28CDC1057762" # Remember to change to individual PICO Mac Address!

# Device/Patient config
DEVICE_NAME = "Pico HRV Monitor"
PATIENT_NAME = "HRV User"
PATIENT_ID = 1  # Default patient ID - update as needed



# ----------------- HARDWARE -----------------
if OLED_ENABLED:
    try:
        i2c = machine.I2C(1, scl=machine.Pin(I2C_SCL),
                          sda=machine.Pin(I2C_SDA), freq=400000)
        oled = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c)
    except:
        oled = None
        print("OLED initialization failed")
else:
    oled = None

exit_btn = machine.Pin(EXIT_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
nav_btn = machine.Pin(NAV_PIN, machine.Pin.IN, machine.Pin.PULL_UP)



# ----------------- GLOBALS -----------------
mqtt_client = None
wifi_connected = False
last_analysis = None
display_page = 0
max_pages = 1
connection_attempted = False
device_registered = False
patient_registered = False



def reset_connections():
    """Reset all connection states for clean startup"""
    global mqtt_client, wifi_connected, last_analysis, connection_attempted
    global device_registered, patient_registered
    
    # Disconnect MQTT if connected
    if mqtt_client:
        try:
            mqtt_client.disconnect()
        except:
            pass
        mqtt_client = None
    
    # Reset WiFi
    try:
        wlan = network.WLAN(network.STA_IF)
        if wlan.isconnected():
            wlan.disconnect()
        wlan.active(False)
        utime.sleep_ms(100)
        wlan.active(True)
    except:
        pass
    
    wifi_connected = False
    last_analysis = None
    connection_attempted = False
    device_registered = False
    patient_registered = False
    print("Connections reset")

# ----------------- HRV DATA ACCESS -----------------
def get_hrv_data():
    """Get clean RR intervals from HRVMonitor.py (excluding initial setup beats)"""
    try:
        import HRVMonitor
        # Use the proper function to get clean RR intervals
        rr_data = HRVMonitor.get_rr_intervals()
        status = HRVMonitor.get_hrv_status()
        
        if rr_data and len(rr_data) >= 10:
            print("Retrieved clean HRV data: %d clean beats (total: %d, ready: %s)" % 
                  (status["clean_beats"], status["total_beats"], status["ready_for_kubios"]))
            return rr_data
        else:
            print("No sufficient clean HRV data available (%d clean beats, need 10+)" % status["clean_beats"])
            return None
    except ImportError:
        print("HRVMonitor.py not found - run HRVMonitor first")
        return None
    except Exception as e:
        print("Error accessing HRV data:", e)
        return None

# ----------------- REGISTRATION FUNCTIONS -----------------
def register_device():
    """Register device with Kubios database (one-time per session)"""
    global mqtt_client
    
    if mqtt_client is None:
        return False
    
    try:
        payload = (
            "{"
            '"mac": "' + DEVICE_MAC + '",'
            '"device_name": "' + DEVICE_NAME + '"'
            "}"
        )
        
        print("Registering device (one-time):", payload)
        mqtt_client.publish(b"database/devices/add", payload)
        print("Device registration sent")
        return True
        
    except Exception as e:
        print("Device registration failed:", e)
        return False

def register_patient():
    """Register patient with Kubios database (one-time per session)"""
    global mqtt_client
    
    if mqtt_client is None:
        return False
    
    try:
        payload = (
            "{"
            '"mac": "' + DEVICE_MAC + '",'
            '"patient_name": "' + PATIENT_NAME + '"'
            "}"
        )
        
        print("Registering patient (one-time):", payload)
        mqtt_client.publish(b"database/patients/add", payload)
        print("Patient registration sent")
        return True
        
    except Exception as e:
        print("Patient registration failed:", e)
        return False

def ensure_registrations():
    """Ensure device and patient are registered before sending HRV data"""
    global device_registered, patient_registered
    
    # Only register if not already done in this session
    if not device_registered:
        if oled:
            show_text_on_oled([
                "REGISTERING",
                "DEVICE...",
                "",
                "Please wait"
            ])
        if register_device():
            device_registered = True
            print("Device registration completed for this session")
        else:
            return False
        utime.sleep_ms(500)  # Brief pause
    else:
        print("Device already registered this session")
    
    if not patient_registered:
        if oled:
            show_text_on_oled([
                "REGISTERING", 
                "PATIENT...",
                "",
                "Please wait"
            ])
        if register_patient():
            patient_registered = True
            print("Patient registration completed for this session")
        else:
            return False
        utime.sleep_ms(500)  # Brief pause
    else:
        print("Patient already registered this session")
    
    return True

def get_real_timestamp():
    """Get real Unix timestamp by syncing with network time"""
    try:
        import ntptime
        # Sync with NTP server to get real time
        print("Syncing time with NTP server...")
        ntptime.settime()
        # After ntptime.settime(), utime.time() returns Unix timestamp directly
        timestamp = utime.time()
        
        # Show human-readable time
        try:
            time_tuple = utime.localtime(timestamp)
            time_str = "%04d-%02d-%02d %02d:%02d:%02d UTC" % (
                time_tuple[0], time_tuple[1], time_tuple[2], 
                time_tuple[3], time_tuple[4], time_tuple[5]
            )
            print("Time synced successfully: %s" % time_str)
        except:
            print("Time synced, timestamp:", timestamp)
        
        return timestamp
    except Exception as e:
        print("NTP sync failed, using approximate time:", e)
        # Fallback: use approximate current time (December 4, 2025)
        # Current Unix timestamp for Dec 4, 2025 8:35 UTC is approximately 1764835350
        base_time = 1764835350  # Dec 4, 2025 8:35 UTC 
        device_uptime_offset = utime.ticks_ms() // 1000  # Convert ms to seconds
        approximate_time = base_time + device_uptime_offset
        
        try:
            time_tuple = utime.localtime(approximate_time)
            time_str = "%04d-%02d-%02d %02d:%02d:%02d (approx)" % (
                time_tuple[0], time_tuple[1], time_tuple[2], 
                time_tuple[3], time_tuple[4], time_tuple[5]
            )
            print("Using approximate time: %s" % time_str)
        except:
            print("Using approximate timestamp:", approximate_time)
        
        return approximate_time

def add_record_to_database(analysis_data):
    """Add HRV analysis record to Kubios database"""
    global mqtt_client
    
    if mqtt_client is None or analysis_data is None:
        return False
    
    try:
        # Get real current timestamp
        timestamp = get_real_timestamp()
        
        # Extract data from Kubios analysis
        mean_hr = analysis_data.get('mean_hr_bpm', 0)
        mean_ppi = analysis_data.get('mean_rr_ms', 0)  # PPI is same as RR interval
        rmssd = analysis_data.get('rmssd_ms', 0)
        sdnn = analysis_data.get('sdnn_ms', 0)
        sns = analysis_data.get('sns_index', 0)
        pns = analysis_data.get('pns_index', 0)
        
        payload = (
            "{"
            '"mac": "' + DEVICE_MAC + '",'
            '"timestamp": ' + str(timestamp) + ','
            '"mean_hr": ' + str(mean_hr) + ','
            '"mean_ppi": ' + str(mean_ppi) + ','
            '"rmssd": ' + str(rmssd) + ','
            '"sdnn": ' + str(sdnn) + ','
            '"sns": ' + str(sns) + ','
            '"pns": ' + str(pns) + ','
            '"patient_id": ' + str(PATIENT_ID) +
            "}"
        )
        
        # Show human-readable time for verification
        try:
            time_tuple = utime.localtime(timestamp)
            time_str = "%04d-%02d-%02d %02d:%02d:%02d" % (
                time_tuple[0], time_tuple[1], time_tuple[2], 
                time_tuple[3], time_tuple[4], time_tuple[5]
            )
            print("Record timestamp: %s (%d)" % (time_str, timestamp))
        except:
            print("Record timestamp: %d" % timestamp)
        
        print("Adding record to database:", payload[:100] + "..." if len(payload) > 100 else payload)
        mqtt_client.publish(b"database/records/add", payload)
        print("Record added to database")
        return True
        
    except Exception as e:
        print("Record database add failed:", e)
        return False

# ----------------- DISPLAY -----------------
def show_text_on_oled(lines):
    if oled is None:
        return
    oled.fill(0)
    y = 0
    for line in lines:
        oled.text(str(line), 0, y)
        y += 10
        if y > OLED_HEIGHT-10:
            break
    oled.show()

def display_analysis_page(analysis, page):
    if oled is None or analysis is None:
        return
    
    try:
        if isinstance(analysis, str):
            data = ujson.loads(analysis)
        else:
            data = analysis
        
        # Single page with key metrics
        readiness = data.get('readiness', 'N/A')
        mean_hr = data.get('mean_hr_bpm', 'N/A')
        stress_index = data.get('stress_index', 'N/A')
        phys_age = data.get('physiological_age', 'N/A')
        
        show_text_on_oled([
            "KUBIOS ANALYSIS",
            "Score: %.1f" % readiness if isinstance(readiness, (int, float)) else "Score: %s" % readiness,
            "HR: %.1f bpm" % mean_hr if isinstance(mean_hr, (int, float)) else "HR: %s" % mean_hr,
            "Stress: %.1f" % stress_index if isinstance(stress_index, (int, float)) else "Stress: %s" % stress_index,
            "Age: %d years" % phys_age if isinstance(phys_age, (int, float)) else "Age: %s" % phys_age,
            "SAVED TO DB & HISTORY"
        ])
    
    except Exception as e:
        show_text_on_oled([
            "DISPLAY ERROR",
            str(e)[:15],
            "",
            "Check data format"
        ])

# ----------------- MQTT FUNCTIONS -----------------
def connect_wifi():
    global wifi_connected, exit_btn
    if MQTTClient is None:
        return None
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    # Force disconnect and reconnect for clean connection
    if wlan.isconnected():
        wlan.disconnect()
        utime.sleep_ms(500)
    
    wlan.connect(SSID, PASSWORD)
    
    # Connection attempt with exit button check (increased timeout)
    attempts = 200  # 20 seconds
    while not wlan.isconnected() and attempts > 0:
        # Check exit button during connection
        if not exit_btn.value():
            utime.sleep_ms(50)
            if not exit_btn.value():
                print("Exit pressed during WiFi connection")
                return "EXIT_REQUESTED"
        
        utime.sleep_ms(100)
        attempts -= 1
    
    if wlan.isconnected():
        wifi_connected = True
        print("WiFi connected:", wlan.ifconfig()[0])
        return wlan
    else:
        print("WiFi connection failed")
        return None

def connect_mqtt():
    global mqtt_client, exit_btn
    if not wifi_connected or MQTTClient is None:
        return None
    
    # Check exit button before MQTT connection
    if not exit_btn.value():
        utime.sleep_ms(50)
        if not exit_btn.value():
            print("Exit pressed during MQTT connection")
            return "EXIT_REQUESTED"
    
    try:
        client = MQTTClient(client_id=b"kubios_hrv", server=BROKER_IP, port=BROKER_PORT)
        # Ensure callback is set before any operations
        client.set_callback(on_message_received)
        client.connect(clean_session=True)
        client.subscribe(b"kubios/response")
        print("MQTT connected")
        return client
    except Exception as e:
        print("MQTT failed:", e)
        return None

def on_message_received(topic, msg):
    global last_analysis, display_page
    try:
        print("Kubios response received")
        response = ujson.loads(msg.decode())
        
        # Check if response has the expected structure
        if "data" in response and "analysis" in response["data"]:
            last_analysis = response["data"]["analysis"]
            display_page = 0
            
            # Save to database and local history
            if oled:
                show_text_on_oled([
                    "SAVING...",
                    "",
                    "Database & History",
                    "Please wait"
                ])
            
            # Save to database
            db_success = add_record_to_database(last_analysis)
            
            # Save to local history
            history_success = False
            try:
                import HRVHistory
                history_success = HRVHistory.add_analysis_to_history(last_analysis)
            except Exception as e:
                print("History save failed:", e)
            
            # Show result
            if db_success and history_success:
                if oled:
                    show_text_on_oled([
                        "ANALYSIS COMPLETE!",
                        "Saved to database",
                        "& local history",
                        "Press Nav to view"
                    ])
                print("Analysis saved to database and history successfully")
            elif db_success:
                if oled:
                    show_text_on_oled([
                        "ANALYSIS SAVED",
                        "Database: OK",
                        "History: failed",
                        "Press Nav to view"
                    ])
                print("Analysis saved to database, history save failed")
            elif history_success:
                if oled:
                    show_text_on_oled([
                        "ANALYSIS SAVED",
                        "Database: failed", 
                        "History: OK",
                        "Press Nav to view"
                    ])
                print("Analysis saved to history, database save failed")
            else:
                if oled:
                    show_text_on_oled([
                        "ANALYSIS RECEIVED",
                        "Save failed",
                        "",
                        "Press Nav to view"
                    ])
                print("Analysis received but both saves failed")
        else:
            print("Unexpected response format:", response)
            if oled:
                show_text_on_oled([
                    "RESPONSE ERROR",
                    "Check format",
                    "",
                    "See console"
                ])
        
    except Exception as e:
        print("Parse error:", e)
        if oled:
            show_text_on_oled([
                "PARSE ERROR",
                str(e)[:15],
                "",
                "Check response"
            ])

def send_hrv_request(rr_data=None):
    global mqtt_client, last_analysis
    if mqtt_client is None:
        return False
    
    # Ensure device and patient are registered first
    if not ensure_registrations():
        if oled:
            show_text_on_oled([
                "REGISTRATION",
                "FAILED",
                "",
                "Check connection"
            ])
        return False
    
    try:
        if rr_data is None or len(rr_data) < 10:
            # Use test data if no real data available
            test_rr = [828, 836, 852, 760, 800, 796, 856, 824, 808, 776, 
                       724, 816, 800, 812, 812, 812, 756, 820, 812, 800,
                       844, 832, 808, 792, 816, 804, 788, 824, 836, 820]
            rr_data = test_rr
            print("Using test RR data")
        else:
            print("Using real RR data:", len(rr_data), "intervals")
        
        payload = (
            "{"
            '"mac": "' + DEVICE_MAC + '",'
            '"type": "RRI",'
            '"data": [' + ",".join(str(x) for x in rr_data) + '],'
            '"analysis": { "type": "readiness" }'
            "}"
        )
        
        # Clear previous analysis
        last_analysis = None
        
        print("Sending payload:", payload[:100] + "..." if len(payload) > 100 else payload)
        mqtt_client.publish(b"kubios/request", payload)
        print("HRV request sent to Kubios")
        
        # Wait for response with timeout
        if oled:
            show_text_on_oled([
                "WAITING FOR",
                "KUBIOS...",
                "",
                "Exit: cancel"
            ])
        
        # Wait up to 15 seconds for response
        timeout = 150  # 15 seconds
        while timeout > 0 and last_analysis is None:
            if not exit_btn.value():
                utime.sleep_ms(50)
                if not exit_btn.value():
                    return "EXIT_REQUESTED"
            
            try:
                mqtt_client.check_msg()
            except:
                pass
            
            utime.sleep_ms(100)
            timeout -= 1
        
        if last_analysis is not None:
            print("Kubios analysis received successfully")
            return True
        else:
            print("Kubios response timeout")
            if oled:
                show_text_on_oled([
                    "NO RESPONSE",
                    "FROM KUBIOS",
                    "",
                    "Check server"
                ])
            return False
        
    except Exception as e:
        print("Send failed:", e)
        return False

# Legacy function for compatibility
def send_test_request():
    return send_hrv_request()

# ----------------- MAIN FUNCTION -----------------
def run(exit_button=None, display=None, enc=None):
    global mqtt_client, last_analysis, display_page, oled, exit_btn, connection_attempted

    # Use passed parameters if available
    if exit_button is not None:
        exit_btn = exit_button
    if display is not None:
        oled = display

    print("Kubios HRV Viewer starting")
    
    # Reset connections for clean start
    reset_connections()
    
    if oled:
        show_text_on_oled(["KUBIOS HRV", "Ready", "", "Nav: send test", "Exit: return"])

    while True:
        # Exit button check
        if not exit_btn.value():
            utime.sleep_ms(50)
            if not exit_btn.value():
                if last_analysis:
                    # If showing analysis, clear it and return to main menu
                    last_analysis = None
                    if oled:
                        reg_status = "Ready"
                        if device_registered and patient_registered:
                            reg_status = "Registered"
                        elif device_registered or patient_registered:
                            reg_status = "Partial reg"
                        
                        show_text_on_oled([
                            "KUBIOS HRV",
                            reg_status,
                            "",
                            "Nav: send HRV data",
                            "Exit: return"
                        ])
                    print("Cleared analysis, back to main menu")
                else:
                    # Exit the program
                    if oled:
                        show_text_on_oled(["Exiting..."])
                    print("Exiting Kubios HRV")
                    if mqtt_client:
                        try:
                            mqtt_client.disconnect()
                        except:
                            pass
                    return

        # Connection status display (no actual connection attempts in main loop)
        if not connection_attempted:
            connection_attempted = True
            if oled:
                reg_status = "Ready"
                if device_registered and patient_registered:
                    reg_status = "Registered"
                elif device_registered or patient_registered:
                    reg_status = "Partial reg"
                
                show_text_on_oled([
                    "KUBIOS HRV",
                    reg_status,
                    "",
                    "Nav: send HRV data",
                    "Exit: return"
                ])

        # Check for MQTT messages
        if mqtt_client:
            try:
                mqtt_client.check_msg()
            except:
                pass

        # Navigation button
        if not nav_btn.value():
            utime.sleep_ms(50)
            if not nav_btn.value():
                if last_analysis:
                    # Show analysis (single page now)
                    display_analysis_page(last_analysis, 0)
                else:
                    # Try to get HRV data and send to Kubios
                    if oled:
                        show_text_on_oled([
                            "CONNECTING...",
                            "",
                            "Exit: cancel",
                            "Please wait..."
                        ])
                    
                    # Connection attempt with exit check
                    wlan = connect_wifi()
                    if wlan == "EXIT_REQUESTED":
                        # User pressed exit during connection
                        if oled:
                            show_text_on_oled(["Exiting..."])
                        print("Exiting Kubios HRV")
                        return
                    elif wlan:
                        mqtt_client = connect_mqtt()
                        if mqtt_client == "EXIT_REQUESTED":
                            # User pressed exit during MQTT connection
                            if oled:
                                show_text_on_oled(["Exiting..."])
                            print("Exiting Kubios HRV")
                            return
                        elif mqtt_client:
                            # Get clean HRV data from HRVMonitor
                            hrv_data = get_hrv_data()
                            if hrv_data and len(hrv_data) >= 10:
                                if oled:
                                    show_text_on_oled([
                                        "SENDING CLEAN",
                                        "HRV DATA",
                                        "Beats: %d" % len(hrv_data),
                                        "Please wait..."
                                    ])
                                result = send_hrv_request(hrv_data)
                            else:
                                if oled:
                                    show_text_on_oled([
                                        "NO CLEAN DATA",
                                        "Need 30+ total beats",
                                        "in HRVMonitor",
                                        "Using test data..."
                                    ])
                                utime.sleep(3)
                                result = send_hrv_request()  # Use test data
                            
                            if result == "EXIT_REQUESTED":
                                if oled:
                                    show_text_on_oled(["Exiting..."])
                                print("Exiting Kubios HRV")
                                return
                            elif not result:
                                utime.sleep(2)  # Show error message briefly
                        else:
                            if oled:
                                show_text_on_oled([
                                    "MQTT failed",
                                    "",
                                    "Check settings"
                                ])
                            utime.sleep(2)
                    else:
                        if oled:
                            show_text_on_oled([
                                "WiFi failed",
                                "",
                                "Check network"
                            ])
                        utime.sleep(2)
                
                # Wait for button release
                while not nav_btn.value():
                    # Check exit button even while waiting for nav button release
                    if not exit_btn.value():
                        utime.sleep_ms(50)
                        if not exit_btn.value():
                            if oled:
                                show_text_on_oled(["Exiting..."])
                            print("Exiting Kubios HRV")
                            if mqtt_client:
                                try:
                                    mqtt_client.disconnect()
                                except:
                                    pass
                            return
                    utime.sleep_ms(10)

        utime.sleep_ms(10)

# Menu compatibility
def main(exit_button=None, display=None, enc=None):
    run(exit_button, display, enc)

if __name__ == "__main__":
    run()