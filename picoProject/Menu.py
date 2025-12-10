# Settings application could be worth it?

from machine import Pin, I2C
from ssd1306 import SSD1306_I2C
from fifo import Fifo
import time
import os

# ----- CONFIG -----
WIDTH, HEIGHT = 128, 64
I2C_SDA, I2C_SCL = 14, 15
ENC_A, ENC_B, ENC_BTN = 10, 11, 12
EXIT_BTN = 9  # SW_0 button

# ----- DISPLAY -----
# Initialize display with error handling
def init_display():
    try:
        i2c = I2C(1, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA))
        oled = SSD1306_I2C(WIDTH, HEIGHT, i2c)
        print("Display initialized successfully")
        return oled
    except Exception as e:
        print("Display initialization failed:", e)
        return None

oled = init_display()

# ----- ENCODER USING INTERRUPT + FIFO -----
class Encoder:
    def __init__(self, pin_a, pin_b):
        self.a = Pin(pin_a, mode=Pin.IN, pull=Pin.PULL_UP)
        self.b = Pin(pin_b, mode=Pin.IN, pull=Pin.PULL_UP)
        self.fifo = Fifo(100, typecode='i')  # Increased size to prevent overflow

        self.a.irq(handler=self.handler, trigger=Pin.IRQ_RISING, hard=True)

    def handler(self, pin):
        # Simple direction logic: if B is high, counterclockwise
        # Add protection against FIFO overflow
        try:
            if self.b():
                self.fifo.put(-1)
            else:
                self.fifo.put(1)
        except:
            # FIFO full - ignore this input to prevent crash
            pass

# Create encoder and buttons
encoder = Encoder(ENC_A, ENC_B)
btn = Pin(ENC_BTN, Pin.IN, Pin.PULL_UP)
exit_btn = Pin(EXIT_BTN, Pin.IN, Pin.PULL_UP)

# ----- MENU ITEMS -----
menu_items = [
    "HRV Monitor",
    "Kubios HRV",
    "HRV History"
]
selected = 0

# ----- DRAW MENU -----
def draw_menu(selected):
    global oled
    if oled is None:
        # Print to console if no display
        print(f"Menu: {[f'> {item}' if i == selected else f'  {item}' for i, item in enumerate(menu_items)]}")
        return
    
    try:
        oled.fill(0)
        start = max(0, selected - 2)
        end = min(len(menu_items), start + 4)
        for i in range(start, end):
            y = (i - start) * 16
            if i == selected:
                oled.fill_rect(0, y, WIDTH, 16, 1)
                oled.text(menu_items[i], 2, y + 4, 0)
            else:
                oled.text(menu_items[i], 2, y + 4, 1)
        oled.show()
    except OSError as e:
        if e.errno == 110:  # ETIMEDOUT
            print("OLED timeout - disabling display")
            oled = None
            # Fall back to console
            print(f"Menu: {[f'> {item}' if i == selected else f'  {item}' for i, item in enumerate(menu_items)]}")
        else:
            raise

# ----- PROGRAM RUNNER -----
def run_program(name):
    print(f"Launching: {name}")
    if oled:
        oled.fill(0)
        oled.text("Launching:", 0, 20)
        oled.text(name, 0, 40)
        oled.show()
    time.sleep(1)

    if name == "HRV Monitor":
        try:
            import HRVMonitor
            if hasattr(HRVMonitor, "main"):
                HRVMonitor.main(exit_btn, oled, encoder)
        except Exception as e:
            print(f"Error running HRV Monitor: {e}")
            if oled:
                oled.fill(0)
                oled.text("Error:", 0, 20)
                oled.text(str(e)[:12], 0, 40)
                oled.show()
            time.sleep(2)
            
    elif name == "Kubios HRV":
        try:
            import KubiosHRV
            if hasattr(KubiosHRV, "main"):
                KubiosHRV.main(exit_btn, oled, encoder)
        except Exception as e:
            print(f"Error running Kubios HRV: {e}")
            if oled:
                oled.fill(0)
                oled.text("Error:", 0, 20)
                oled.text(str(e)[:12], 0, 40)
                oled.show()
            time.sleep(2)
            
    elif name == "HRV History":
        try:
            import HRVHistory
            if hasattr(HRVHistory, "main"):
                HRVHistory.main(exit_btn, oled, encoder)
        except Exception as e:
            print(f"Error running HRV History: {e}")
            if oled:
                oled.fill(0)
                oled.text("Error:", 0, 20)
                oled.text(str(e)[:12], 0, 40)
                oled.show()
            time.sleep(2)
    
    else:
        print("No program available")
        if oled:
            oled.fill(0)
            oled.text("No program", 0, 20)
            oled.text("available", 0, 36)
            oled.show()
        time.sleep(1)

    # Clear encoder FIFO to avoid stale inputs when returning to menu
    while encoder.fifo.has_data():
        encoder.fifo.get()
    
    # Redraw menu after program ends
    draw_menu(selected)

# ----- MAIN LOOP -----
draw_menu(selected)
last_move_time = time.ticks_ms()

while True:
    # --- Rotary movement ---
    if encoder.fifo.has_data():
        try:
            move = encoder.fifo.get()
            selected = max(0, min(len(menu_items) - 1, selected + move))
            draw_menu(selected)
        except Exception as e:
            print(f"Encoder error: {e}")
            # Clear FIFO on error to recover
            while encoder.fifo.has_data():
                try:
                    encoder.fifo.get()
                except:
                    break

    # --- Button press to launch ---
    if not btn.value():
        # Clear any pending encoder inputs before launching program
        while encoder.fifo.has_data():
            encoder.fifo.get()
        
        run_program(menu_items[selected])
        time.sleep(0.5)  # debounce

    time.sleep(0.01)