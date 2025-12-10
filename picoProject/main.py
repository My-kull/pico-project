# Main launcher for HRV Monitoring System
# Animated heart startup screen

import time

def init_display():
    try:
        from machine import Pin, I2C
        from ssd1306 import SSD1306_I2C
        
        i2c = I2C(1, scl=Pin(15), sda=Pin(14))
        oled = SSD1306_I2C(128, 64, i2c)
        return oled
    except:
        return None

def draw_heart_frame(oled, frame):
    if oled is None:
        return
    
    oled.fill(0)
    
    # Heart animation frames
    if frame == 0 or frame == 3:  # Small heart - 13x13 pixels
        width, height = 13, 13
        heart_data = bytearray([
            0x7C, 0xFE, 0xFF, 0xFF, 0xFF, 0xFE, 0xFC, 0xFE,
            0xFF, 0xFF, 0xFF, 0xFE, 0x7C, 0x00, 0x00, 0x01,
            0x03, 0x07, 0x0F, 0x1F, 0x0F, 0x07, 0x03, 0x01,
            0x00, 0x00
        ])
        
    elif frame == 1:  # Medium heart - 16x16 pixels
        width, height = 16, 16
        heart_data = bytearray([
            0xF8, 0xFC, 0xFE, 0xFF, 0xFF, 0xFE, 0xFC, 0xF8, 
            0xF8, 0xFC, 0xFE, 0xFF, 0xFF, 0xFE, 0xFC, 0xF8, 
            0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFF, 0xFF, 
            0xFF, 0xFF, 0x7F, 0x3F, 0x1F, 0x0F, 0x07, 0x03
        ])
        
    else:  # frame == 2, Large heart - 20x20 pixels
        width, height = 20, 20
        heart_data = bytearray([
            0xF0, 0xF8, 0xFC, 0xFE, 0xFF, 0xFF, 0xFF, 0xFE, 
            0xFC, 0xF8, 0xF8, 0xFC, 0xFE, 0xFF, 0xFF, 0xFF, 
            0xFE, 0xFC, 0xF8, 0xF0, 0x07, 0x0F, 0x1F, 0x3F, 
            0x7F, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 
            0xFF, 0xFF, 0xFF, 0x7F, 0x3F, 0x1F, 0x0F, 0x07, 
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x03, 
            0x07, 0x0F, 0x0F, 0x07, 0x03, 0x01, 0x00, 0x00, 
            0x00, 0x00, 0x00, 0x00
        ])
    
    # Calculate center position for 128x64 screen
    start_x = (128 - width) // 2
    start_y = (64 - height) // 2
    
    import framebuf
    
    fbuf = framebuf.FrameBuffer(heart_data, width, height, framebuf.MONO_VLSB)
    oled.blit(fbuf, start_x, start_y)
    
    # Add text at bottom
    oled.text("HRV SYSTEM", 25, 54)
    oled.show()

def show_heart_animation(oled, duration=3):
    if oled is None:
        print("🫀 HRV SYSTEM 🫀")
        print("♥ Starting... ♥")
        time.sleep(duration)
        return
    
    frames = [0, 1, 2, 1]  # Small -> Medium -> Large -> Medium -> repeat
    beats_per_second = 1.2
    frame_duration = 1.0 / (beats_per_second * len(frames))
    
    total_frames = int(duration / frame_duration)
    
    for i in range(total_frames):
        frame_index = i % len(frames)
        draw_heart_frame(oled, frames[frame_index])
        time.sleep(frame_duration)
    
    # Final loading screen
    oled.fill(0)
    oled.text("HRV SYSTEM", 25, 20)
    oled.text("Loading...", 28, 35)
    oled.show()

def show_error(oled, error):
    """Show error on display"""
    if oled is None:
        return
    
    oled.fill(0)
    oled.text("ERROR:", 35, 10)
    oled.text("System failed", 15, 25)
    oled.text("to start", 30, 40)
    oled.show()

def main():
    print("Starting HRV System...")
    
    # Initialize display
    oled = init_display()
    
    # Show heart beating animation
    print("🫀 Showing startup animation...")
    show_heart_animation(oled, duration=3.5)
    
    try:
        print("Loading menu system...")
        
        # Import and run the main menu
        import Menu
        
        print("Menu system loaded successfully")
        
    except Exception as e:
        print("Error starting system:", e)
        
        # Show error on display
        show_error(oled, e)
        
        # Print detailed error
        import sys
        sys.print_exception(e)

# Run the main function
if __name__ == "__main__":
    main()